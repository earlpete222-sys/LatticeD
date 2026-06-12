"""Sprint 31 - fast_mentor agency framing (Covey Habit 1)."""
from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _prompt() -> str:
    return L.AgentFactoryRegistry().registry["fast_mentor"].system_prompt


def test_agency_block_present():
    p = _prompt().lower()
    check("'agency over advice' section present", "agency over advice" in p)
    check("'freedom to choose' (Frankl/Habit 1 anchor) present",
          "freedom to choose" in p)
    check("choice-shaped question examples present",
          "what do you want to choose here" in p)
    check("'in your control' question present",
          "in your control" in p)
    check("victim-framing forbidden",
          "never frame them as a victim" in p)


def test_existing_behaviors_intact():
    p = _prompt()
    check("curious-companion identity intact",
          "thoughtful, curious personal companion" in p)
    check("follow-up question default intact",
          "ASK A FOLLOW-UP QUESTION" in p)
    check("FORBIDDEN PATTERNS section intact",
          "FORBIDDEN PATTERNS" in p)
    check("Sprint 29 no-meta-reply rule intact",
          "give the reply itself" in p)
    check("no-unsolicited-advice rule intact",
          "Do not give unsolicited advice" in p)
    check("closing stop instruction intact",
          "Stop after the question mark" in p)


def test_agency_gated_on_user_asking():
    """Habit 1 framing must NOT license unsolicited advice -- it only
    shapes responses when the user DOES ask."""
    p = _prompt()
    check("agency guidance gated on 'DO ask what to do'",
          "DO ask what to do" in p, f"extract={p[-700:]!r}")


def test_agentspec_fields_unchanged():
    spec = L.AgentFactoryRegistry().registry["fast_mentor"]
    check("model still MODEL_REASONING", spec.model_name == L.MODEL_REASONING)
    check("temp still 0.6", spec.temperature == 0.6)
    check("max_tokens still 400", spec.max_tokens == 400)


def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_agency_block_present,
        test_existing_behaviors_intact,
        test_agency_gated_on_user_asking,
        test_agentspec_fields_unchanged,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 31 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
