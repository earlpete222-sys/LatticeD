"""Sprint 35 - recall-mode guarantees tests."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

BELIEF_CTX = ("BELIEF GRAPH:\n"
              "  [0.76 | rel 0.32] I go hiking almost every Saturday morning.\n"
              "  [0.76 | rel 0.31] My favorite weekend activity is hiking.\n"
              "  [0.76 | rel 0.30] You pay $1,200 in rent")


# ---------- deterministic fallback composer ----------
def test_fallback_composes_from_activity_beliefs():
    out = L._compose_recall_fallback(BELIEF_CTX)
    check("fallback non-empty", bool(out), f"got {out!r}")
    check("fallback mentions hiking", "hiking" in out, f"got {out!r}")
    check("fallback strips scoring prefixes", "[0.76" not in out)
    check("fallback excludes non-activity facts (rent)",
          "rent" not in out, f"got {out!r}")
    check("fallback framed as recall ('From what you've shared')",
          out.startswith("From what you've shared with me:"))


def test_fallback_single_belief():
    ctx = "BELIEF GRAPH:\n  [0.8] I love watching movies"
    out = L._compose_recall_fallback(ctx)
    check("single-belief fallback well-formed",
          out == "From what you've shared with me: I love watching movies.",
          f"got {out!r}")


def test_fallback_empty_when_no_activity_beliefs():
    ctx = "BELIEF GRAPH:\n  [0.8] You make $5,000 a month\n  [0.7] You pay $1,200 in rent"
    out = L._compose_recall_fallback(ctx)
    check("no activity beliefs -> empty fallback", out == "", f"got {out!r}")


def test_fallback_empty_input():
    check("empty belief -> empty fallback", L._compose_recall_fallback("") == "")


# ---------- recall-mode guard in fast_core_node ----------
class _Stub:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
    def log_hardware(self, *a, **kw): pass
    async def execute_registry_inference(self, agent_id, payload):
        self.calls += 1
        return self.responses.pop(0)


def _state(user_input, belief=BELIEF_CTX):
    return {"user_input": user_input, "retrieved_memory": "",
            "belief_context": belief, "thread_id": "t"}


def test_recall_question_twice_gets_deterministic_answer():
    """Model returns a question both times -> fallback composed from beliefs.
    This is the exact eval-14 failure scenario."""
    stub = _Stub([
        "What are you currently into for fun?",   # mirror (echo-guard retries: ends ?, but
                                                    #  not scaffolded/echo -> NO retry there)
        # NOTE: echo guard won't retry a non-scaffolded paraphrase, so only
        # one inference happens; recall guard then applies the fallback.
    ])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L.fast_core_node(_state("What do I like to do for fun?")))
    text = out["fast_generation"]
    check("question-only recall response replaced by fallback",
          "hiking" in text, f"got {text!r}")
    check("fallback framing used",
          text.startswith("From what you've shared with me:"))


def test_recall_good_answer_passes_through():
    stub = _Stub(["You're a hiker — most Saturday mornings you're on a trail."])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L.fast_core_node(_state("What do I like to do for fun?")))
    check("good recall answer untouched",
          out["fast_generation"].startswith("You're a hiker"))
    check("single inference", stub.calls == 1)


def test_non_recall_question_response_allowed():
    """Casual share -> mentor's follow-up question is CORRECT behavior;
    the recall guard must not interfere."""
    stub = _Stub(["Nice — what did you cook?"])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L.fast_core_node(_state("I made dinner tonight.")))
    check("follow-up question passes for non-recall input",
          out["fast_generation"].endswith("?"))


def test_recall_without_beliefs_no_fallback():
    """Self-ref question but NO beliefs -> question back is legitimate
    (nothing to recall)."""
    stub = _Stub(["What do you enjoy doing for fun?"])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L.fast_core_node(
            _state("What do I like to do for fun?", belief="")))
    check("no beliefs -> question response stands",
          out["fast_generation"].endswith("?"))


def test_recall_payload_says_do_not_ask_back():
    captured = {}
    class _Cap:
        def log_hardware(self, *a, **kw): pass
        async def execute_registry_inference(self, agent_id, payload):
            captured["p"] = payload
            return "You hike."
    with patch.object(L, "runtime", _Cap()):
        asyncio.run(L.fast_core_node(_state("What do I like to do for fun?")))
    check("payload forbids asking back",
          "Do NOT ask them a question back" in captured["p"])


# ---------- few-shot example in fast_mentor ----------
def test_fast_mentor_has_recall_example():
    p = L.AgentFactoryRegistry().registry["fast_mentor"].system_prompt
    check("recall few-shot present",
          "What do I like to do for fun?" in p)
    check("recall example answers from knowledge",
          "You're a hiker" in p)
    check("never-ask-back rule attached to example",
          "Never ask them the same question back" in p)


# ---------- encoder gate fix ----------
def test_encoder_gate_lazy_loads():
    """get_belief_context_sync must attempt the lazy load, not skip when
    the module-global is still None."""
    import inspect
    src = inspect.getsource(L.EarlRuntime.get_belief_context_sync)
    check("old defeating guard removed",
          "if _SHARED_ST_MODEL is not None else None" not in src)
    check("direct lazy-load call present",
          "_get_shared_st_model()" in src)


# ---------- regression ----------
def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_fallback_composes_from_activity_beliefs,
        test_fallback_single_belief,
        test_fallback_empty_when_no_activity_beliefs,
        test_fallback_empty_input,
        test_recall_question_twice_gets_deterministic_answer,
        test_recall_good_answer_passes_through,
        test_non_recall_question_response_allowed,
        test_recall_without_beliefs_no_fallback,
        test_recall_payload_says_do_not_ask_back,
        test_fast_mentor_has_recall_example,
        test_encoder_gate_lazy_loads,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 35 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
