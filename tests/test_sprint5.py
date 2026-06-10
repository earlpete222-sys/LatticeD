"""Sprint 5 - Identity Synthesis Layer tests. Standalone."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp():
    t = Path(tempfile.mkdtemp(prefix="sprint5_"))
    return L.IdentityStore(t/"id.json"), t


def test_empty_domain_summary():
    s, t = _tmp()
    try:
        syn = L.IdentitySynthesizer(s)
        ds = syn.synthesize_domain(L.LifeDomain.CAREER.value)
        check("empty domain has 0 facts", ds.fact_count == 0)
        check("empty domain has empty narrative", ds.narrative == "")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_populated_domain_summary():
    s, t = _tmp()
    try:
        s.add_fact("I work as a software engineer at a fintech startup.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.95)
        s.add_fact("I lead a team of three engineers.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("My boss is supportive but slow to respond.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.8)
        syn = L.IdentitySynthesizer(s)
        ds = syn.synthesize_domain(L.LifeDomain.CAREER.value)
        check("fact_count = 3", ds.fact_count == 3)
        check("avg confidence > 0.8", ds.avg_confidence > 0.8, f"got {ds.avg_confidence}")
        check("representative facts present", len(ds.representative_facts) == 3)
        check("narrative is non-empty", len(ds.narrative) > 20, ds.narrative)
        check("narrative tags the domain",
              "[career]" in ds.narrative.lower(), ds.narrative)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_theme_extraction():
    s, t = _tmp()
    try:
        s.add_fact("My wife and I are arguing about money.",
                   domain=L.LifeDomain.RELATIONSHIPS.value)
        s.add_fact("My wife wants to move closer to her family.",
                   domain=L.LifeDomain.RELATIONSHIPS.value)
        s.add_fact("My wife is starting a new job.",
                   domain=L.LifeDomain.RELATIONSHIPS.value)
        syn = L.IdentitySynthesizer(s)
        ds = syn.synthesize_domain(L.LifeDomain.RELATIONSHIPS.value)
        check("'wife' surfaces as a theme",
              "wife" in ds.themes, f"themes={ds.themes}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_contradiction_detection():
    s, t = _tmp()
    try:
        s.add_fact("I love my job.", domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I hate my job lately.", domain=L.LifeDomain.CAREER.value, confidence=0.85)
        syn = L.IdentitySynthesizer(s)
        conflicts = syn.detect_contradictions()
        check("love vs hate in same domain -> contradiction",
              len(conflicts) >= 1, f"got {conflicts}")
        c = conflicts[0]
        check("contradiction tagged with domain", c.domain == L.LifeDomain.CAREER.value)
        check("contradiction has nontrivial score", c.score > 0.3)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_contradiction_when_consistent():
    s, t = _tmp()
    try:
        s.add_fact("I enjoy my work as a designer.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I like my coworkers.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.9)
        syn = L.IdentitySynthesizer(s)
        conflicts = syn.detect_contradictions()
        check("consistent facts produce no contradictions",
              len(conflicts) == 0, f"got {conflicts}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_user_portrait_composition():
    s, t = _tmp()
    try:
        s.add_fact("I'm a manager at a SaaS company.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I save 20% of every paycheck.",
                   domain=L.LifeDomain.FINANCIAL.value, confidence=0.95)
        s.add_north_star("Lead a 20-person org by 35.",
                         domain=L.LifeDomain.CAREER.value, weight=1.4)
        s.add_rule("Be direct with bad news.", priority=200)
        syn = L.IdentitySynthesizer(s)
        port = syn.synthesize_portrait()
        check("portrait covers 2 domains", len(port.domains) == 2,
              f"got {list(port.domains)}")
        check("portrait includes north star",
              any("20-person" in ns for ns in port.north_stars), port.north_stars)
        check("portrait includes rule",
              any("direct" in r for r in port.rules), port.rules)
        check("one-line summary references both domains",
              "career" in port.one_line_summary and "financial" in port.one_line_summary,
              port.one_line_summary)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_write_back_summaries():
    s, t = _tmp()
    try:
        s.add_fact("I'm an analyst.", domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I work remotely.", domain=L.LifeDomain.CAREER.value, confidence=0.9)
        syn = L.IdentitySynthesizer(s)
        syn.write_back_summaries()
        check("domain summary written to IdentityDocument",
              L.LifeDomain.CAREER.value in s.doc.domain_summaries,
              f"keys={list(s.doc.domain_summaries)}")
        # Persistence survives a save/load round-trip.
        s.save()
        s2 = L.IdentityStore(s.path).load()
        check("written summary survives reload",
              L.LifeDomain.CAREER.value in s2.doc.domain_summaries,
              f"keys={list(s2.doc.domain_summaries)}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_empty_portrait():
    s, t = _tmp()
    try:
        syn = L.IdentitySynthesizer(s)
        port = syn.synthesize_portrait()
        check("empty portrait has 0 domains", len(port.domains) == 0)
        check("empty portrait one-liner is informative",
              "empty" in port.one_line_summary.lower(), port.one_line_summary)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_empty_domain_summary,
        test_populated_domain_summary,
        test_theme_extraction,
        test_contradiction_detection,
        test_no_contradiction_when_consistent,
        test_user_portrait_composition,
        test_write_back_summaries,
        test_empty_portrait,
        test_no_regression,
    ]
    for t in tests:
        try: t()
        except Exception as e: results.append((t.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 5 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
