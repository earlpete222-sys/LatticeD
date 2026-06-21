"""Sprint 43 — Reliability pass: graceful degradation, warm-up, eval teardown.

Unit tests that don't require a live LatticeD server or Ollama. They cover:
- classify_inference_exception buckets transport/timeout/missing-model errors
- user_facing_inference_error returns actionable text per bucket
- grounding_node emits GROUNDING_UNAVAILABLE when Tavily fails / returns empty
- runtime.warm_models honors LATTICED_WARM_MODELS and records per-model status
- eval_harness teardown DELETEs every used thread and conditionally purges beliefs

The tests stub out network calls and the Tavily/ollama clients so they run in
milliseconds and stay green in CI without external dependencies.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
sys.path.insert(0, str(HERE.parent))

import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


# ── classify_inference_exception ─────────────────────────────────────────────
def test_classify_buckets():
    cls = L.classify_inference_exception

    check("timeout bucket", cls(asyncio.TimeoutError()) == "timeout")

    check(
        "ollama_down (connection refused)",
        cls(ConnectionError("Connection refused on 127.0.0.1:11434")) == "ollama_down",
    )
    check(
        "ollama_down (max retries)",
        cls(RuntimeError("HTTPConnectionPool: Max retries exceeded")) == "ollama_down",
    )
    check(
        "ollama_down (winerror 10061)",
        cls(OSError("WinError 10061: target machine actively refused")) == "ollama_down",
    )
    check(
        "model_missing bucket",
        cls(RuntimeError("model not found, try pulling first")) == "model_missing",
    )
    check("other bucket", cls(ValueError("schema mismatch")) == "other")

    # Cause chain — original transport error wrapped in a generic RuntimeError.
    try:
        try:
            raise ConnectionError("connection refused")
        except ConnectionError as e:
            raise RuntimeError("agent failed") from e
    except RuntimeError as wrapped:
        check("classify follows __cause__", cls(wrapped) == "ollama_down")


# ── user_facing_inference_error ──────────────────────────────────────────────
def test_user_facing_text():
    f = L.user_facing_inference_error
    msg = f("ollama_down")
    check("ollama_down msg mentions Ollama", "Ollama" in msg)
    check("ollama_down msg shows host", L.OLLAMA_HOST in msg)

    msg = f("model_missing", "deepseek-r1:1.5b")
    check("model_missing msg includes detail", "deepseek-r1:1.5b" in msg)
    check("model_missing msg mentions pull", "ollama pull" in msg)

    check("timeout msg actionable", "shorter" in f("timeout"))
    check("other bucket returns empty", f("other") == "")


# ── grounding_node — Tavily failure modes ────────────────────────────────────
def _run_grounding(state: dict, tavily_client) -> tuple[dict, str]:
    """Drop a stub tavily_client into runtime, call grounding_node, and return
    (node_output, tavily_last_status_after_call). Status is captured before the
    client is restored so callers can assert on it without race conditions.
    """
    orig_client = L.runtime.tavily_client
    L.runtime.tavily_client = tavily_client
    L.runtime.tavily_last_status = ""   # reset so each call observes its own write
    try:
        out = asyncio.get_event_loop().run_until_complete(L.grounding_node(state))
        return out, L.runtime.tavily_last_status
    finally:
        L.runtime.tavily_client = orig_client


def test_grounding_marks_unavailable_on_exception():
    class _Boom:
        def search(self, *a, **kw):
            raise ConnectionError("tavily.com unreachable")

    out, status = _run_grounding(
        {"user_input": "what is the fed funds rate", "intent_category": "research"},
        _Boom(),
    )
    ctx = out["grounding_context"]
    check("exception → GROUNDING_UNAVAILABLE marker", "GROUNDING_UNAVAILABLE" in ctx)
    check("marker tells agents to disclaim", "may not reflect recent events" in ctx)
    check("status recorded", status.startswith("error:"), f"got {status!r}")


def test_grounding_marks_unavailable_on_empty_results():
    class _Empty:
        def search(self, *a, **kw):
            return {"results": []}

    out, _ = _run_grounding(
        {"user_input": "obscure topic", "intent_category": "research"},
        _Empty(),
    )
    check("empty results → GROUNDING_UNAVAILABLE",
          "GROUNDING_UNAVAILABLE" in out["grounding_context"])


def test_grounding_ok_path_marks_status():
    class _Good:
        def search(self, *a, **kw):
            return {"results": [{"url": "https://example.com/x", "content": "fed rate is 3.80%"}]}

    out, status = _run_grounding(
        {"user_input": "fed rate", "intent_category": "research"},
        _Good(),
    )
    check("ok path emits VERIFIED WEB SOURCES",
          "VERIFIED WEB SOURCES" in out["grounding_context"])
    check("ok path records status=ok", status == "ok", f"got {status!r}")


def test_grounding_skips_when_no_provider_and_chat_intent():
    out, _ = _run_grounding(
        {"user_input": "hi", "intent_category": "chat"},
        None,
    )
    check("chat intent without provider — no UNAVAILABLE marker",
          "GROUNDING_UNAVAILABLE" not in out["grounding_context"])


def test_grounding_marks_unavailable_when_research_intent_but_no_provider():
    out, _ = _run_grounding(
        {"user_input": "what is happening in markets", "intent_category": "research"},
        None,
    )
    check("research intent + no provider → UNAVAILABLE marker",
          "GROUNDING_UNAVAILABLE" in out["grounding_context"])


# ── warm_models honors env flag + per-model status ───────────────────────────
def test_warm_models_disabled_by_env():
    with patch.dict(os.environ, {"LATTICED_WARM_MODELS": "0"}):
        # WARM_MODELS_ENABLED is captured at import time; patch the module flag
        # for this test rather than re-importing the 11k-line module.
        with patch.object(L, "WARM_MODELS_ENABLED", False):
            status = asyncio.get_event_loop().run_until_complete(
                L.runtime.warm_models(["fake-model"])
            )
    check("disabled flag → skipped status", status == {"fake-model": "skipped"})


def test_warm_models_records_ok_and_error():
    # Stub the ollama_client.generate so we can simulate ok + failure without
    # touching a real Ollama process.
    calls = []

    def _fake_generate(model, prompt, options):
        calls.append(model)
        if model == "good":
            return {"response": "ok"}
        raise ConnectionError("connection refused on 127.0.0.1:11434")

    fake_module = SimpleNamespace(generate=_fake_generate)
    with patch.object(L, "WARM_MODELS_ENABLED", True), \
         patch.object(L, "OLLAMA_DIRECT_AVAILABLE", True), \
         patch.object(L, "ollama_client", fake_module):
        status = asyncio.get_event_loop().run_until_complete(
            L.runtime.warm_models(["good", "bad"])
        )
    check("both models attempted", set(calls) == {"good", "bad"})
    check("good model marked ok", status["good"] == "ok")
    check("bad model bucketed as ollama_down",
          status["bad"] == "error:ollama_down", f"got {status['bad']}")


def test_warm_models_missing_client():
    with patch.object(L, "WARM_MODELS_ENABLED", True), \
         patch.object(L, "OLLAMA_DIRECT_AVAILABLE", False):
        status = asyncio.get_event_loop().run_until_complete(
            L.runtime.warm_models(["m"])
        )
    check("missing client recorded as error",
          status["m"] == "error:ollama_client_missing")


# ── eval_harness teardown — DELETE every thread + conditional belief wipe ────
def test_eval_harness_teardown_deletes_threads_only():
    import importlib
    eh = importlib.import_module("eval_harness")

    # Reset module state to a clean slate for this test.
    eh.USED_THREAD_IDS.clear()
    eh._BELIEFS_TOUCHED = False
    eh.USED_THREAD_IDS.extend(["eval_aaaa1111", "eval_bbbb2222", "eval_aaaa1111"])

    calls: list[tuple[str, str]] = []

    class _FakeResp:
        status_code = 200

    def _fake_delete(url, **kw):
        calls.append(("DELETE", url))
        return _FakeResp()

    with patch.object(eh._requests_lib, "delete", _fake_delete):
        summary = eh.teardown("http://x", "k")

    deleted_urls = [u for _, u in calls]
    check("each unique thread deleted exactly once",
          deleted_urls == [
              "http://x/api/threads/eval_aaaa1111",
              "http://x/api/threads/eval_bbbb2222",
          ],
          f"got {deleted_urls}")
    check("summary counts dedupe", summary["threads_deleted"] == 2)
    check("no belief purge when no seed test ran", summary["beliefs_purged"] is False)


def test_eval_harness_teardown_purges_beliefs_when_seeded():
    import importlib
    eh = importlib.import_module("eval_harness")

    eh.USED_THREAD_IDS.clear()
    eh.USED_THREAD_IDS.append("eval_cccc3333")
    eh._BELIEFS_TOUCHED = True

    seen: list[str] = []

    class _R:
        status_code = 200

    def _fake_delete(url, **kw):
        seen.append(url)
        return _R()

    with patch.object(eh._requests_lib, "delete", _fake_delete):
        summary = eh.teardown("http://x", "k")

    check("belief endpoint hit when seed-test ran",
          "http://x/api/beliefs" in seen)
    check("summary records belief purge", summary["beliefs_purged"] is True)


def test_eval_harness_teardown_swallows_failures():
    import importlib
    eh = importlib.import_module("eval_harness")
    eh.USED_THREAD_IDS.clear()
    eh.USED_THREAD_IDS.append("eval_dddd4444")
    eh._BELIEFS_TOUCHED = False

    def _explode(url, **kw):
        raise ConnectionError("server gone")

    with patch.object(eh._requests_lib, "delete", _explode):
        summary = eh.teardown("http://x", "k")  # must not raise
    check("transport failure does not raise",
          summary["thread_failures"] == 1 and summary["threads_deleted"] == 0)


# ── Runner ───────────────────────────────────────────────────────────────────
TESTS = [
    test_classify_buckets,
    test_user_facing_text,
    test_grounding_marks_unavailable_on_exception,
    test_grounding_marks_unavailable_on_empty_results,
    test_grounding_ok_path_marks_status,
    test_grounding_skips_when_no_provider_and_chat_intent,
    test_grounding_marks_unavailable_when_research_intent_but_no_provider,
    test_warm_models_disabled_by_env,
    test_warm_models_records_ok_and_error,
    test_warm_models_missing_client,
    test_eval_harness_teardown_deletes_threads_only,
    test_eval_harness_teardown_purges_beliefs_when_seeded,
    test_eval_harness_teardown_swallows_failures,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:  # pragma: no cover
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 43 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
