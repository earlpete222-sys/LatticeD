"""Sprint 53 — v2 runtime + /api/v2/chat endpoint + A/B harness.

End-to-end tests of the v2 pipeline exposed as an HTTP endpoint, plus
unit tests for the runtime/backend wrappers and the A/B scoring logic.

The endpoint test uses FastAPI's TestClient + a StubNarratorBackend so
the full SSE event stream can be verified without a live Ollama. We
attach the stub to V2Runtime before the endpoint is hit; the lazy
init in latticed.py honors the pre-attached backend.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
# latticed/ directory is treated as a namespace package so v2 imports work
sys.path.insert(0, str(REPO_ROOT))

# Point the v2 runtime at a temp DB *before* importing latticed (the v2
# runtime resolves its path from env at construction time).
_TMP_KSTORE = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False)
_TMP_KSTORE.close()
os.environ["LATTICED_V2_KSTORE_PATH"] = _TMP_KSTORE.name
# Also point v1 db to a tempfile so the migration noop path is taken.
_TMP_V1 = tempfile.NamedTemporaryFile(suffix="_v1.db", delete=False)
_TMP_V1.close()
os.environ["LATTICED_V1_DB_PATH"] = _TMP_V1.name

# latticed.py (the main module containing the FastAPI app) and the
# latticed/ package share a name; importing both is normally a conflict.
# Load the main module via importlib under a private name so it coexists.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location(
    "_latticed_main", REPO_ROOT / "latticed" / "latticed.py"
)
L = importlib.util.module_from_spec(_spec)
sys.modules["_latticed_main"] = L
_spec.loader.exec_module(L)

from latticed.v2.runtime import (  # noqa: E402
    OllamaNarratorBackend, V2Runtime,
)
from latticed.v2.strategies import StubNarratorBackend, Slot  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── OllamaNarratorBackend: stubbed ollama client ──────────────────────────
def test_ollama_backend_calls_generate_with_slot_options():
    captured: dict = {}

    def _generate(*, model, prompt, options):
        captured["model"] = model
        captured["prompt"] = prompt
        captured["options"] = options
        return {"response": "  Your dad sounds great. "}

    fake = SimpleNamespace(generate=_generate)
    be = OllamaNarratorBackend(ollama_client=fake, model_name="x:1b")
    slot = Slot.model(
        name="r", prompt="say something",
        fallback_value="fallback",
        temperature=0.55, max_tokens=80,
    )
    out = _run(be.fill_model_slot(slot, {}))
    check("backend strips and returns model text",
          out == "Your dad sounds great.")
    check("model name forwarded", captured["model"] == "x:1b")
    check("slot prompt forwarded", captured["prompt"] == "say something")
    check("slot temperature forwarded",
          captured["options"]["temperature"] == 0.55)
    check("slot max_tokens forwarded",
          captured["options"]["num_predict"] == 80)


def test_ollama_backend_strips_think_blocks():
    def _generate(*, model, prompt, options):
        return {"response": "<think>reasoning</think>Your dad sounds great."}

    fake = SimpleNamespace(generate=_generate)
    be = OllamaNarratorBackend(ollama_client=fake)
    slot = Slot.model(name="r", prompt="x", fallback_value="fb")
    out = _run(be.fill_model_slot(slot, {}))
    check("<think> blocks stripped",
          "<think>" not in out and out == "Your dad sounds great.")


def test_ollama_backend_falls_back_on_exception():
    def _generate(**kw):
        raise ConnectionError("ollama down")

    fake = SimpleNamespace(generate=_generate)
    be = OllamaNarratorBackend(ollama_client=fake)
    slot = Slot.model(name="r", prompt="x", fallback_value="safe fallback")
    out = _run(be.fill_model_slot(slot, {}))
    check("connection error -> slot fallback returned",
          out == "safe fallback")


def test_ollama_backend_falls_back_on_timeout():
    def _slow_generate(**kw):
        import time as _t
        _t.sleep(2.0)
        return {"response": "too late"}

    fake = SimpleNamespace(generate=_slow_generate)
    be = OllamaNarratorBackend(ollama_client=fake, timeout_s=0.2)
    slot = Slot.model(name="r", prompt="x", fallback_value="safe fallback")
    out = _run(be.fill_model_slot(slot, {}))
    check("timeout -> slot fallback returned",
          out == "safe fallback")


# ── V2Runtime: init + migration ───────────────────────────────────────────
def test_v2runtime_init_creates_singletons():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    rt = V2Runtime(kstore_path=Path(tmp.name), backend=StubNarratorBackend())
    stats = rt.kstore.stats()
    check("V2Runtime creates kstore with USER+SYSTEM singletons",
          stats["live_entities"] == 2)
    check("backend attached", rt.backend is not None)
    rt.close()


def test_v2runtime_attach_backend_late_binds():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    rt = V2Runtime(kstore_path=Path(tmp.name))
    check("backend starts None", rt.backend is None)
    rt.attach_backend(StubNarratorBackend())
    check("backend attached after init", rt.backend is not None)
    rt.close()


def test_v2runtime_maybe_migrate_is_idempotent_and_skips_when_populated():
    import sqlite3
    # Build a tiny v1-shaped db with one belief
    v1 = tempfile.NamedTemporaryFile(suffix="_v1.db", delete=False)
    v1.close()
    conn = sqlite3.connect(v1.name)
    conn.execute(
        "CREATE TABLE belief_graph ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT UNIQUE, "
        "confidence REAL, last_seen REAL, source TEXT, categories TEXT)"
    )
    conn.execute("INSERT INTO belief_graph (fact, confidence, last_seen) "
                 "VALUES ('user enjoys hiking', 0.9, 1.0)")
    conn.commit()
    conn.close()

    ks = tempfile.NamedTemporaryFile(suffix="_ks.db", delete=False)
    ks.close()
    rt = V2Runtime(kstore_path=Path(ks.name), v1_db_path=Path(v1.name))
    report1 = rt.maybe_migrate_v1()
    check("first migration runs", report1.get("typed_records_created", 0) >= 1)
    report2 = rt.maybe_migrate_v1()
    check("second call: no-op (already attempted)",
          report2 == {})
    rt.close()


def test_v2runtime_skip_migration_when_store_non_empty():
    # If store already has entities/events/relations beyond singletons,
    # migration should skip even on first call.
    from latticed.v2.kstore import Entity, EntityKind
    import sqlite3
    v1 = tempfile.NamedTemporaryFile(suffix="_v1.db", delete=False)
    v1.close()
    conn = sqlite3.connect(v1.name)
    conn.execute(
        "CREATE TABLE belief_graph (id INTEGER PRIMARY KEY, fact TEXT)"
    )
    conn.execute("INSERT INTO belief_graph (fact) VALUES ('user enjoys hiking')")
    conn.commit()
    conn.close()

    ks = tempfile.NamedTemporaryFile(suffix="_ks.db", delete=False)
    ks.close()
    rt = V2Runtime(kstore_path=Path(ks.name), v1_db_path=Path(v1.name))
    # Pre-populate to exceed singleton count
    rt.kstore.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.PERSON, name="Dad",
    ))
    report = rt.maybe_migrate_v1()
    check("populated store skips migration", report == {})
    rt.close()


# ── /api/v2/chat endpoint via TestClient ──────────────────────────────────
def _drain_sse(text: str) -> list[dict]:
    out: list[dict] = []
    for blob in text.split("\n\n"):
        for line in blob.split("\n"):
            line = line.strip()
            if not line.startswith("data: "):
                continue
            try:
                out.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return out


def test_v2_chat_endpoint_streams_full_pipeline():
    """Hit /api/v2/chat with the live Father's Day failure prompt. The
    response must (a) emit all four node events + Final, (b) NOT contain
    'we talked' or 'amazing personality', (c) include 'your dad' or
    'Father's Day' anchor."""
    from fastapi.testclient import TestClient

    # Reset module-level v2 runtime so we control its backend.
    L._v2_runtime = None
    # Build a stub backend pre-loaded with CLEAN responses so we don't
    # need a live Ollama. We patch _get_v2_runtime to return our rig.
    rt = V2Runtime(
        kstore_path=Path(os.environ["LATTICED_V2_KSTORE_PATH"]),
        backend=StubNarratorBackend({
            "reflection": "A Father's Day conversation with your dad — that's a real moment.",
            "question": "What did the two of you end up talking about?",
        }),
    )
    L._v2_runtime = rt

    with TestClient(L.app) as client:
        r = client.get(
            "/api/v2/chat",
            params={"prompt": "Sunday was Father's Day I spoke with my dad had a great conversation"},
            headers={"x-api-key": L.ACTIVE_SECRET},
        )
    check("/api/v2/chat 200", r.status_code == 200, f"got {r.status_code}")
    events = _drain_sse(r.text)
    nodes = [e.get("node") for e in events if "node" in e]
    finals = [e for e in events if e.get("phase") == "Final"]
    check("emits perceive event", "perceive" in nodes)
    check("emits strategy event", "strategy" in nodes)
    check("emits narrate event", "narrate" in nodes)
    check("emits review event", "review" in nodes)
    check("emits Final event", len(finals) == 1)
    if finals:
        content = finals[0].get("content", "")
        check("Final content has 'your dad'",
              "your dad" in content, f"got {content!r}")
        check("Final content has 'Father's Day' anchor",
              "Father's Day" in content)
        check("Final content NEVER contains 'we talked'",
              "we talked" not in content.lower())
        check("Final content NEVER contains 'amazing personality'",
              "amazing personality" not in content.lower())
        check("Final has verdict field",
              "verdict" in finals[0])
        check("Final has strategy field",
              finals[0].get("strategy") == "acknowledge_event")
    rt.close()
    L._v2_runtime = None


def test_v2_chat_requires_auth():
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    rt = V2Runtime(
        kstore_path=Path(os.environ["LATTICED_V2_KSTORE_PATH"]),
        backend=StubNarratorBackend(),
    )
    L._v2_runtime = rt
    with TestClient(L.app) as client:
        r = client.get("/api/v2/chat", params={"prompt": "hi"},
                       headers={"x-api-key": "wrong-key"})
    check("/api/v2/chat without valid key: 401",
          r.status_code == 401, f"got {r.status_code}")
    rt.close()
    L._v2_runtime = None


def test_v2_stats_endpoint():
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    rt = V2Runtime(
        kstore_path=Path(os.environ["LATTICED_V2_KSTORE_PATH"]),
        backend=StubNarratorBackend(),
    )
    L._v2_runtime = rt
    with TestClient(L.app) as client:
        r = client.get("/api/v2/stats", headers={"x-api-key": L.ACTIVE_SECRET})
    check("/api/v2/stats 200", r.status_code == 200)
    body = r.json()
    check("stats has kstore.live_entities",
          "kstore" in body and "live_entities" in body["kstore"])
    check("stats reports backend attached",
          body.get("backend_attached") is True)
    rt.close()
    L._v2_runtime = None


# ── A/B harness scoring logic ─────────────────────────────────────────────
def test_score_output_flags_banned_plural():
    import eval_v2_vs_v1 as ab
    probe = ab.Probe(id="x", prompt="I spoke with my dad",
                     description="test", expected_shape_hint="two_beat")
    outcome = ab.score_output(probe, "we talked. what about?")
    check("score: banned plural -> fatal failure",
          "no_banned_plural" in outcome.fatal_failures)


def test_score_output_flags_forbid_substring():
    import eval_v2_vs_v1 as ab
    probe = ab.Probe(
        id="x", prompt="Sunday was Father's Day I spoke with my dad",
        description="test",
        expected_shape_hint="two_beat",
        forbid=("amazing personality",),
    )
    outcome = ab.score_output(probe, "He had such an amazing personality.")
    check("score: forbid substring tracked", outcome.forbid_hits == ["amazing personality"])


def test_score_output_clean_passes():
    import eval_v2_vs_v1 as ab
    probe = ab.Probe(
        id="x", prompt="Sunday was Father's Day I spoke with my dad",
        description="test",
        expected_shape_hint="two_beat",
    )
    outcome = ab.score_output(
        probe,
        "A Father's Day conversation with your dad. What stood out?",
    )
    check("score: clean output passes",
          outcome.passed, f"failures={outcome.fatal_failures}, "
          f"checks={outcome.checks}")


def test_migration_gate_requires_v2_results():
    import eval_v2_vs_v1 as ab
    ok, reasons = ab.migration_gate_passed({})
    check("empty summary fails gate", not ok)


def test_migration_gate_rejects_low_pass_rate():
    import eval_v2_vs_v1 as ab
    summary = {
        "v1": {"pass_rate": 0.9, "fabrication_rate": 0.1, "median_elapsed_s": 5.0},
        "v2": {"pass_rate": 0.85, "fabrication_rate": 0.0, "median_elapsed_s": 5.0},
    }
    ok, reasons = ab.migration_gate_passed(summary)
    check("v2 pass_rate 0.85 < 0.95 -> gate fails", not ok)


def test_migration_gate_accepts_clean_v2():
    import eval_v2_vs_v1 as ab
    summary = {
        "v1": {"pass_rate": 0.7, "fabrication_rate": 0.3, "median_elapsed_s": 10.0},
        "v2": {"pass_rate": 0.97, "fabrication_rate": 0.02, "median_elapsed_s": 8.0},
    }
    ok, reasons = ab.migration_gate_passed(summary)
    check("clean v2 passes gate", ok, f"reasons={reasons}")


# ── Runner ────────────────────────────────────────────────────────────────
TESTS = [
    test_ollama_backend_calls_generate_with_slot_options,
    test_ollama_backend_strips_think_blocks,
    test_ollama_backend_falls_back_on_exception,
    test_ollama_backend_falls_back_on_timeout,
    test_v2runtime_init_creates_singletons,
    test_v2runtime_attach_backend_late_binds,
    test_v2runtime_maybe_migrate_is_idempotent_and_skips_when_populated,
    test_v2runtime_skip_migration_when_store_non_empty,
    test_v2_chat_endpoint_streams_full_pipeline,
    test_v2_chat_requires_auth,
    test_v2_stats_endpoint,
    test_score_output_flags_banned_plural,
    test_score_output_flags_forbid_substring,
    test_score_output_clean_passes,
    test_migration_gate_requires_v2_results,
    test_migration_gate_rejects_low_pass_rate,
    test_migration_gate_accepts_clean_v2,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            import traceback as tb
            results.append((fn.__name__, "FAIL",
                            f"raised {type(exc).__name__}: {exc}\n"
                            + tb.format_exc().splitlines()[-3]))
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 53 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
