"""Sprint 4 - Voice Evolution Engine tests. Standalone."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp():
    t = Path(tempfile.mkdtemp(prefix="sprint4_"))
    return L.VoiceEvolutionEngine(t/"voice.json"), t


def test_neutral_profile_for_new_agent():
    eng, t = _tmp()
    try:
        p = eng.profile_for("fast_mentor")
        check("new profile brevity=1.0", p.brevity_pref == 1.0)
        check("new profile warmth=1.0", p.warmth_pref == 1.0)
        check("new profile curiosity=1.0", p.curiosity_mult == 1.0)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_positive_signal_on_long_output_drops_brevity_pref():
    eng, t = _tmp()
    try:
        for _ in range(5):
            eng.record_interaction(L.EngagementSignal(
                agent_id="life_coach", output_chars=800,
                user_explicit_positive=True,
            ))
        p = eng.profile_for("life_coach")
        check("brevity pref drops below 1.0 after positive long-output signals",
              p.brevity_pref < 1.0, f"got {p.brevity_pref}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_negative_signal_on_long_output_raises_brevity_pref():
    eng, t = _tmp()
    try:
        for _ in range(5):
            eng.record_interaction(L.EngagementSignal(
                agent_id="fast_mentor", output_chars=600,
                user_explicit_negative=True,
            ))
        p = eng.profile_for("fast_mentor")
        check("brevity pref rises above 1.0 after negative long-output signals",
              p.brevity_pref > 1.0, f"got {p.brevity_pref}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_drift_bounded():
    eng, t = _tmp()
    try:
        for _ in range(500):
            eng.record_interaction(L.EngagementSignal(
                agent_id="fast_mentor", output_chars=900,
                user_explicit_negative=True,
            ))
        p = eng.profile_for("fast_mentor")
        check("drift bounded above by VOICE_DRIFT_MAX",
              p.brevity_pref <= L.VOICE_DRIFT_MAX + 1e-9, f"got {p.brevity_pref}")
        for _ in range(500):
            eng.record_interaction(L.EngagementSignal(
                agent_id="fast_mentor", output_chars=900,
                user_explicit_positive=True,
            ))
        p = eng.profile_for("fast_mentor")
        check("drift bounded below by VOICE_DRIFT_MIN",
              p.brevity_pref >= L.VOICE_DRIFT_MIN - 1e-9, f"got {p.brevity_pref}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_answered_curiosity_bumps_domain_multiplier():
    eng, t = _tmp()
    try:
        for _ in range(3):
            eng.record_interaction(L.EngagementSignal(
                agent_id="fast_mentor", output_chars=200,
                curiosity_question_answered=True,
                domain=L.LifeDomain.FINANCIAL.value,
            ))
        p = eng.profile_for("fast_mentor")
        check("financial domain curiosity multiplier > 1.0",
              p.domain_curiosity.get(L.LifeDomain.FINANCIAL.value, 1.0) > 1.0,
              f"got {p.domain_curiosity}")
        check("global curiosity_mult > 1.0", p.curiosity_mult > 1.0, f"got {p.curiosity_mult}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_unanswered_curiosity_drops_domain_multiplier():
    eng, t = _tmp()
    try:
        for _ in range(3):
            eng.record_interaction(L.EngagementSignal(
                agent_id="fast_mentor", output_chars=200,
                curiosity_question_answered=False,
                domain=L.LifeDomain.HEALTH.value,
            ))
        p = eng.profile_for("fast_mentor")
        check("health domain curiosity multiplier < 1.0",
              p.domain_curiosity.get(L.LifeDomain.HEALTH.value, 1.0) < 1.0,
              f"got {p.domain_curiosity}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_evolved_salience_shrinks_with_brevity():
    eng, t = _tmp()
    try:
        for _ in range(8):
            eng.record_interaction(L.EngagementSignal(
                agent_id="life_coach", output_chars=900,
                user_explicit_negative=True,
            ))
        base = L.AGENT_SALIENCE["life_coach"]
        out = eng.evolved_salience("life_coach", base)
        check("evolved salience reduces max_facts when brevity_pref high",
              out["max_facts"] < base["max_facts"],
              f"base={base['max_facts']} evolved={out['max_facts']}")
        check("evolved salience exposes brevity_pref tag",
              out["_voice_brevity_pref"] > 1.0)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_should_ask_curiosity_threshold():
    eng, t = _tmp()
    try:
        # Drift curiosity well below 0.7.
        for _ in range(20):
            eng.record_interaction(L.EngagementSignal(
                agent_id="fast_mentor", output_chars=200,
                curiosity_question_answered=False,
                domain=L.LifeDomain.RELATIONSHIPS.value,
            ))
        p = eng.profile_for("fast_mentor")
        ask = eng.should_ask_curiosity("fast_mentor", L.LifeDomain.RELATIONSHIPS.value)
        check("should_ask_curiosity = False after repeated skips",
              ask is False, f"profile={p.curiosity_mult} dom={p.domain_curiosity}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_roundtrip():
    eng, t = _tmp()
    try:
        eng.record_interaction(L.EngagementSignal(
            agent_id="fast_mentor", output_chars=300,
            user_explicit_positive=True,
            curiosity_question_answered=True,
            domain=L.LifeDomain.CAREER.value,
        ))
        eng.save()
        eng2 = L.VoiceEvolutionEngine(eng.path).load()
        check("profile persisted across reload",
              "fast_mentor" in eng2.profiles)
        p = eng2.profiles["fast_mentor"]
        check("interaction count preserved", p.interaction_count == 1)
        check("domain curiosity preserved",
              p.domain_curiosity.get(L.LifeDomain.CAREER.value, 1.0) > 1.0)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_neutral_profile_for_new_agent,
        test_positive_signal_on_long_output_drops_brevity_pref,
        test_negative_signal_on_long_output_raises_brevity_pref,
        test_drift_bounded,
        test_answered_curiosity_bumps_domain_multiplier,
        test_unanswered_curiosity_drops_domain_multiplier,
        test_evolved_salience_shrinks_with_brevity,
        test_should_ask_curiosity_threshold,
        test_roundtrip,
        test_no_regression,
    ]
    for t in tests:
        try: t()
        except Exception as e: results.append((t.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 4 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
