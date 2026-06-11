"""Sprint 28 - executive_arbiter voice rewrite (Covey Habit 2).

Pins down the Habit 2 anchors so a future refactor cannot silently
strip them out.
"""
from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _arbiter_prompt() -> str:
    return L.AgentFactoryRegistry().registry["executive_arbiter"].system_prompt


def test_arbiter_carries_begin_with_the_end_in_mind():
    p = _arbiter_prompt().lower()
    check("'begin with the end in mind' present",
          "begin with the end in mind" in p,
          f"prompt[:200]={p[:200]!r}")


def test_arbiter_carries_all_things_created_twice():
    p = _arbiter_prompt().lower()
    check("'created twice' present (mental then physical)",
          "created twice" in p)
    check("'mental creation BEFORE...physical' rule present",
          "mental creation before" in p or "mental creation before composing" in p,
          f"extract={p[100:400]!r}")


def test_arbiter_end_state_loop_steps():
    p = _arbiter_prompt().lower()
    check("'name the destination' step present",
          "name the destination" in p)
    check("'after reading this, the user is holding' sentence template",
          "the user is holding" in p)
    check("'one takeaway' step present",
          "one takeaway" in p)
    check("'compose backward' step present",
          "compose backward" in p)


def test_arbiter_forbids_filler_openers():
    p = _arbiter_prompt().lower()
    check("'restate the user' forbidden",
          "restate the user" in p)
    check("'no filler openers' rule present",
          "no filler openers" in p)
    check("'great question' is explicitly cited as filler",
          "great question" in p)


def test_arbiter_forbids_hedge_closers():
    p = _arbiter_prompt().lower()
    check("'i hope this helps' explicitly forbidden",
          "i hope this helps" in p)
    check("'let me know' closer cited as wrong",
          "let me know" in p)


def test_arbiter_anchors_to_approved_strategy():
    p = _arbiter_prompt().lower()
    check("'approved technical strategy' anchor named",
          "approved technical strategy" in p)
    check("'do not introduce new claims' rule present",
          "do not introduce new claims" in p)


def test_arbiter_distill_not_recite_rule():
    p = _arbiter_prompt().lower()
    check("'distill, do not recite' rule present",
          "distill, do not recite" in p
          or "distill" in p and "not recite" in p)
    check("photocopier metaphor present",
          "photocopier" in p)


def test_arbiter_voice_anchors_present():
    p = _arbiter_prompt().lower()
    check("'each paragraph earns its place' anchor",
          "earns its place" in p)
    check("'second person' anchor",
          "second person" in p)
    check("'active voice' anchor",
          "active voice" in p)


def test_arbiter_context_integration_uses_milestones_in_lede():
    p = _arbiter_prompt().lower()
    check("'active milestone... in the lede' integration rule",
          "active milestone" in p and "lede" in p,
          f"extract={p[-600:]!r}")
    check("'do not quote the preamble verbatim' rule",
          "do not quote the preamble verbatim" in p)


def test_arbiter_prompt_length_reasonable():
    n = len(_arbiter_prompt())
    check("arbiter prompt is between 800 and 3500 chars",
          800 <= n <= 3500, f"got {n} chars")


def test_arbiter_agentspec_unchanged_otherwise():
    spec = L.AgentFactoryRegistry().registry["executive_arbiter"]
    check("model_name still MODEL_SYNTHESIS",
          spec.model_name == L.MODEL_SYNTHESIS)
    check("temperature still 0.05", spec.temperature == 0.05)
    check("max_tokens still 800", spec.max_tokens == 800)
    check("INSTRUCTION_FOLLOWING still required STRONG",
          spec.capabilities_required.get(L.Capability.INSTRUCTION_FOLLOWING.value)
          == L.CapabilityLevel.STRONG.value)
    check("MINIMAL_GPU pool still qwen2.5-coder:1.5b",
          spec.model_pool_per_tier[L.ModelTier.MINIMAL_GPU.value]
          == [L.MODEL_SYNTHESIS])


def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_arbiter_carries_begin_with_the_end_in_mind,
        test_arbiter_carries_all_things_created_twice,
        test_arbiter_end_state_loop_steps,
        test_arbiter_forbids_filler_openers,
        test_arbiter_forbids_hedge_closers,
        test_arbiter_anchors_to_approved_strategy,
        test_arbiter_distill_not_recite_rule,
        test_arbiter_voice_anchors_present,
        test_arbiter_context_integration_uses_milestones_in_lede,
        test_arbiter_prompt_length_reasonable,
        test_arbiter_agentspec_unchanged_otherwise,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 28 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
