"""Sprint 27 - life_coach voice rewrite (Covey Habit 5).

Tests that the new persona is actually anchored in 'seek first to
understand' discipline -- not a list of buzzwords.  Refactors of this
prompt that quietly remove the Habit 5 anchors will fail these.
"""
from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _life_coach_prompt() -> str:
    return L.AgentFactoryRegistry().registry["life_coach"].system_prompt


def test_life_coach_carries_diagnose_before_prescribe():
    p = _life_coach_prompt().lower()
    check("'diagnose before prescribe' present",
          "diagnose before prescribe" in p,
          f"prompt[:200]={p[:200]!r}")


def test_life_coach_carries_reflection_loop_steps():
    p = _life_coach_prompt().lower()
    check("'reflect' step named",        "reflect" in p)
    check("'acknowledge' step named",    "acknowledge" in p)
    check("'one clarifying question' rule present",
          "one clarifying question" in p)
    check("'stop. let the question land.' rule present",
          "stop" in p and "let the question land" in p)


def test_life_coach_forbids_jumping_to_advice():
    p = _life_coach_prompt().lower()
    check("'jump to advice' explicitly forbidden", "jump to advice" in p)
    check("phrase 'prescription without diagnosis' present",
          "prescription without diagnosis" in p)


def test_life_coach_warns_against_pivot_to_own_experience():
    p = _life_coach_prompt().lower()
    check("self-pivot failure mode named",
          "pivot to your own experience" in p
          or "that happened to me too" in p)


def test_life_coach_advice_gate_present():
    """Advice only when the user explicitly asks OR after reflection
    lands AND the user signals readiness."""
    p = _life_coach_prompt().lower()
    check("'when advice is appropriate' section present",
          "when advice is appropriate" in p)
    check("explicit-ask gate named ('what would you do?' / 'any thoughts?')",
          "'what would you do?'" in _life_coach_prompt()
          or "'any thoughts?'" in _life_coach_prompt(),
          f"prompt extract={_life_coach_prompt()[400:800]!r}")


def test_life_coach_voice_clean_reflection_over_hedging():
    p = _life_coach_prompt().lower()
    check("clean reflection prefers 'it sounds like'",
          "it sounds like" in p)
    check("hedged form 'maybe you're feeling' is explicitly cited as worse",
          "maybe you're feeling" in p)


def test_life_coach_context_integration_rule_present():
    p = _life_coach_prompt().lower()
    check("'do not quote them back' (re facts/north stars) present",
          "do not quote them back" in p)
    check("preamble integration is named",
          "preamble" in p and "listening for" in p)


def test_life_coach_prompt_length_reasonable():
    n = len(_life_coach_prompt())
    check("life_coach prompt is between 400 and 3000 chars",
          400 <= n <= 3000, f"got {n} chars")


def test_life_coach_agentspec_unchanged_otherwise():
    """The rewrite must not silently change model_name, temperature,
    capability declarations, or model_pool_per_tier."""
    spec = L.AgentFactoryRegistry().registry["life_coach"]
    check("model_name still MODEL_REASONING",
          spec.model_name == L.MODEL_REASONING)
    check("temperature still 0.55", spec.temperature == 0.55)
    check("max_tokens still 700", spec.max_tokens == 700)
    check("EMOTIONAL_INTELLIGENCE still required STRONG",
          spec.capabilities_required.get(L.Capability.EMOTIONAL_INTELLIGENCE.value)
          == L.CapabilityLevel.STRONG.value)
    check("BRIEF_RESPONSES still in capabilities_avoid",
          L.Capability.BRIEF_RESPONSES.value in spec.capabilities_avoid)
    check("MINIMAL_GPU pool still deepseek-r1:1.5b",
          spec.model_pool_per_tier[L.ModelTier.MINIMAL_GPU.value]
          == [L.MODEL_REASONING])


def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_life_coach_carries_diagnose_before_prescribe,
        test_life_coach_carries_reflection_loop_steps,
        test_life_coach_forbids_jumping_to_advice,
        test_life_coach_warns_against_pivot_to_own_experience,
        test_life_coach_advice_gate_present,
        test_life_coach_voice_clean_reflection_over_hedging,
        test_life_coach_context_integration_rule_present,
        test_life_coach_prompt_length_reasonable,
        test_life_coach_agentspec_unchanged_otherwise,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 27 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
