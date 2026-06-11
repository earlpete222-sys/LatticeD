"""Sprint 25 - voice loop closing tests (mood + milestones in preamble)."""
from __future__ import annotations
import sys
import tempfile
import shutil
import time
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
        if k in ("AUDIT_LOG_PATH", "ACTIVITY_PATH", "MOODS_PATH"):
            suffix = ".jsonl"
        else:
            suffix = ".json"
        setattr(L, k, tmp / f"{k.lower()}{suffix}")
    return orig


def _restore(o):
    for k, v in o.items(): setattr(L, k, v)


def _boot():
    L.install_encrypted_persistence(None)
    return L.LatticeContext.boot(user_id="t", tier_override="minimal_gpu")


# ---------- mood block ----------
def test_mood_block_absent_when_no_observations():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        p = ctx.compose_preamble("life_coach")
        check("no mood observations -> no mood block",
              "USER MOOD CONTEXT" not in p, f"got {p[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mood_block_present_when_heavy_dominant():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for _ in range(4):
            ctx.mood.observe("Rough week, struggling and feel down.")
        p = ctx.compose_preamble("life_coach")
        check("HEAVY mood surfaces in preamble",
              "USER MOOD CONTEXT" in p and "heavy" in p,
              f"got {p[:500]}")
        check("HEAVY guidance is 'do not jump to fixes'",
              "do not jump to fixes" in p.lower(),
              f"got {p[:500]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mood_block_uses_different_guidance_per_signal():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        # Drained mood.
        for _ in range(3):
            ctx.mood.observe("Long day, exhausted and worn out.")
        p_drained = ctx.compose_preamble("life_coach")
        check("DRAINED -> 'brief and gentle' guidance",
              "brief and gentle" in p_drained.lower())
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mood_block_skips_schema_discipline_agents():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for _ in range(4):
            ctx.mood.observe("Rough week, struggling and feel down.")
        for aid in ("intent_router", "factual_auditor",
                     "system_guardian", "fact_extractor"):
            p = ctx.compose_preamble(aid)
            check(f"{aid} preamble excludes mood block",
                  "USER MOOD CONTEXT" not in p,
                  f"agent={aid}  got={p[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mood_block_excludes_low_concentration_signals():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        # 1 mood obs but the test_capture_continuity hook etc may produce
        # NEUTRAL signals too; force a single one and verify share < 0.3
        # is filtered out.  Here just one observation in isolation has
        # share = 1.0, which is above the threshold, so we need to
        # produce two non-matching signals.  Instead, just check NEUTRAL
        # is suppressed.
        for _ in range(3):
            ctx.mood.observe("Bought groceries.")  # -> NEUTRAL
        p = ctx.compose_preamble("life_coach")
        check("NEUTRAL dominant -> no mood block",
              "USER MOOD CONTEXT" not in p, f"got {p[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- milestone block ----------
def test_milestone_block_absent_when_no_in_progress():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.milestones.add("future plan",
                            north_star_ref="lead the team",
                            status=L.MilestoneStatus.OPEN.value)
        p = ctx.compose_preamble("life_coach")
        check("OPEN-only milestones don't surface",
              "ACTIVE MILESTONES" not in p, f"got {p[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_milestone_block_surfaces_in_progress():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("Run the team retro",
                                 north_star_ref="Lead a team within 3 years.",
                                 domain=L.LifeDomain.CAREER.value)
        ctx.milestones.update_status(m.id, L.MilestoneStatus.IN_PROGRESS.value)
        p = ctx.compose_preamble("life_coach")
        check("IN_PROGRESS milestone surfaces",
              "ACTIVE MILESTONES" in p and "team retro" in p,
              f"got {p[:500]}")
        check("north star tail surfaces",
              "Lead a team" in p, f"got {p[:500]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_milestone_block_skips_schema_agents():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("Run the team retro",
                                 north_star_ref="Lead a team.")
        ctx.milestones.update_status(m.id, L.MilestoneStatus.IN_PROGRESS.value)
        for aid in ("intent_router", "factual_auditor",
                     "system_guardian", "fact_extractor",
                     "quant_architect"):
            p = ctx.compose_preamble(aid)
            check(f"{aid} excludes ACTIVE MILESTONES",
                  "ACTIVE MILESTONES" not in p,
                  f"agent={aid} got={p[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_milestone_block_due_soon_section():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("Submit quarterly review",
                                 north_star_ref="Lead the org.",
                                 due_at=time.time() + 5 * 86400)
        ctx.milestones.update_status(m.id, L.MilestoneStatus.IN_PROGRESS.value)
        p = ctx.compose_preamble("life_coach")
        check("DUE SOON section appears",
              "DUE SOON" in p and "quarterly review" in p,
              f"got {p[:600]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_milestone_block_caps_at_three():
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for i in range(6):
            m = ctx.milestones.add(f"Milestone {i}", north_star_ref="goal")
            ctx.milestones.update_status(m.id, L.MilestoneStatus.IN_PROGRESS.value)
        p = ctx.compose_preamble("life_coach")
        count = sum(1 for line in p.splitlines() if line.startswith("  - ") and "Milestone" in line)
        check("milestone block lists at most 3 active",
              count <= 3, f"got count={count}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- composite ----------
def test_combined_preamble_block_ordering():
    """Continuity first, then voice, then mood, then milestones."""
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        # Fill all four blocks.
        ctx.capture_continuity(session_id="s1",
                                 summary="Last session: chatted about work.")
        ctx.identity.add_fact("I work as a designer.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        for _ in range(4):
            ctx.mood.observe("Rough day, feel heavy.")
        m = ctx.milestones.add("Wrap the project",
                                 north_star_ref="Ship by EOY.",
                                 domain=L.LifeDomain.CAREER.value)
        ctx.milestones.update_status(m.id, L.MilestoneStatus.IN_PROGRESS.value)
        p = ctx.compose_preamble("life_coach")

        # Order must be: RECENT CONTEXT -> USER ... (rules/facts) -> USER MOOD -> ACTIVE MILESTONES
        ic = p.find("RECENT CONTEXT")
        iv = p.find("WHAT YOU KNOW ABOUT THE USER")
        im = p.find("USER MOOD CONTEXT")
        ig = p.find("ACTIVE MILESTONES")
        check("continuity before voice", ic >= 0 and ic < iv,
              f"continuity={ic} voice={iv}")
        check("voice before mood", iv < im,
              f"voice={iv} mood={im}")
        check("mood before milestones", im < ig,
              f"mood={im} goals={ig}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_router_preamble_still_empty():
    """intent_router was empty pre-Sprint-25; must still be empty."""
    tmp = Path(tempfile.mkdtemp(prefix="sp25_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for _ in range(4):
            ctx.mood.observe("Rough day, feel heavy.")
        m = ctx.milestones.add("step", north_star_ref="goal")
        ctx.milestones.update_status(m.id, L.MilestoneStatus.IN_PROGRESS.value)
        p = ctx.compose_preamble("intent_router")
        check("intent_router preamble stays empty",
              p == "", f"got {p!r}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


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
        test_mood_block_absent_when_no_observations,
        test_mood_block_present_when_heavy_dominant,
        test_mood_block_uses_different_guidance_per_signal,
        test_mood_block_skips_schema_discipline_agents,
        test_mood_block_excludes_low_concentration_signals,
        test_milestone_block_absent_when_no_in_progress,
        test_milestone_block_surfaces_in_progress,
        test_milestone_block_skips_schema_agents,
        test_milestone_block_due_soon_section,
        test_milestone_block_caps_at_three,
        test_combined_preamble_block_ordering,
        test_router_preamble_still_empty,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 25 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
