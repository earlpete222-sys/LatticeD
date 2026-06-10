"""
Sprint 2 - Curiosity Engine (Information-Theoretic) regression tests.

Standalone (no server, no Ollama). Exit code 0 = all pass.

Usage:
    python tests/test_sprint2.py
"""

from __future__ import annotations

import sys
import time
import tempfile
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "latticed"))

import latticed as L  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, PASS if cond else FAIL, detail))


def _tmp_pair() -> tuple[L.IdentityStore, L.EngagementLedger, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="sprint2_"))
    store  = L.IdentityStore(path=tmp / "identity.json", user_id="test")
    ledger = L.EngagementLedger(path=tmp / "curiosity.json")
    return store, ledger, tmp


# ---------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------
def test_empty_store_detects_low_coverage_for_every_domain() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        gaps = engine.detect_gaps()
        coverage_domains = {g.domain for g in gaps if g.gap_type == L.GapType.LOW_COVERAGE.value}
        non_uncat = {d.value for d in L.LifeDomain if d != L.LifeDomain.UNCATEGORIZED}
        check("empty store -> LOW_COVERAGE gap for every real domain",
              coverage_domains == non_uncat,
              f"missing={non_uncat - coverage_domains}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_adding_facts_reduces_low_coverage_gaps() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        # Add 3 financial facts to close the coverage gap there.
        store.add_fact("My salary is $90k.")
        store.add_fact("I owe $20k in student loans.")
        store.add_fact("I save into a 401k each month.")
        gaps = engine.detect_gaps()
        fin_coverage = [g for g in gaps
                        if g.domain == L.LifeDomain.FINANCIAL.value
                        and g.gap_type == L.GapType.LOW_COVERAGE.value]
        check("3 financial facts closes LOW_COVERAGE for FINANCIAL",
              len(fin_coverage) == 0,
              f"residual={fin_coverage}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_low_confidence_triggers_gap() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        # Add a fact at low confidence directly.
        store.add_fact("Maybe I want to switch careers.",
                       domain=L.LifeDomain.CAREER.value, confidence=0.3)
        engine = L.CuriosityEngine(store, ledger)
        gaps = engine.detect_gaps()
        low_conf = [g for g in gaps
                    if g.domain == L.LifeDomain.CAREER.value
                    and g.gap_type == L.GapType.LOW_CONFIDENCE.value]
        check("low-confidence fact in domain -> LOW_CONFIDENCE gap",
              len(low_conf) == 1, f"got {low_conf}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_north_star_only_when_facts_exist() -> None:
    """NO_NORTH_STAR gap is only worth surfacing once the user is active in that domain."""
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        # Empty store - should have NO NO_NORTH_STAR gaps (would be noise).
        gaps0 = engine.detect_gaps()
        ns_gaps0 = [g for g in gaps0 if g.gap_type == L.GapType.NO_NORTH_STAR.value]
        check("empty store has no NO_NORTH_STAR gaps", len(ns_gaps0) == 0,
              f"got {ns_gaps0}")

        # Add a career fact - should now surface NO_NORTH_STAR for CAREER.
        store.add_fact("I'm a software engineer at a startup.",
                       domain=L.LifeDomain.CAREER.value, confidence=0.9)
        gaps1 = engine.detect_gaps()
        ns_gaps1 = [g for g in gaps1
                    if g.gap_type == L.GapType.NO_NORTH_STAR.value
                    and g.domain == L.LifeDomain.CAREER.value]
        check("fact without north star -> NO_NORTH_STAR gap for that domain",
              len(ns_gaps1) == 1, f"got {ns_gaps1}")

        # Add a north star - gap should disappear.
        store.add_north_star("Lead a team within 3 years.",
                             domain=L.LifeDomain.CAREER.value, weight=1.2)
        gaps2 = engine.detect_gaps()
        ns_gaps2 = [g for g in gaps2
                    if g.gap_type == L.GapType.NO_NORTH_STAR.value
                    and g.domain == L.LifeDomain.CAREER.value]
        check("adding a north star closes NO_NORTH_STAR gap",
              len(ns_gaps2) == 0, f"residual={ns_gaps2}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_stale_domain_flagged() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        f = store.add_fact("I cook on weekends.",
                            domain=L.LifeDomain.LIFESTYLE.value, confidence=0.8)
        # Backdate the fact 45 days.
        f.last_seen  = time.time() - (45 * 86400)
        f.first_seen = f.last_seen
        engine = L.CuriosityEngine(store, ledger)
        gaps = engine.detect_gaps()
        stale = [g for g in gaps
                  if g.gap_type == L.GapType.STALE_DOMAIN.value
                  and g.domain == L.LifeDomain.LIFESTYLE.value]
        check("fact older than STALE_DAYS -> STALE_DOMAIN gap",
              len(stale) == 1, f"got {stale}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------
# Information theory
# ---------------------------------------------------------------------
def test_entropy_empty_domain_high() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        h_empty = engine.domain_entropy(L.LifeDomain.HEALTH.value)
        check("empty domain has positive entropy", h_empty > 0.5,
              f"H_empty={h_empty:.3f}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_entropy_decreases_as_facts_accumulate() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        h0 = engine.domain_entropy(L.LifeDomain.HEALTH.value)
        store.add_fact("I run 5k twice a week.",
                       domain=L.LifeDomain.HEALTH.value, confidence=0.9)
        h1 = engine.domain_entropy(L.LifeDomain.HEALTH.value)
        store.add_fact("I sleep about 7 hours nightly.",
                       domain=L.LifeDomain.HEALTH.value, confidence=0.85)
        h2 = engine.domain_entropy(L.LifeDomain.HEALTH.value)
        check("entropy strictly decreases as facts accumulate",
              h0 > h1 > h2,
              f"H0={h0:.3f} H1={h1:.3f} H2={h2:.3f}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_expected_information_gain_nonneg() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        gaps = engine.detect_gaps()
        gains = [engine.expected_information_gain(g) for g in gaps[:5]]
        check("expected information gain is non-negative for every gap",
              all(g >= 0.0 for g in gains), f"gains={gains}")
        check("at least one positive-gain gap in empty store",
              any(g > 0.0 for g in gains), f"gains={gains}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------
# Question generation + selection
# ---------------------------------------------------------------------
def test_generate_questions_for_low_coverage() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        gap = L.IdentityGap(
            domain=L.LifeDomain.FINANCIAL.value,
            gap_type=L.GapType.LOW_COVERAGE.value,
            score=1.0,
        )
        cands = engine.question_candidates_for_gap(gap)
        check("LOW_COVERAGE / FINANCIAL has > 0 templates", len(cands) > 0,
              f"got {cands}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_select_next_question_returns_a_question() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger)
        sel = engine.select_next_question()
        check("select_next_question returns a triple on empty store",
              sel is not None, f"got {sel}")
        q, gap, gain = sel
        check("selected question is non-empty", isinstance(q, str) and len(q) > 5,
              f"q={q!r}")
        check("selected gap.score > 0", gap.score > 0, f"score={gap.score}")
        check("selected expected gain >= 0", gain >= 0, f"gain={gain}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_already_asked_questions_are_filtered() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger, max_per_hour=99, max_per_day=99)
        sel = engine.select_next_question()
        assert sel is not None
        q, gap, gain = sel
        engine.record_question_asked(q, gap, gain)
        # Re-selecting should NOT produce the same question.
        sel2 = engine.select_next_question()
        if sel2 is not None:
            q2, _, _ = sel2
            check("re-selection avoids already-asked question", q2 != q,
                  f"q={q!r}\nq2={q2!r}")
        else:
            check("re-selection avoids already-asked question (or returns None)",
                  True, "no more candidates")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------
def test_hourly_budget_enforced() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger, max_per_hour=1, max_per_day=99)
        sel = engine.select_next_question()
        assert sel is not None
        q, gap, gain = sel
        engine.record_question_asked(q, gap, gain)
        # No response yet -> outstanding=1, hourly budget exhausted.
        sel2 = engine.select_next_question()
        check("hourly budget blocks further questions while one is outstanding",
              sel2 is None, f"got {sel2}")
        # User answers - hourly budget should free up.
        engine.record_response(q, answered=True, response_excerpt="Sure, my salary is $90k.")
        sel3 = engine.select_next_question()
        check("answering frees the hourly budget",
              sel3 is not None, f"got {sel3}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_daily_budget_enforced() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger, max_per_hour=99, max_per_day=2)
        # Ask + answer twice to consume the daily quota.
        for _ in range(2):
            sel = engine.select_next_question()
            assert sel is not None, "ran out of candidates before quota - inconsistent fixture"
            q, gap, gain = sel
            engine.record_question_asked(q, gap, gain)
            engine.record_response(q, answered=True)
        sel3 = engine.select_next_question()
        check("daily budget blocks further questions once 2 asked in 24h",
              sel3 is None, f"got {sel3}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------
# Engagement ledger
# ---------------------------------------------------------------------
def test_engagement_ledger_roundtrip() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger, max_per_hour=99, max_per_day=99)
        sel = engine.select_next_question()
        q, gap, gain = sel
        engine.record_question_asked(q, gap, gain)
        engine.record_response(q, answered=True, response_excerpt="ok sure")
        ledger.save()

        ledger2 = L.EngagementLedger(path=ledger.path).load()
        check("engagement ledger round-trip: 1 entry persisted",
              len(ledger2.entries) == 1, f"got {len(ledger2.entries)}")
        e = ledger2.entries[0]
        check("persisted answered=True", e.answered is True)
        check("persisted excerpt", e.response_excerpt == "ok sure")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_response_rate_per_domain() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        engine = L.CuriosityEngine(store, ledger, max_per_hour=99, max_per_day=99)
        # Drive 3 questions: 2 answered, 1 skipped.
        answers = [True, True, False]
        domains = []
        for ans in answers:
            sel = engine.select_next_question()
            assert sel is not None
            q, gap, gain = sel
            engine.record_question_asked(q, gap, gain)
            engine.record_response(q, answered=ans)
            domains.append(gap.domain)
        global_rate = ledger.response_rate()
        check("global response rate = 2/3",
              abs(global_rate - (2/3)) < 1e-6, f"got {global_rate}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_already_asked_normalization() -> None:
    store, ledger, tmp = _tmp_pair()
    try:
        ledger.add(L.CuriosityEngagement(
            question="What do YOU  do for work?",
            domain=L.LifeDomain.CAREER.value,
            gap_type=L.GapType.LOW_COVERAGE.value,
        ))
        check("already_asked is whitespace/case insensitive",
              ledger.already_asked("what do you do for work?"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------
# Integration with Sprint 0 / 1
# ---------------------------------------------------------------------
def test_curiosity_does_not_break_sprint1() -> None:
    """Module-level additions must not regress Sprint 0 / Sprint 1."""
    import importlib
    importlib.reload(L)   # noqa: F841 - just confirm module reloads cleanly
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU still validates with Sprint 2 module present",
          rep.valid, f"errors={rep.errors}")
    check("agent count remains 12", len(reg) == 12, f"got {len(reg)}")


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------
def main() -> int:
    tests = [
        test_empty_store_detects_low_coverage_for_every_domain,
        test_adding_facts_reduces_low_coverage_gaps,
        test_low_confidence_triggers_gap,
        test_no_north_star_only_when_facts_exist,
        test_stale_domain_flagged,
        test_entropy_empty_domain_high,
        test_entropy_decreases_as_facts_accumulate,
        test_expected_information_gain_nonneg,
        test_generate_questions_for_low_coverage,
        test_select_next_question_returns_a_question,
        test_already_asked_questions_are_filtered,
        test_hourly_budget_enforced,
        test_daily_budget_enforced,
        test_engagement_ledger_roundtrip,
        test_response_rate_per_domain,
        test_already_asked_normalization,
        test_curiosity_does_not_break_sprint1,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            results.append((t.__name__, FAIL, f"EXC {type(e).__name__}: {e}"))

    pass_count = sum(1 for _, s, _ in results if s == PASS)
    total = len(results)
    for name, status, detail in results:
        marker = "[OK]  " if status == PASS else "[XX]  "
        line = f"{marker}{name}"
        if detail:
            line += f"   - {detail}"
        print(line)
    print(f"\n{pass_count}/{total} Sprint 2 tests passed.")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
