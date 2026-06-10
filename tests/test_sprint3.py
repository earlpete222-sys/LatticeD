"""Sprint 3 - Voice Context + Continuity Tokens tests. Standalone."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp():
    t = Path(tempfile.mkdtemp(prefix="sprint3_"))
    return L.IdentityStore(t/"id.json"), L.EngagementLedger(t/"cur.json"), L.ContinuityStore(t/"cont.json"), t


def test_preamble_router_empty():
    s, _, _, t = _tmp()
    try:
        s.add_fact("I make $100k.")
        check("intent_router never sees user identity",
              L.build_voice_preamble("intent_router", s) == "")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_preamble_unknown_agent_empty():
    s, _, _, t = _tmp()
    try:
        check("unknown agent_id yields empty preamble",
              L.build_voice_preamble("not_an_agent", s) == "")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_preamble_quant_architect_financial_only():
    s, _, _, t = _tmp()
    try:
        s.add_fact("My salary is $90k.", confidence=0.9)         # FINANCIAL
        s.add_fact("My wife is a teacher.", confidence=0.9)       # RELATIONSHIPS
        s.add_fact("I run twice a week.", confidence=0.9)         # HEALTH
        p = L.build_voice_preamble("quant_architect", s)
        check("architect preamble includes financial fact", "$90k" in p, p[:200])
        check("architect preamble EXCLUDES relationships fact", "wife is a teacher" not in p, p[:200])
        check("architect preamble EXCLUDES health fact", "run twice" not in p, p[:200])
    finally: shutil.rmtree(t, ignore_errors=True)


def test_preamble_life_coach_all_domains():
    s, _, _, t = _tmp()
    try:
        s.add_fact("My salary is $90k.", confidence=0.9)
        s.add_fact("My wife is a teacher.", confidence=0.9)
        p = L.build_voice_preamble("life_coach", s)
        check("life_coach sees financial fact",      "$90k" in p)
        check("life_coach sees relationships fact",  "wife is a teacher" in p)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_preamble_constitutional_rules_outrank():
    s, _, _, t = _tmp()
    try:
        s.add_rule("Never use the word 'leverage' as a verb.", priority=200)
        s.add_fact("My salary is $90k.", confidence=0.9)
        s.add_north_star("Financial freedom by 50.", domain=L.LifeDomain.FINANCIAL.value, weight=1.5)
        p = L.build_voice_preamble("quant_architect", s)
        # Ground rules block must appear BEFORE north stars block.
        check("rules block precedes north stars block",
              p.find("USER GROUND RULES") < p.find("USER NORTH STARS"),
              f"positions: rules={p.find('USER GROUND RULES')} stars={p.find('USER NORTH STARS')}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_preamble_max_facts_cap():
    s, _, _, t = _tmp()
    try:
        for i in range(15):
            s.add_fact(f"Financial fact {i}.", domain=L.LifeDomain.FINANCIAL.value, confidence=0.9)
        p = L.build_voice_preamble("life_coach", s)
        # max_facts for life_coach is 8.
        count = p.count("Financial fact")
        check("life_coach respects max_facts cap (8)", count <= 8, f"got {count}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_preamble_curiosity_hint_optin():
    s, ledger, _, t = _tmp()
    try:
        engine = L.CuriosityEngine(s, ledger, max_per_hour=99, max_per_day=99)
        sel = engine.select_next_question()
        q, gap, gain = sel
        engine.record_question_asked(q, gap, gain)
        # Default: no curiosity hint
        p_off = L.build_voice_preamble("fast_mentor", s, ledger=ledger, include_curiosity_hint=False)
        check("curiosity hint OFF by default", "OPEN CURIOSITY" not in p_off)
        # Opt-in: curiosity hint present
        p_on = L.build_voice_preamble("fast_mentor", s, ledger=ledger, include_curiosity_hint=True)
        check("curiosity hint ON when requested", "OPEN CURIOSITY" in p_on)
        check("curiosity hint quotes the asked question", q[:20] in p_on)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_weave_appends_question_cleanly():
    out = L.weave_curiosity_question("Here is your budget summary.", "What do you do for work?")
    check("weave separates with blank line",
          out.endswith("What do you do for work?")
          and "summary.\n\nWhat" in out, f"out={out!r}")


def test_weave_skips_when_question_already_present():
    base = "Here is the plan. What do you do for work?"
    out = L.weave_curiosity_question(base, "What do you do for work?")
    check("weave is idempotent when question already in text", out == base.rstrip(), f"out={out!r}")


def test_weave_empty_question_passthrough():
    out = L.weave_curiosity_question("Hello.", "")
    check("empty question -> passthrough", out == "Hello.")


# ---------------------------------------------------------------------
# Continuity tokens
# ---------------------------------------------------------------------
def test_continuity_roundtrip():
    _, _, cs, t = _tmp()
    try:
        cs.add(L.ContinuityToken(
            session_id="s1",
            last_intent="PERSONAL",
            open_threads=["weekend with kids", "401k question"],
            domains_touched=["relationships", "financial"],
            mood_signal="focused",
            summary="Talked about balancing work and family time."
        ))
        cs.save()
        cs2 = L.ContinuityStore(cs.path).load()
        check("continuity round-trip: 1 token persisted",
              len(cs2.tokens) == 1, f"got {len(cs2.tokens)}")
        check("summary preserved", cs2.tokens[0].summary.startswith("Talked about"))
    finally: shutil.rmtree(t, ignore_errors=True)


def test_continuity_ring_buffer():
    _, _, cs, t = _tmp()
    try:
        for i in range(L.MAX_CONTINUITY_TOKENS + 5):
            cs.add(L.ContinuityToken(session_id=f"s{i}", summary=f"session {i}"))
        check("ring buffer trims to MAX_CONTINUITY_TOKENS",
              len(cs.tokens) == L.MAX_CONTINUITY_TOKENS,
              f"got {len(cs.tokens)}")
        check("oldest tokens dropped first",
              cs.tokens[0].session_id == f"s5")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_continuity_preamble_empty():
    _, _, cs, t = _tmp()
    try:
        check("empty continuity store -> empty preamble",
              L.build_continuity_preamble(cs) == "")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_continuity_preamble_renders():
    _, _, cs, t = _tmp()
    try:
        cs.add(L.ContinuityToken(
            session_id="s1",
            summary="Discussed promotion path",
            open_threads=["follow up on manager 1:1"],
            mood_signal="focused",
        ))
        p = L.build_continuity_preamble(cs, n=1)
        check("preamble contains the summary", "promotion path" in p, p)
        check("preamble contains the open thread", "manager 1:1" in p, p)
        check("preamble contains mood signal", "focused" in p, p)
    finally: shutil.rmtree(t, ignore_errors=True)


# ---------------------------------------------------------------------
# Regression: Sprint 0/1/2 still pass with Sprint 3 module loaded
# ---------------------------------------------------------------------
def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU still validates", rep.valid, f"errors={rep.errors}")
    check("agent count remains 12", len(reg) == 12)


def main():
    tests = [
        test_preamble_router_empty,
        test_preamble_unknown_agent_empty,
        test_preamble_quant_architect_financial_only,
        test_preamble_life_coach_all_domains,
        test_preamble_constitutional_rules_outrank,
        test_preamble_max_facts_cap,
        test_preamble_curiosity_hint_optin,
        test_weave_appends_question_cleanly,
        test_weave_skips_when_question_already_present,
        test_weave_empty_question_passthrough,
        test_continuity_roundtrip,
        test_continuity_ring_buffer,
        test_continuity_preamble_empty,
        test_continuity_preamble_renders,
        test_no_regression,
    ]
    for t in tests:
        try: t()
        except Exception as e:
            results.append((t.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        m = "[OK]  " if s == "PASS" else "[XX]  "
        print(f"{m}{n}" + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 3 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
