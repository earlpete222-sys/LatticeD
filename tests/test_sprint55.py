"""Sprint 55 — UI v2 toggle + status + reflection trigger.

UI behavior is JavaScript inside a single HTML file; the only thing
unit tests can lock down is the contract between the UI and the
backend (event shapes the UI parses, endpoints + payload shape the
UI calls) plus static checks that the new UI surface area is wired in.

Tests cover:
  - /api/v2/chat emits the four node events + Final with the exact
    fields the UI's v2 ticker reads (engine='v2' branch in ChatView.send)
  - /api/v2/reflect POST returns the keys the UI displays in the
    reflection result message
  - /api/v2/stats returns the keys the new v2 status panel reads
  - ui_v2.html contains the engine selector + v2 ticker + Settings panel
    + the localStorage persistence key
  - README and MOBILE.md mention the v2 engine
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

# Isolate v2 stores so the test doesn't touch the user's real data.
_TMP_KSTORE = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False)
_TMP_KSTORE.close()
_TMP_TURNLOG = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False)
_TMP_TURNLOG.close()
os.environ["LATTICED_V2_KSTORE_PATH"] = _TMP_KSTORE.name
os.environ["LATTICED_V2_TURNLOG_PATH"] = _TMP_TURNLOG.name

_TMP_V1 = tempfile.NamedTemporaryFile(suffix="_v1.db", delete=False)
_TMP_V1.close()
os.environ["LATTICED_V1_DB_PATH"] = _TMP_V1.name

# Load latticed.py the main module under a private name (file vs package
# collision; same pattern as Sprint 53/54).
_spec = importlib.util.spec_from_file_location(
    "_latticed_main", REPO_ROOT / "latticed" / "latticed.py"
)
L = importlib.util.module_from_spec(_spec)
sys.modules["_latticed_main"] = L
_spec.loader.exec_module(L)

from latticed.v2.runtime import V2Runtime  # noqa: E402
from latticed.v2.strategies import StubNarratorBackend  # noqa: E402


results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


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


# ── Backend contract: events the UI v2 ticker reads ───────────────────────
def test_v2_chat_emits_keys_ui_consumes():
    """The UI's v2 branch in send() reads ev.intent, ev.mood, ev.strategy_name,
    ev.used_fallback, ev.verdict, ev.elapsed_ms on Final. Lock those keys in."""
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    ks = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False); ks.close()
    tl = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False); tl.close()
    rt = V2Runtime(
        kstore_path=Path(ks.name), turn_log_path=Path(tl.name),
        backend=StubNarratorBackend({
            "reflection": "A real moment with your dad.",
            "question": "What stood out?",
        }),
    )
    L._v2_runtime = rt
    with TestClient(L.app) as client:
        r = client.get(
            "/api/v2/chat",
            params={"prompt": "Sunday was Father's Day I spoke with my dad"},
            headers={"x-api-key": L.ACTIVE_SECRET},
        )
    check("/api/v2/chat 200", r.status_code == 200)
    events = _drain_sse(r.text)
    nodes_by_name = {e.get("node"): e for e in events if "node" in e}
    final = next((e for e in events if e.get("phase") == "Final"), None)

    # Perceive event keys the v2 ticker reads (intent, mood)
    perceive = nodes_by_name.get("perceive") or {}
    check("perceive event has 'intent'", "intent" in perceive,
          f"keys={sorted(perceive.keys())}")
    check("perceive event has 'mood'", "mood" in perceive)

    # Strategy event keys (strategy_name)
    strat = nodes_by_name.get("strategy") or {}
    check("strategy event has 'strategy_name'", "strategy_name" in strat)

    # Narrate event keys (used_fallback)
    narrate = nodes_by_name.get("narrate") or {}
    check("narrate event has 'used_fallback'", "used_fallback" in narrate)

    # Review event keys (verdict)
    review = nodes_by_name.get("review") or {}
    check("review event has 'verdict'", "verdict" in review)

    # Final event keys
    check("Final present", final is not None)
    if final:
        for k in ("content", "strategy", "verdict", "used_fallback", "elapsed_ms"):
            check(f"Final has '{k}'", k in final, f"keys={sorted(final.keys())}")

    rt.close()
    L._v2_runtime = None


def test_v2_reflect_returns_keys_ui_reads():
    """The Settings panel's reflection result message reads turns_processed,
    entities_created, relations_created, events_created, proposals_deferred."""
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    ks = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False); ks.close()
    tl = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False); tl.close()
    rt = V2Runtime(
        kstore_path=Path(ks.name), turn_log_path=Path(tl.name),
        backend=StubNarratorBackend({
            "reflection": "A real moment with your dad.",
            "question": "What stood out?",
        }),
    )
    L._v2_runtime = rt
    with TestClient(L.app) as client:
        # Force one turn so reflection has something to process.
        client.get(
            "/api/v2/chat",
            params={"prompt": "My friend Alex came by today"},
            headers={"x-api-key": L.ACTIVE_SECRET},
        )
        r = client.post(
            "/api/v2/reflect",
            headers={"x-api-key": L.ACTIVE_SECRET},
        )
    check("/api/v2/reflect 200", r.status_code == 200)
    body = r.json()
    for k in ("turns_processed", "entities_created", "relations_created",
              "events_created", "proposals_deferred"):
        check(f"reflect response has '{k}'", k in body,
              f"keys={sorted(body.keys())}")
    rt.close()
    L._v2_runtime = None


def test_v2_stats_returns_keys_ui_reads():
    """v2 status panel reads kstore.{live_entities,live_events,live_relations,
    legacy_beliefs}, turns.{total,unprocessed}, backend_attached."""
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    ks = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False); ks.close()
    tl = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False); tl.close()
    rt = V2Runtime(
        kstore_path=Path(ks.name), turn_log_path=Path(tl.name),
        backend=StubNarratorBackend(),
    )
    L._v2_runtime = rt
    with TestClient(L.app) as client:
        r = client.get("/api/v2/stats", headers={"x-api-key": L.ACTIVE_SECRET})
    check("/api/v2/stats 200", r.status_code == 200)
    body = r.json()
    ks_keys = body.get("kstore", {})
    for k in ("live_entities", "live_events", "live_relations", "legacy_beliefs"):
        check(f"stats.kstore.{k} present", k in ks_keys)
    turn_keys = body.get("turns", {})
    for k in ("total", "unprocessed"):
        check(f"stats.turns.{k} present", k in turn_keys)
    check("stats.backend_attached present", "backend_attached" in body)
    rt.close()
    L._v2_runtime = None


# ── UI surface area: engine selector wired in ─────────────────────────────
def test_ui_has_engine_selector():
    src = (REPO_ROOT / "latticed" / "ui_v2.html").read_text(encoding="utf-8")
    check("ChatView declares 'engine' state",
          "const [engine, setEngine] = useState" in src
          or "[engine, setEngine] = useState" in src)
    check("engine persists to localStorage",
          "localStorage.setItem('latticed_engine'" in src or
          "'latticed_engine'" in src)
    check("engine v1 button present", "engine v1" in src)
    check("engine v2 button present", "engine v2 (beta)" in src or "engine v2" in src)
    check("v2 endpoint URL referenced",
          "/api/v2/chat" in src)


def test_ui_has_v2_ticker_branches():
    src = (REPO_ROOT / "latticed" / "ui_v2.html").read_text(encoding="utf-8")
    check("v2 step list state present",
          "v2Steps" in src and "setV2Steps" in src)
    check("v2 final state present",
          "v2Final" in src and "setV2Final" in src)
    check("ticker handles perceive/strategy/narrate/review",
          all(node in src for node in ("perceive", "strategy", "narrate", "review")))


def test_ui_has_v2_settings_panel():
    src = (REPO_ROOT / "latticed" / "ui_v2.html").read_text(encoding="utf-8")
    check("Settings has 'v2 Engine' section",
          "v2 Engine" in src)
    check("Settings loads /api/v2/stats",
          "/api/v2/stats" in src)
    check("Settings has Run reflection button",
          "Run reflection" in src)
    check("Settings posts /api/v2/reflect",
          "/api/v2/reflect" in src)


# ── Docs reference v2 ────────────────────────────────────────────────────
def test_readme_mentions_v2_engine():
    r = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    check("README has 'v2 engine' heading",
          "v2 engine" in r.lower() or "v2 (beta)" in r.lower())
    check("README references /api/v2/chat", "/api/v2/chat" in r)
    check("README points to V2_ARCHITECTURE.md", "V2_ARCHITECTURE.md" in r)


def test_mobile_md_mentions_v2_toggle():
    m = (REPO_ROOT / "MOBILE.md").read_text(encoding="utf-8")
    check("MOBILE.md mentions engine v1/v2",
          "engine v1" in m and "engine v2" in m)
    check("MOBILE.md mentions Run reflection",
          "Run reflection" in m)


# ── Runner ───────────────────────────────────────────────────────────────
TESTS = [
    test_v2_chat_emits_keys_ui_consumes,
    test_v2_reflect_returns_keys_ui_reads,
    test_v2_stats_returns_keys_ui_reads,
    test_ui_has_engine_selector,
    test_ui_has_v2_ticker_branches,
    test_ui_has_v2_settings_panel,
    test_readme_mentions_v2_engine,
    test_mobile_md_mentions_v2_toggle,
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
    print(f"\n{passed}/{passed + failed} Sprint 55 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
