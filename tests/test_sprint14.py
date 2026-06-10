"""Sprint 14 - LatticeContext activation orchestrator. Standalone."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _redirect_paths(tmp: Path) -> dict:
    """Redirect every persistent path into tmp so tests don't touch real state.
    Returns the dict of (attr_name, original_value) for restoration."""
    redirects = {
        "IDENTITY_PATH":          tmp / "identity.json",
        "CURIOSITY_PATH":         tmp / "curiosity.json",
        "VOICE_PROFILES_PATH":    tmp / "voice.json",
        "CONTINUITY_PATH":        tmp / "continuity.json",
        "AUDIT_LOG_PATH":         tmp / "audit.jsonl",
        "BUSINESS_PATH":          tmp / "business.json",
        "PROMPT_EVOLUTION_PATH":  tmp / "prompt_evolution.json",
    }
    originals = {}
    for k, v in redirects.items():
        originals[k] = getattr(L, k)
        setattr(L, k, v)
    return originals


def _restore_paths(originals: dict) -> None:
    for k, v in originals.items():
        setattr(L, k, v)


def test_boot_returns_valid_context():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot(user_id="alice", tier_override="minimal_gpu")
        check("ctx.profile tier matches override",
              ctx.profile.tier == L.ModelTier.MINIMAL_GPU.value)
        check("ctx has 12 agents", len(ctx.factory.registry) == 12)
        check("ctx validation valid on MINIMAL_GPU", ctx.validation.valid)
        report = ctx.boot_report()
        check("boot_report carries user_id", report["user_id"] == "alice")
        check("boot_report.tier matches", report["tier"] == "minimal_gpu")
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_compose_preamble_router_empty():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot()
        ctx.identity.add_fact("I make $100k.")
        # intent_router has empty AGENT_SALIENCE -> preamble should be empty.
        p = ctx.compose_preamble("intent_router")
        check("intent_router preamble is empty", p == "", f"got {p!r}")
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_compose_preamble_includes_identity_for_life_coach():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot()
        ctx.identity.add_fact("My wife is a high school teacher.",
                              domain=L.LifeDomain.RELATIONSHIPS.value,
                              confidence=0.95)
        ctx.identity.add_north_star("Be a present partner.",
                                     domain=L.LifeDomain.RELATIONSHIPS.value,
                                     weight=1.5)
        p = ctx.compose_preamble("life_coach")
        check("life_coach preamble includes the fact",
              "teacher" in p, p[:200])
        check("life_coach preamble includes north star",
              "present partner" in p.lower(), p[:200])
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_compose_preamble_evolved_salience_shrinks_facts():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot()
        for i in range(20):
            ctx.identity.add_fact(f"Career fact {i}.",
                                   domain=L.LifeDomain.CAREER.value, confidence=0.9)
        # Negative feedback on long outputs -> brevity_pref drifts UP.
        for _ in range(10):
            ctx.voice.record_interaction(L.EngagementSignal(
                agent_id="life_coach", output_chars=800,
                user_explicit_negative=True,
            ))
        p_evolved = ctx.compose_preamble("life_coach")
        career_count = p_evolved.count("[career]")
        # Base max_facts for life_coach = 8; evolved should be smaller.
        check("evolved salience trims fact count under brevity pressure",
              career_count < 8, f"got {career_count}")
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_record_turn_updates_voice_and_perf_and_memory():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot()
        ctx.record_turn(
            agent_id="fast_mentor",
            output="That's nice to hear. What's coming next?",
            user_explicit_positive=True,
            domain=L.LifeDomain.CAREER.value,
            latency_ms=120.0,
        )
        check("voice profile created for fast_mentor",
              "fast_mentor" in ctx.voice.profiles)
        check("perf log captured one sample",
              len(ctx.perf.samples) == 1
              and ctx.perf.samples[0].node == "fast_mentor")
        check("memory store captured one record",
              len(ctx.memory.records) == 1)
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_capture_continuity_persists():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot()
        ctx.capture_continuity(
            session_id="s1", last_intent="PERSONAL",
            open_threads=["follow up on manager 1:1"],
            domains_touched=[L.LifeDomain.CAREER.value],
            mood_signal="focused",
            summary="Talked about a project handoff.",
        )
        check("continuity store has 1 token", len(ctx.continuity.tokens) == 1)
        ctx.save_all()
        # Reload context: should still see the token.
        ctx2 = L.LatticeContext.boot()
        check("continuity token persists across boot",
              len(ctx2.continuity.tokens) == 1
              and ctx2.continuity.tokens[0].summary.startswith("Talked"),
              f"got {[t.summary for t in ctx2.continuity.tokens]}")
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_save_all_persists_everything():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot(user_id="bob")
        ctx.identity.add_fact("I run a small consultancy.")
        ctx.identity.add_north_star("Reach $300k revenue.",
                                     domain=L.LifeDomain.BUSINESS.value, weight=1.5)
        ctx.identity.add_rule("Never share client data.", priority=300)
        ctx.business.register(L.BusinessProfile(business_id="consult",
                                                 display_name="Consultancy",
                                                 role="founder"),
                              set_active=True)
        ctx.voice.record_interaction(L.EngagementSignal(
            agent_id="fast_mentor", output_chars=120, user_explicit_positive=True,
        ))
        ctx.prompt_evo.seed("fast_mentor", "Be warm and direct.")
        ctx.save_all()

        ctx2 = L.LatticeContext.boot(user_id="bob")
        check("identity persisted across boot",
              any("consultancy" in f.text.lower() for f in ctx2.identity.doc.facts))
        check("business store persisted",
              ctx2.business.active_id == "consult")
        check("voice profile persisted",
              "fast_mentor" in ctx2.voice.profiles)
        check("prompt evolution persisted",
              "fast_mentor" in ctx2.prompt_evo.populations)
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_boot_report_shape():
    tmp = Path(tempfile.mkdtemp(prefix="sp14_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot()
        rep = ctx.boot_report()
        for key in ["user_id", "tier", "vram_gb", "agents", "validation",
                    "facts", "north_stars", "rules", "active_business",
                    "continuity_tokens", "voice_profiles"]:
            check(f"boot_report has key '{key}'", key in rep)
    finally:
        _restore_paths(orig)
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_boot_returns_valid_context,
        test_compose_preamble_router_empty,
        test_compose_preamble_includes_identity_for_life_coach,
        test_compose_preamble_evolved_salience_shrinks_facts,
        test_record_turn_updates_voice_and_perf_and_memory,
        test_capture_continuity_persists,
        test_save_all_persists_everything,
        test_boot_report_shape,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 14 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
