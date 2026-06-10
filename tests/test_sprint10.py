"""Sprint 10 - Two Mes Model + Predictive Modeling tests. Standalone."""
from __future__ import annotations
import sys, tempfile, shutil, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp():
    t = Path(tempfile.mkdtemp(prefix="sprint10_"))
    return L.IdentityStore(t/"id.json"), t


def test_capture_present_empty():
    s, t = _tmp()
    try:
        snap = L.capture_present(s)
        check("empty present has 0 facts", snap.fact_count == 0)
        check("empty present has 0 active domains", len(snap.domain_fact_counts) == 0)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_capture_present_populated():
    s, t = _tmp()
    try:
        s.add_fact("I work as a designer.", domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I run twice a week.",   domain=L.LifeDomain.HEALTH.value, confidence=0.85)
        snap = L.capture_present(s)
        check("present captures 2 domains", len(snap.domain_fact_counts) == 2)
        check("present total fact count = 2", snap.fact_count == 2)
        check("present avg conf reasonable",
              0.8 <= snap.domain_avg_confidence[L.LifeDomain.HEALTH.value] <= 0.9)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_capture_aspirational():
    s, t = _tmp()
    try:
        s.add_north_star("Lead a team.", domain=L.LifeDomain.CAREER.value, weight=1.5)
        s.add_north_star("Run a half marathon.", domain=L.LifeDomain.HEALTH.value, weight=1.2)
        s.add_north_star("Save for a house.", domain=L.LifeDomain.FINANCIAL.value, weight=1.0)
        snap = L.capture_aspirational(s)
        check("aspirational tracks 3 domains",
              len(set(snap.north_star_domains)) == 3, f"got {snap.north_star_domains}")
        check("aspirational financial weight = 1.0",
              abs(snap.north_star_weights[L.LifeDomain.FINANCIAL.value] - 1.0) < 1e-6)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_tension_score_high_when_aspiration_no_facts():
    s, t = _tmp()
    try:
        s.add_north_star("Become a manager.", domain=L.LifeDomain.CAREER.value, weight=2.0)
        m = L.TwoMesModel.from_store(s)
        score = L.tension_score(m, L.LifeDomain.CAREER.value)
        check("strong aspiration + no facts -> high tension",
              score > 0.8, f"got {score}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_tension_score_low_when_aspiration_matches_facts():
    s, t = _tmp()
    try:
        for i in range(5):
            s.add_fact(f"Career fact {i} I work in tech as a lead engineer.",
                       domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_north_star("Lead a team.", domain=L.LifeDomain.CAREER.value, weight=1.0)
        m = L.TwoMesModel.from_store(s)
        score = L.tension_score(m, L.LifeDomain.CAREER.value)
        check("strong present-self saturates tension",
              score < 0.2, f"got {score}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_tension_zero_when_no_aspiration():
    s, t = _tmp()
    try:
        s.add_fact("I run.", domain=L.LifeDomain.HEALTH.value, confidence=0.9)
        m = L.TwoMesModel.from_store(s)
        score = L.tension_score(m, L.LifeDomain.HEALTH.value)
        check("no north star -> 0 tension", score == 0.0)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_high_tension_domains_ranked():
    s, t = _tmp()
    try:
        s.add_north_star("Become an engineer.", domain=L.LifeDomain.CAREER.value, weight=2.0)
        s.add_north_star("Build wealth.",        domain=L.LifeDomain.FINANCIAL.value, weight=1.0)
        s.add_fact("My salary is $90k.",         domain=L.LifeDomain.FINANCIAL.value, confidence=0.9)
        m = L.TwoMesModel.from_store(s)
        tens = L.high_tension_domains(m)
        check("career > financial in tension ranking",
              tens and tens[0][0] == L.LifeDomain.CAREER.value, f"got {tens}")
    finally: shutil.rmtree(t, ignore_errors=True)


# ---------- predict_engagement ----------
def test_predict_engagement_uses_ledger_history():
    s, t = _tmp()
    try:
        ledger = L.EngagementLedger(t/"cur.json")
        # Plant 4 prior career questions, 3 answered.
        for i in range(4):
            ledger.add(L.CuriosityEngagement(
                question=f"q{i}", domain=L.LifeDomain.CAREER.value,
                gap_type=L.GapType.LOW_COVERAGE.value, answered=(i != 3),
            ))
        pred = L.predict_engagement(
            "What do you do for work?", s, ledger=ledger,
        )
        check("predicted rate near ledger rate (3/4)",
              0.6 <= pred.estimated_response_rate <= 0.85,
              f"got {pred.estimated_response_rate}")
        check("predicted domain = career", pred.likely_domain == L.LifeDomain.CAREER.value)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_predict_engagement_no_signal_defaults():
    s, t = _tmp()
    try:
        pred = L.predict_engagement("The sky is blue.", s)
        check("no domain signal -> default 0.5",
              pred.estimated_response_rate == 0.5)
        check("domain = uncategorized",
              pred.likely_domain == L.LifeDomain.UNCATEGORIZED.value)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_predict_engagement_voice_multiplier_applied():
    s, t = _tmp()
    try:
        voice = L.VoiceEvolutionEngine(t/"voice.json")
        # Drop curiosity for relationships.
        for _ in range(20):
            voice.record_interaction(L.EngagementSignal(
                agent_id="fast_mentor", output_chars=200,
                curiosity_question_answered=False,
                domain=L.LifeDomain.RELATIONSHIPS.value,
            ))
        pred = L.predict_engagement(
            "My wife and I are arguing.", s, voice=voice,
        )
        check("voice multiplier reduces prediction",
              pred.estimated_response_rate < 0.5,
              f"got {pred.estimated_response_rate}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_predict_engagement_north_star_boost():
    s, t = _tmp()
    try:
        ledger = L.EngagementLedger(t/"cur.json")
        # 2/4 baseline = 0.5.
        for i in range(4):
            ledger.add(L.CuriosityEngagement(
                question=f"q{i}", domain=L.LifeDomain.GROWTH.value,
                gap_type=L.GapType.LOW_COVERAGE.value, answered=(i < 2),
            ))
        s.add_north_star("Keep learning every week.",
                         domain=L.LifeDomain.GROWTH.value, weight=1.5)
        pred = L.predict_engagement(
            "What's a skill you're working on improving?", s, ledger=ledger,
        )
        check("north-star boost > 0.5",
              pred.estimated_response_rate > 0.5, f"got {pred.estimated_response_rate}")
    finally: shutil.rmtree(t, ignore_errors=True)


# ---------- drift report ----------
def test_drift_report_detects_growth():
    s, t = _tmp()
    try:
        s.add_fact("I'm a junior dev.", domain=L.LifeDomain.CAREER.value, confidence=0.7)
        earlier = L.capture_present(s, label="t0")
        # Advance "time" (no actual sleep needed - the report only uses fact_count deltas).
        s.add_fact("I now lead a team.", domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I started cycling.", domain=L.LifeDomain.HEALTH.value, confidence=0.85)
        later = L.capture_present(s, label="t1")
        rep = L.drift_report(earlier, later)
        check("drift detects +2 facts", rep.fact_delta == 2, f"got {rep.fact_delta}")
        check("drift reports HEALTH as new domain",
              L.LifeDomain.HEALTH.value in rep.new_domains, f"new={rep.new_domains}")
        check("drift detects CAREER confidence rise",
              rep.confidence_changes.get(L.LifeDomain.CAREER.value, 0.0) > 0,
              f"changes={rep.confidence_changes}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_capture_present_empty,
        test_capture_present_populated,
        test_capture_aspirational,
        test_tension_score_high_when_aspiration_no_facts,
        test_tension_score_low_when_aspiration_matches_facts,
        test_tension_zero_when_no_aspiration,
        test_high_tension_domains_ranked,
        test_predict_engagement_uses_ledger_history,
        test_predict_engagement_no_signal_defaults,
        test_predict_engagement_voice_multiplier_applied,
        test_predict_engagement_north_star_boost,
        test_drift_report_detects_growth,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 10 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
