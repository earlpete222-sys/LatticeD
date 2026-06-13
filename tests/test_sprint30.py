"""Sprint 30 - quant_architect Quadrant II framing (Covey Habit 3)."""
from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _prompts():
    reg = L.AgentFactoryRegistry().registry
    return (reg["quant_architect"].system_prompt,
            reg["quant_architect_explore"].system_prompt)


def test_both_architects_carry_first_things_first():
    pc, pe = _prompts()
    for label, p in [("conservative", pc), ("explore", pe)]:
        lo = p.lower()
        check(f"{label}: 'put first things first' present",
              "put first things first" in lo)
        check(f"{label}: 'important but never urgent' framing present",
              "important but never urgent" in lo)
        check(f"{label}: 'first thing paid, not the leftover' rule present",
              "first thing paid, not the leftover" in lo)
        check(f"{label}: 'protect the important from the urgent' present",
              "protect the important from the urgent" in lo)


def test_anti_role_parrot_rule_present():
    """Sprint 38: both architects must forbid role-description openers
    (live probe parroted 'As a confident financial strategist...')."""
    pc, pe = _prompts()
    for label, p in [("conservative", pc), ("explore", pe)]:
        check(f"{label}: forbids role-describing openers",
              "NEVER open by describing your role" in p, f"{label} missing rule")
        check(f"{label}: names the parroted opener as forbidden",
              "As a confident" in p and "Forbidden openers" in p)


def test_contamination_guards_still_present():
    pc, pe = _prompts()
    for label, p in [("conservative", pc), ("explore", pe)]:
        check(f"{label}: 'Never mention financial products' guard intact",
              "Never mention financial products" in p)
        check(f"{label}: STAY ON TOPIC rule intact",
              "STAY ON TOPIC" in p)
        check(f"{label}: 529 example still absent",
              "529 plan for maximum" not in p
              and "three-month emergency fund before any college" not in p)


def test_templates_and_voice_intact():
    pc, pe = _prompts()
    for label, p in [("conservative", pc), ("explore", pe)]:
        check(f"{label}: WRITE LIKE THIS templates intact",
              "WRITE LIKE THIS" in p)
        check(f"{label}: TABLE BELOW HANDLES ALL NUMBERS rule intact",
              "TABLE BELOW HANDLES ALL NUMBERS" in p)
        check(f"{label}: closing write-the-paragraph instruction intact",
              "Write the paragraph (2-3 complete sentences)" in p)


def test_agentspec_fields_unchanged():
    reg = L.AgentFactoryRegistry().registry
    c = reg["quant_architect"]; e = reg["quant_architect_explore"]
    check("conservative temp still 0.1", c.temperature == 0.1)
    check("explore temp still 0.3", e.temperature == 0.3)
    check("both max_tokens still 500",
          c.max_tokens == 500 and e.max_tokens == 500)
    check("adversarial pairing intact",
          c.adversarial_pair == "quant_architect_explore"
          and e.adversarial_pair == "quant_architect")
    check("both still PAIR_AGREEMENT consensus",
          c.consensus_requirement == L.ConsensusRequirement.PAIR_AGREEMENT.value
          and e.consensus_requirement == L.ConsensusRequirement.PAIR_AGREEMENT.value)


def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_both_architects_carry_first_things_first,
        test_anti_role_parrot_rule_present,
        test_contamination_guards_still_present,
        test_templates_and_voice_intact,
        test_agentspec_fields_unchanged,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 30 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
