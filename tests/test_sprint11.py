"""Sprint 11 - Aspect Extraction + Cross-Memory Recombination tests."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp(): return Path(tempfile.mkdtemp(prefix="sprint11_"))


# ---------- aspect extraction ----------
def test_extract_profession():
    asps = L.extract_aspects("I work as a software engineer at Acme Corp.")
    prof = [a for a in asps if a.name == "profession"]
    check("profession aspect extracted", len(prof) >= 1, f"got {prof}")
    if prof:
        check("profession value reasonable",
              "software engineer" in prof[0].value.lower(),
              f"got {prof[0].value!r}")


def test_extract_partner_status():
    asps = L.extract_aspects("My wife and I went hiking on Saturday.")
    p = [a for a in asps if a.name == "partner_status"]
    check("partner_status aspect extracted", len(p) >= 1, f"got {p}")
    if p:
        check("value mentions wife", "wife" in p[0].value.lower())


def test_extract_children():
    asps = L.extract_aspects("I have 2 kids and they keep me busy.")
    c = [a for a in asps if a.name == "children"]
    check("children aspect extracted", len(c) >= 1, f"got {c}")
    if c:
        check("value mentions 2 kids", "2" in c[0].value and "kid" in c[0].value.lower())


def test_extract_financial_goal():
    asps = L.extract_aspects("I'm saving for a down payment on a house.")
    g = [a for a in asps if a.name == "financial_goal"]
    check("financial_goal aspect extracted", len(g) >= 1, f"got {g}")


def test_extract_learning_goal():
    asps = L.extract_aspects("I'm currently learning Rust programming on weekends.")
    g = [a for a in asps if a.name == "learning_goal"]
    check("learning_goal aspect extracted", len(g) >= 1, f"got {g}")


def test_no_false_positive_on_unrelated_text():
    asps = L.extract_aspects("The sky is blue today.")
    check("no aspects from unrelated text", len(asps) == 0, f"got {asps}")


# ---------- aspect index ----------
def test_aspect_index_from_store():
    t = _tmp()
    try:
        s = L.IdentityStore(t/"id.json")
        s.add_fact("I work as a designer.", domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("My wife is a teacher.", domain=L.LifeDomain.RELATIONSHIPS.value, confidence=0.9)
        s.add_fact("I have 3 kids.", domain=L.LifeDomain.RELATIONSHIPS.value, confidence=0.9)
        idx = L.AspectIndex.from_store(s)
        check("index has profession", "profession" in idx.names())
        check("index has partner_status", "partner_status" in idx.names())
        check("index has children", "children" in idx.names())
    finally: shutil.rmtree(t, ignore_errors=True)


def test_aspect_confidence_blends_with_fact():
    t = _tmp()
    try:
        s = L.IdentityStore(t/"id.json")
        s.add_fact("I work as a manager.", domain=L.LifeDomain.CAREER.value, confidence=0.95)
        idx = L.AspectIndex.from_store(s)
        prof = idx.get("profession")
        check("profession confidence reflects fact confidence",
              prof and prof[0].confidence > 0.7, f"got {prof[0].confidence if prof else None}")
    finally: shutil.rmtree(t, ignore_errors=True)


# ---------- recombination ----------
def test_recombine_finds_cross_domain_link():
    t = _tmp()
    try:
        s = L.IdentityStore(t/"id.json")
        # Career fact mentioning "training"; Health fact also mentioning "training".
        s.add_fact("I provide training to engineers on the team.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I started marathon training last month.",
                   domain=L.LifeDomain.HEALTH.value, confidence=0.85)
        insights = L.recombine_memory(s)
        check("at least one cross-domain insight surfaced",
              len(insights) >= 1, f"got {insights}")
        if insights:
            ins = insights[0]
            check("link spans career and health",
                  {ins.domain_a, ins.domain_b} == {L.LifeDomain.CAREER.value, L.LifeDomain.HEALTH.value},
                  f"got {ins.domain_a} <-> {ins.domain_b}")
            check("'training' surfaces as shared term",
                  "training" in ins.link_terms, f"terms={ins.link_terms}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_recombine_skips_same_domain_pairs():
    t = _tmp()
    try:
        s = L.IdentityStore(t/"id.json")
        s.add_fact("I run distance routes.", domain=L.LifeDomain.HEALTH.value, confidence=0.9)
        s.add_fact("I run sprint intervals.", domain=L.LifeDomain.HEALTH.value, confidence=0.9)
        insights = L.recombine_memory(s)
        # Both facts same domain -> no cross-domain pairing.
        check("same-domain pair produces no insight",
              len(insights) == 0, f"got {insights}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_recombine_score_ranking():
    t = _tmp()
    try:
        s = L.IdentityStore(t/"id.json")
        # Strong cross-domain overlap.
        s.add_fact("I love mentoring junior teammates.",
                   domain=L.LifeDomain.CAREER.value, confidence=0.9)
        s.add_fact("I enjoy mentoring younger family members.",
                   domain=L.LifeDomain.RELATIONSHIPS.value, confidence=0.9)
        # Weaker overlap (just 'enjoy').
        s.add_fact("I enjoy hiking.",
                   domain=L.LifeDomain.LIFESTYLE.value, confidence=0.7)
        insights = L.recombine_memory(s, top_k=10)
        check("strongest insight involves career+relationships",
              insights and ({insights[0].domain_a, insights[0].domain_b}
                            == {L.LifeDomain.CAREER.value, L.LifeDomain.RELATIONSHIPS.value}),
              f"got {[(i.domain_a, i.domain_b, i.score) for i in insights]}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_recombine_respects_top_k():
    t = _tmp()
    try:
        s = L.IdentityStore(t/"id.json")
        for i in range(5):
            s.add_fact(f"Career discipline number {i} routine work.",
                       domain=L.LifeDomain.CAREER.value, confidence=0.9)
            s.add_fact(f"Health discipline number {i} routine work.",
                       domain=L.LifeDomain.HEALTH.value, confidence=0.9)
        insights = L.recombine_memory(s, top_k=3)
        check("top_k=3 returns at most 3 insights",
              len(insights) <= 3, f"got {len(insights)}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_extract_profession,
        test_extract_partner_status,
        test_extract_children,
        test_extract_financial_goal,
        test_extract_learning_goal,
        test_no_false_positive_on_unrelated_text,
        test_aspect_index_from_store,
        test_aspect_confidence_blends_with_fact,
        test_recombine_finds_cross_domain_link,
        test_recombine_skips_same_domain_pairs,
        test_recombine_score_ranking,
        test_recombine_respects_top_k,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 11 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
