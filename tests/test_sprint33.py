"""Sprint 33 - meta-reply eval failure fixes."""
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


# ---------- broadened scaffold regex ----------
def test_scaffold_you_could_ask():
    out = L.clean_model_text('You could ask, "What do you enjoy doing for fun?"')
    check("'You could ask' stripped + unwrapped",
          out == "What do you enjoy doing for fun?", f"got {out!r}")


def test_scaffold_you_might_reply():
    out = L.clean_model_text('You might reply: "Sounds great, count me in."')
    check("'You might reply' stripped",
          out == "Sounds great, count me in.", f"got {out!r}")


def test_scaffold_try_asking():
    out = L.clean_model_text('Try asking: "How was your weekend?"')
    check("'Try asking' stripped",
          out == "How was your weekend?", f"got {out!r}")


def test_scaffold_heres_a_question():
    out = L.clean_model_text("Here's a question: What matters most to you?")
    check("'Here's a question' stripped",
          out == "What matters most to you?", f"got {out!r}")


def test_scaffold_originals_still_work():
    out1 = L.clean_model_text('Great! How about: "I am glad to hear from you."')
    check("original 'How about' still stripped",
          out1 == "I am glad to hear from you.", f"got {out1!r}")
    out2 = L.clean_model_text("Plain answer, no scaffold.")
    check("non-scaffolded text untouched",
          out2 == "Plain answer, no scaffold.")


def test_scaffold_does_not_eat_normal_sentences():
    # 'you can say' mid-sentence (not at start) must NOT be stripped.
    text = "When negotiating, you can say no without explanation."
    out = L.clean_model_text(text)
    check("mid-sentence 'you can say' untouched", out == text, f"got {out!r}")


# ---------- echo guard: scaffolded-question retry ----------
class _StubRuntime:
    """Stands in for the module-level runtime; returns scripted responses."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def execute_registry_inference(self, agent_id, payload):
        self.calls.append(payload)
        return self.responses.pop(0)


def test_guard_retries_on_scaffolded_question():
    stub = _StubRuntime([
        'You could ask, "What do you enjoy doing for fun?"',     # meta -> retry
        "You love hiking — you head out almost every Saturday morning.",
    ])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "fast_mentor", "WHAT I KNOW ABOUT THE USER:\n- hikes Saturdays",
            "What do I like to do for fun?"))
    check("scaffolded question triggered retry", len(stub.calls) == 2,
          f"calls={len(stub.calls)}")
    check("retry nudge mentions not suggesting a question",
          "do not suggest a question" in stub.calls[1])
    check("final output is the real answer",
          "hiking" in out, f"got {out!r}")


def test_guard_no_retry_on_good_answer():
    stub = _StubRuntime([
        "You love hiking — almost every Saturday morning, in fact.",
    ])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "fast_mentor", "payload", "What do I like to do for fun?"))
    check("good answer -> no retry", len(stub.calls) == 1)
    check("output passthrough", "hiking" in out)


def test_guard_no_retry_on_legit_followup_question():
    """A NON-scaffolded question (the mentor's normal follow-up style)
    must NOT trigger the meta retry."""
    stub = _StubRuntime([
        "Nice — what part of the day was the best?",
    ])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "fast_mentor", "payload", "Spent the day at the park."))
    check("legit follow-up question -> no retry",
          len(stub.calls) == 1, f"calls={len(stub.calls)}")
    check("question passthrough", out.endswith("?"))


def test_guard_still_retries_on_echo():
    stub = _StubRuntime([
        "What do I like to do for fun?",        # echo -> retry
        "You're a hiker — Saturdays on the trail.",
    ])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "fast_mentor", "payload", "What do I like to do for fun?"))
    check("verbatim echo still triggers retry", len(stub.calls) == 2)
    check("echo retry produced answer", "hiker" in out)


def test_guard_scaffolded_statement_not_retried():
    """Scaffold + statement (not question) unwraps to a usable reply --
    no retry needed."""
    stub = _StubRuntime([
        'Sure! You could say: "I had a great day, thanks for asking."',
    ])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "fast_mentor", "payload", "How was your day?"))
    check("scaffolded STATEMENT unwraps without retry",
          len(stub.calls) == 1, f"calls={len(stub.calls)}")
    check("unwrapped statement returned",
          out == "I had a great day, thanks for asking.", f"got {out!r}")


# ---------- self-referential payload emphasis ----------
def test_fast_core_payload_emphasis():
    """fast_core_node adds the IMPORTANT pointer when belief context is
    present AND the query is self-referential."""
    captured = {}

    class _Capture:
        def log_hardware(self, *a, **kw): pass
        async def execute_registry_inference(self, agent_id, payload):
            captured["payload"] = payload
            return "You love hiking."

    state = {
        "user_input": "What do I like to do for fun?",
        "retrieved_memory": "",
        "belief_context": "- goes hiking almost every Saturday morning",
        "thread_id": "t",
    }
    with patch.object(L, "runtime", _Capture()):
        out = asyncio.run(L.fast_core_node(state))
    p = captured["payload"]
    check("payload includes belief section",
          "WHAT I KNOW ABOUT THE USER" in p)
    check("payload includes IMPORTANT self-reference pointer",
          "asking about THEMSELVES" in p, f"payload={p[:400]!r}")
    check("node returns generation",
          out["fast_generation"] == "You love hiking.")


def test_fast_core_no_emphasis_without_self_reference():
    captured = {}

    class _Capture:
        def log_hardware(self, *a, **kw): pass
        async def execute_registry_inference(self, agent_id, payload):
            captured["payload"] = payload
            return "Nice."

    state = {
        "user_input": "Tell me a fun fact about space.",
        "retrieved_memory": "",
        "belief_context": "- goes hiking almost every Saturday morning",
        "thread_id": "t",
    }
    with patch.object(L, "runtime", _Capture()):
        asyncio.run(L.fast_core_node(state))
    check("non-self-referential query -> no IMPORTANT pointer",
          "asking about THEMSELVES" not in captured["payload"],
          f"payload={captured['payload'][:300]!r}")


def test_fast_core_no_emphasis_without_beliefs():
    captured = {}

    class _Capture:
        def log_hardware(self, *a, **kw): pass
        async def execute_registry_inference(self, agent_id, payload):
            captured["payload"] = payload
            return "Hmm."

    state = {
        "user_input": "What do I like to do for fun?",
        "retrieved_memory": "",
        "belief_context": "",
        "thread_id": "t",
    }
    with patch.object(L, "runtime", _Capture()):
        asyncio.run(L.fast_core_node(state))
    check("no beliefs -> no pointer (nothing to point at)",
          "asking about THEMSELVES" not in captured["payload"])


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
        test_scaffold_you_could_ask,
        test_scaffold_you_might_reply,
        test_scaffold_try_asking,
        test_scaffold_heres_a_question,
        test_scaffold_originals_still_work,
        test_scaffold_does_not_eat_normal_sentences,
        test_guard_retries_on_scaffolded_question,
        test_guard_no_retry_on_good_answer,
        test_guard_no_retry_on_legit_followup_question,
        test_guard_still_retries_on_echo,
        test_guard_scaffolded_statement_not_retried,
        test_fast_core_payload_emphasis,
        test_fast_core_no_emphasis_without_self_reference,
        test_fast_core_no_emphasis_without_beliefs,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 33 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
