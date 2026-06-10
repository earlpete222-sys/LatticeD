"""Sprint 12 - Business Mode tests. Standalone."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp(): return Path(tempfile.mkdtemp(prefix="sprint12_"))


def test_business_store_register_and_active():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bp = L.BusinessProfile(business_id="acme", display_name="Acme LLC", role="founder")
        bs.register(bp, set_active=True)
        check("active is acme", bs.active() and bs.active().business_id == "acme")
        check("can list profile", "acme" in bs.profiles)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_business_store_first_register_becomes_active():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bs.register(L.BusinessProfile(business_id="b1", display_name="B1"))
        check("first registered becomes active by default",
              bs.active() and bs.active().business_id == "b1")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_business_add_fact_and_dedup():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bs.register(L.BusinessProfile(business_id="acme", display_name="Acme"))
        bs.add_fact("acme", "Our MRR hit $20k this month.")
        bs.add_fact("acme", "Our MRR hit $20k this month.")  # dup
        bp = bs.profiles["acme"]
        check("dedup keeps 1 fact", len(bp.facts) == 1)
        check("seen_count incremented", bp.facts[0].seen_count == 2)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_business_add_north_star():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bs.register(L.BusinessProfile(business_id="acme", display_name="Acme"))
        ns = bs.add_north_star("acme", "Hit $1M ARR within 18 months.", weight=1.8)
        check("north star added", ns is not None and ns.weight == 1.8)
        check("default domain is business",
              ns.domain == L.LifeDomain.BUSINESS.value)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_business_store_roundtrip():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bp = L.BusinessProfile(business_id="acme", display_name="Acme Co",
                               legal_entity="LLC", role="founder")
        bs.register(bp, set_active=True)
        bs.add_fact("acme", "We have 3 paying clients.")
        bs.add_north_star("acme", "Become category leader.", weight=2.0)
        bs.save()

        bs2 = L.BusinessStore(bs.path).load()
        check("active id preserved", bs2.active_id == "acme")
        check("profile reloaded", "acme" in bs2.profiles)
        bp2 = bs2.profiles["acme"]
        check("fact preserved", len(bp2.facts) == 1)
        check("north star preserved", len(bp2.north_stars) == 1)
        check("legal entity preserved", bp2.legal_entity == "LLC")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_detect_business_intent_strong():
    score = L.detect_business_intent("Our company needs to extend runway by 6 months.")
    check("multi-term match -> moderate-to-high score",
          score >= 0.5, f"got {score}")


def test_detect_business_intent_zero():
    score = L.detect_business_intent("I had a great hike on Saturday.")
    check("no signal -> 0", score == 0.0, f"got {score}")


def test_route_fact_no_active_business_returns_personal():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        route, bid = L.route_fact("Our client signed the contract.", bs)
        check("no active business -> personal", route == "personal" and bid is None)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_route_fact_business_intent_wins():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bs.register(L.BusinessProfile(business_id="acme", display_name="Acme"))
        route, bid = L.route_fact("Our client signed the contract.", bs)
        check("business-shaped text routes to active business",
              route == "business" and bid == "acme", f"got {(route, bid)}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_route_fact_personal_text_stays_personal():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bs.register(L.BusinessProfile(business_id="acme", display_name="Acme"))
        route, bid = L.route_fact("My wife and I are looking at houses.", bs)
        check("personal-shaped text stays personal even with active business",
              route == "personal", f"got {(route, bid)}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_route_fact_business_domain_text_routes_to_business():
    t = _tmp()
    try:
        bs = L.BusinessStore(t/"biz.json")
        bs.register(L.BusinessProfile(business_id="acme", display_name="Acme"))
        route, bid = L.route_fact(
            "Our startup just hit $20k MRR with the new product launch.",
            bs,
        )
        check("BUSINESS domain text routes to active business",
              route == "business" and bid == "acme",
              f"got {(route, bid)}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_business_store_register_and_active,
        test_business_store_first_register_becomes_active,
        test_business_add_fact_and_dedup,
        test_business_add_north_star,
        test_business_store_roundtrip,
        test_detect_business_intent_strong,
        test_detect_business_intent_zero,
        test_route_fact_no_active_business_returns_personal,
        test_route_fact_business_intent_wins,
        test_route_fact_personal_text_stays_personal,
        test_route_fact_business_domain_text_routes_to_business,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 12 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
