"""Sprint 6 - Memory Architecture Advances tests. Standalone."""
from __future__ import annotations
import sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def test_decay_no_age_returns_full_confidence():
    r = L.MemoryRecord(text="x", tier=L.MemoryTier.EPISODIC.value, confidence=0.9)
    check("fresh record decays to ~original", abs(L.apply_decay(r) - 0.9) < 1e-6)


def test_decay_at_halflife_is_half():
    r = L.MemoryRecord(text="x", tier=L.MemoryTier.EPISODIC.value, confidence=0.8)
    r.last_seen = time.time() - (45 * 86400)
    val = L.apply_decay(r)
    check("at 45-day halflife confidence ~= 0.4",
          abs(val - 0.4) < 0.01, f"got {val}")


def test_decay_semantic_slower_than_episodic():
    r_ep  = L.MemoryRecord(text="x", tier=L.MemoryTier.EPISODIC.value, confidence=0.9)
    r_sem = L.MemoryRecord(text="x", tier=L.MemoryTier.SEMANTIC.value, confidence=0.9)
    age = time.time() - (60 * 86400)
    r_ep.last_seen = r_sem.last_seen = age
    check("semantic decays slower than episodic at same age",
          L.apply_decay(r_sem) > L.apply_decay(r_ep),
          f"sem={L.apply_decay(r_sem):.3f} ep={L.apply_decay(r_ep):.3f}")


def test_decay_working_tier_no_persistence_effect():
    r = L.MemoryRecord(text="x", tier=L.MemoryTier.WORKING.value, confidence=0.8)
    r.last_seen = time.time() - (90 * 86400)   # would crush an episodic record
    check("working tier ignores age",
          L.apply_decay(r) == 0.8)


def test_router_secret_pinned_to_working():
    tier, sens, _ = L.MemoryRouter.route("My password is hunter2.")
    check("SECRET content -> WORKING tier", tier == L.MemoryTier.WORKING.value,
          f"got tier={tier} sens={sens}")


def test_router_identity_shaped_routes_to_identity():
    tier, sens, dom = L.MemoryRouter.route("I work as a designer at a media agency.")
    check("'I work as...' routes to IDENTITY tier",
          tier == L.MemoryTier.IDENTITY.value, f"got tier={tier}")
    check("domain inferred as CAREER", dom == L.LifeDomain.CAREER.value, f"got {dom}")


def test_router_default_episodic():
    tier, sens, _ = L.MemoryRouter.route("The cafe on the corner has great coffee.")
    check("ordinary observation -> EPISODIC", tier == L.MemoryTier.EPISODIC.value, f"got tier={tier}")


def test_store_dedup_and_seen_count():
    s = L.MemoryStore()
    s.add(L.MemoryRecord(text="Coffee meets bagel.", tier=L.MemoryTier.EPISODIC.value))
    s.add(L.MemoryRecord(text="  coffee  meets BAGEL.", tier=L.MemoryTier.EPISODIC.value))
    check("dedup by normalized text", len(s.records) == 1, f"got {len(s.records)}")
    check("seen_count incremented", s.records[0].seen_count == 2)


def test_store_search_filters_sensitivity():
    s = L.MemoryStore()
    s.add(L.MemoryRecord(text="My SSN appears here.",
                         sensitivity=L.Sensitivity.HIGH.value, confidence=0.9))
    s.add(L.MemoryRecord(text="The weather is nice today.",
                         sensitivity=L.Sensitivity.LOW.value, confidence=0.9))
    medium_only = s.search("weather SSN", max_sensitivity=L.Sensitivity.MEDIUM.value)
    check("HIGH content excluded from MEDIUM-ceiling search",
          all(r.sensitivity != L.Sensitivity.HIGH.value for r, _ in medium_only),
          f"got {[(r.text, r.sensitivity) for r,_ in medium_only]}")


def test_store_consolidation_promotes_repeated_facts():
    s = L.MemoryStore()
    r = L.MemoryRecord(text="I run twice a week.", tier=L.MemoryTier.EPISODIC.value)
    s.add(r)
    s.add(L.MemoryRecord(text="I run twice a week.", tier=L.MemoryTier.EPISODIC.value))
    s.add(L.MemoryRecord(text="I run twice a week.", tier=L.MemoryTier.EPISODIC.value))
    promoted = s.consolidate()
    check("3 sightings -> 1 promotion", promoted == 1, f"got {promoted}")
    check("record tier upgraded to SEMANTIC",
          s.records[0].tier == L.MemoryTier.SEMANTIC.value)


def test_purge_expired_drops_dead_records():
    s = L.MemoryStore()
    dead = L.MemoryRecord(text="ancient", tier=L.MemoryTier.EPISODIC.value, confidence=0.06)
    dead.last_seen = time.time() - (10 * 365 * 86400)  # 10 years
    alive = L.MemoryRecord(text="fresh", tier=L.MemoryTier.EPISODIC.value, confidence=0.9)
    s.records.extend([dead, alive])
    dropped = s.purge_expired()
    check("purge drops dead record", dropped == 1, f"got {dropped}")
    check("purge keeps fresh record",
          any(r.text == "fresh" for r in s.records))


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_decay_no_age_returns_full_confidence,
        test_decay_at_halflife_is_half,
        test_decay_semantic_slower_than_episodic,
        test_decay_working_tier_no_persistence_effect,
        test_router_secret_pinned_to_working,
        test_router_identity_shaped_routes_to_identity,
        test_router_default_episodic,
        test_store_dedup_and_seen_count,
        test_store_search_filters_sensitivity,
        test_store_consolidation_promotes_repeated_facts,
        test_purge_expired_drops_dead_records,
        test_no_regression,
    ]
    for t in tests:
        try: t()
        except Exception as e: results.append((t.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 6 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
