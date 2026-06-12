"""Sprint 32 - universal-pattern core primitives."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _redirect_paths(tmp: Path) -> dict:
    keys = ["IDENTITY_PATH", "CURIOSITY_PATH", "VOICE_PROFILES_PATH",
            "CONTINUITY_PATH", "AUDIT_LOG_PATH", "BUSINESS_PATH",
            "PROMPT_EVOLUTION_PATH", "SNAPSHOTS_PATH", "ACTIVITY_PATH",
            "MOODS_PATH", "MILESTONES_PATH"]
    orig = {k: getattr(L, k) for k in keys}
    for k in keys:
        suffix = ".jsonl" if k in ("AUDIT_LOG_PATH", "ACTIVITY_PATH", "MOODS_PATH") else ".json"
        setattr(L, k, tmp / f"{k.lower()}{suffix}")
    return orig


def _restore(o):
    for k, v in o.items(): setattr(L, k, v)


# ---------- control locus ----------
def test_locus_within():
    locus, _ = L.classify_control_locus("I can start saving more each week. It's my decision.")
    check("agency language -> WITHIN", locus == L.ControlLocus.WITHIN.value, f"got {locus}")


def test_locus_outside():
    locus, _ = L.classify_control_locus("The market crashed and there's nothing I can do about it.")
    check("market language -> OUTSIDE", locus == L.ControlLocus.OUTSIDE.value, f"got {locus}")


def test_locus_mixed():
    locus, counts = L.classify_control_locus(
        "My boss decided to cancel the project, but I can choose how I respond and what I learn.")
    check("both signals -> MIXED", locus == L.ControlLocus.MIXED.value,
          f"got {locus} counts={counts}")


def test_locus_unclear():
    locus, _ = L.classify_control_locus("The sky is blue.")
    check("no signal -> UNCLEAR", locus == L.ControlLocus.UNCLEAR.value)


def test_locus_empty():
    locus, counts = L.classify_control_locus("")
    check("empty -> UNCLEAR with empty counts",
          locus == L.ControlLocus.UNCLEAR.value and counts == {})


def test_locus_layoff_is_outside():
    locus, _ = L.classify_control_locus("I got laid off last month.")
    check("layoff -> OUTSIDE", locus == L.ControlLocus.OUTSIDE.value, f"got {locus}")


# ---------- time horizon ----------
def test_horizon_immediate():
    h = L.infer_time_horizon("I need to fix this today.")
    check("'today' -> IMMEDIATE", h == L.TimeHorizon.IMMEDIATE.value, f"got {h}")


def test_horizon_short():
    h = L.infer_time_horizon("I want this done by the end of the month.")
    check("'end of month' -> SHORT", h == L.TimeHorizon.SHORT.value, f"got {h}")


def test_horizon_medium():
    h = L.infer_time_horizon("We plan to expand within two years.")
    check("'within two years' -> MEDIUM", h == L.TimeHorizon.MEDIUM.value, f"got {h}")


def test_horizon_long():
    h = L.infer_time_horizon("Saving for retirement is the priority.")
    check("'retirement' -> LONG", h == L.TimeHorizon.LONG.value, f"got {h}")


def test_horizon_longest_wins():
    h = L.infer_time_horizon(
        "I'll start this week, but the real goal is retirement security.")
    check("mixed horizons -> LONGEST wins", h == L.TimeHorizon.LONG.value, f"got {h}")


def test_horizon_unstated():
    h = L.infer_time_horizon("I like coffee.")
    check("no time signal -> UNSTATED", h == L.TimeHorizon.UNSTATED.value)


# ---------- consensus confidence ----------
def test_confidence_unanimous():
    conf, n = L.consensus_confidence(["yes", "yes", "Yes"])
    check("unanimous (case-insensitive) -> 1.0, 1 cluster",
          conf == 1.0 and n == 1, f"got {conf}, {n}")


def test_confidence_majority():
    conf, n = L.consensus_confidence(["a", "a", "b"])
    check("2-of-3 -> 0.667, 2 clusters",
          abs(conf - 2/3) < 1e-6 and n == 2, f"got {conf}, {n}")


def test_confidence_total_disagreement():
    conf, n = L.consensus_confidence(["a", "b", "c"])
    check("3-way split -> 1/3, 3 clusters",
          abs(conf - 1/3) < 1e-6 and n == 3)


def test_confidence_empty():
    conf, n = L.consensus_confidence([])
    check("empty -> 0.0, 0", conf == 0.0 and n == 0)


def test_margin_of_safety_preface_tiers():
    check("high confidence -> no hedge", L.margin_of_safety_preface(1.0) == "")
    p66 = L.margin_of_safety_preface(0.7)
    check("0.7 -> 'substantially agree'", "substantially agree" in p66)
    p5 = L.margin_of_safety_preface(0.55)
    check("0.55 -> 'provisional' language", "provisional" in p5)
    p3 = L.margin_of_safety_preface(0.34)
    check("0.34 -> LOW confidence warning", "LOW" in p3)


# ---------- decision-agent mood discipline ----------
def test_decision_agents_get_discipline_suffix():
    tmp = Path(tempfile.mkdtemp(prefix="sp32_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="minimal_gpu")
        for _ in range(4):
            ctx.mood.observe("Rough week, struggling and feel down.")
        p_arch = ctx.compose_preamble("quant_architect")
        check("architect mood block includes DECISION DISCIPLINE",
              "DECISION DISCIPLINE" in p_arch, f"got {p_arch[:400]}")
        check("'math does not change with feelings' present",
              "math does not change with feelings" in p_arch.lower()
              or "math does not change" in p_arch)
        p_coach = ctx.compose_preamble("life_coach")
        check("life_coach mood block does NOT carry decision suffix",
              "DECISION DISCIPLINE" not in p_coach, f"got {p_coach[:400]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_research_synthesizer_in_decision_agents():
    check("research_synthesizer registered as decision agent",
          "research_synthesizer" in L.LatticeContext._DECISION_AGENTS)
    check("both architects registered as decision agents",
          "quant_architect" in L.LatticeContext._DECISION_AGENTS
          and "quant_architect_explore" in L.LatticeContext._DECISION_AGENTS)
    check("coaches NOT in decision agents",
          "life_coach" not in L.LatticeContext._DECISION_AGENTS
          and "fast_mentor" not in L.LatticeContext._DECISION_AGENTS)


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
        test_locus_within,
        test_locus_outside,
        test_locus_mixed,
        test_locus_unclear,
        test_locus_empty,
        test_locus_layoff_is_outside,
        test_horizon_immediate,
        test_horizon_short,
        test_horizon_medium,
        test_horizon_long,
        test_horizon_longest_wins,
        test_horizon_unstated,
        test_confidence_unanimous,
        test_confidence_majority,
        test_confidence_total_disagreement,
        test_confidence_empty,
        test_margin_of_safety_preface_tiers,
        test_decision_agents_get_discipline_suffix,
        test_research_synthesizer_in_decision_agents,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 32 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
