"""Sprint 36 - prompt-leakage guard tests."""
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

LEAKED = ("Certainly! Here's a structured analysis of your query:\n"
          "Reflection on LatticeD's Conversation: The dialogue follows an "
          "empathic listening framework... Context Blueprint: the user wants "
          "to reflect before family time.")

GOOD = "It sounds like family time really fills your tank. What did you all get up to?"


class _Stub:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
    def log_hardware(self, *a, **kw): pass
    async def execute_registry_inference(self, agent_id, payload):
        self.calls += 1
        return self.responses.pop(0)


def test_leak_triggers_retry_then_good():
    stub = _Stub([LEAKED, GOOD])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "life_coach", "payload", "I love hanging out with family"))
    check("leak triggered retry", stub.calls == 2, f"calls={stub.calls}")
    check("good retry passes through", out == GOOD, f"got {out!r}")


def test_leak_twice_degrades_to_minimal_reply():
    stub = _Stub([LEAKED, LEAKED])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "life_coach", "payload", "I love hanging out with family"))
    check("double leak -> minimal honest reply",
          out == "I hear you. Tell me a bit more about that?", f"got {out!r}")
    check("machinery never reaches user",
          "Context Blueprint" not in out and "framework" not in out)


def test_good_response_untouched():
    stub = _Stub([GOOD])
    with patch.object(L, "runtime", stub):
        out = asyncio.run(L._infer_with_echo_guard(
            "life_coach", "payload", "I love hanging out with family"))
    check("clean response -> single inference", stub.calls == 1)
    check("clean response passthrough", out == GOOD)


def test_leak_markers_individually_detected():
    for marker_text in [
        "Let me explain the Context Blueprint you provided.",
        "The reflection loop has four steps.",
        "Per my system prompt, I should reflect first.",
        "My operating discipline is empathic listening.",
    ]:
        stub = _Stub([marker_text, GOOD])
        with patch.object(L, "runtime", stub):
            out = asyncio.run(L._infer_with_echo_guard(
                "life_coach", "payload", "hello"))
        check(f"marker caught: '{marker_text[:35]}...'",
              stub.calls == 2 and out == GOOD,
              f"calls={stub.calls} out={out[:50]!r}")


def test_normal_words_not_false_positives():
    """'discipline' or 'blueprint' alone in normal conversation must NOT
    trigger the guard."""
    for ok_text in [
        "Building discipline around savings takes time — be patient with yourself.",
        "Sounds like the blueprint for your week is already taking shape.",
        "That kind of systems thinking will serve you well.",
    ]:
        stub = _Stub([ok_text])
        with patch.object(L, "runtime", stub):
            out = asyncio.run(L._infer_with_echo_guard(
                "life_coach", "payload", "I'm working on my budget"))
        check(f"no false positive: '{ok_text[:35]}...'",
              stub.calls == 1 and out == ok_text,
              f"calls={stub.calls}")


def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_leak_triggers_retry_then_good,
        test_leak_twice_degrades_to_minimal_reply,
        test_good_response_untouched,
        test_leak_markers_individually_detected,
        test_normal_words_not_false_positives,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 36 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
