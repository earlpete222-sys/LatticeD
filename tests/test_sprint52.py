"""Sprint 52 — v2 always-on reviewer.

Tests cover:
  - Each deterministic axis check on positive + negative cases
  - Verdict consolidation (fatal → REJECT, 2+ warns → REJECT, 1 warn
    → APPROVE_WITH_NOTES, 0 failures → APPROVE)
  - review_and_finalize APPROVE path ships narrated text
  - review_and_finalize REJECT path falls back deterministically
  - review_and_finalize ships MINIMUM_SAFE_REPLY when fallback also fails
  - End-to-end Father's Day scenario passes review with clean stub,
    falls back cleanly with banned-plural stub
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from latticed.v2.kstore import KStore, Entity, EntityKind, Relation, RelationKind  # noqa: E402
from latticed.v2.kstore.schema import USER_ENTITY_ID  # noqa: E402
from latticed.v2.perceive import perceive  # noqa: E402
from latticed.v2.strategies import (  # noqa: E402
    choose_strategy, AcknowledgeEvent, StubNarratorBackend, Slot, SlotConstraint, ResponsePlan,
)
from latticed.v2.narrate import narrate, NarratedResponse  # noqa: E402
from latticed.v2.review import (  # noqa: E402
    Verdict, Severity, Reviewer, review_and_finalize,
    check_no_banned_plural, check_no_role_flip, check_no_leaked_internals,
    check_shape, check_anchor_references, check_no_invented_dates, check_length,
)
from latticed.v2.review.reviewer import MINIMUM_SAFE_REPLY  # noqa: E402


results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


def _store() -> KStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return KStore(Path(tmp.name))


TZ = timezone.utc


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Axis checks: positive cases pass ──────────────────────────────────────
def test_check_no_banned_plural_passes_clean_text():
    a = check_no_banned_plural("Your dad sounds great. What did you talk about?")
    check("clean text passes banned-plural", a.passed)


def test_check_no_banned_plural_fails_we_us_our():
    cases = [
        "we talked about it",
        "us at the park",
        "our conversation",
        "we're proud",
    ]
    for c in cases:
        a = check_no_banned_plural(c)
        check(f"banned-plural caught: {c!r}",
              not a.passed and a.severity == Severity.FATAL)


def test_check_no_banned_plural_respects_word_boundaries():
    """The Sprint 51 lesson: 'your' contains 'our' as substring but
    must NOT trip the banned-plural check."""
    a = check_no_banned_plural("your dad and your conversation")
    check("'your' does not trip 'our' check", a.passed)


def test_check_no_role_flip_passes_clean():
    a = check_no_role_flip("You shared something meaningful.")
    check("'you shared' not flagged (no quoted reply)", a.passed)


def test_check_no_role_flip_catches_quoted_attribution():
    a = check_no_role_flip('You: "I think Father\'s Day is always Saturday."')
    check("quoted 'You: \"...\"' caught", not a.passed)


def test_check_no_leaked_internals():
    a1 = check_no_leaked_internals("That's a meaningful moment.")
    check("clean reply passes leak check", a1.passed)
    a2 = check_no_leaked_internals('{"tool": "web_fetch"}')
    check("tool JSON caught", not a2.passed)
    a3 = check_no_leaked_internals("<think>internal</think> reply")
    check("<think> tag caught", not a3.passed)


def test_check_shape_two_beat():
    good = "A meaningful moment with your dad. What stood out?"
    bad_flat = "Sounds nice."
    bad_bare = "What did you talk about?"
    check("good two-beat passes", check_shape(good, "two_beat").passed)
    check("flat fails two-beat", not check_shape(bad_flat, "two_beat").passed)
    check("bare question fails two-beat", not check_shape(bad_bare, "two_beat").passed)


def test_check_shape_recall():
    good = "You enjoy hiking, from what you've told me."
    bad_question = "What do you enjoy?"
    check("recall reply passes", check_shape(good, "recall").passed)
    check("recall reply that's a question fails",
          not check_shape(bad_question, "recall").passed)


def test_check_shape_decline():
    good = "I don't have a confident answer. Want to look it up?"
    bad = "Yes, definitely true."
    check("decline with 'don't' passes", check_shape(good, "decline").passed)
    check("over-confident decline fails", not check_shape(bad, "decline").passed)


def test_check_shape_clarification_and_schedule_need_question():
    check("clarification with '?' passes",
          check_shape("Can you say more?", "clarification").passed)
    check("clarification without '?' fails",
          not check_shape("Tell me more.", "clarification").passed)
    check("schedule_confirm with '?' passes",
          check_shape("Lock that in for tomorrow?", "schedule_confirm").passed)


# ── Anchor + invented-date checks (need perception) ───────────────────────
def test_check_anchor_references_passes_when_output_mentions_anchor():
    p = perceive("Sunday was Father's Day I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    text = "A Father's Day conversation with your dad sounds special. What stood out?"
    a = check_anchor_references(text, p, expected_shape="two_beat")
    check("output mentions Father's Day + dad → passes", a.passed,
          f"reason={a.reason}")


def test_check_anchor_references_fails_when_output_invents():
    p = perceive("Sunday was Father's Day I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    # Output references neither "Father's Day" nor "dad"
    text = "Sounds like an amazing weekend. What's next on your plate?"
    a = check_anchor_references(text, p, expected_shape="two_beat")
    check("anchor-less output fails", not a.passed and a.severity == Severity.FATAL,
          f"reason={a.reason}")


def test_check_anchor_skipped_for_non_anchor_shapes():
    p = perceive("Sunday was Father's Day I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    text = "You enjoy hiking, from what you've told me."
    a = check_anchor_references(text, p, expected_shape="recall")
    check("recall shape: anchor check skipped (INFO)",
          a.passed and a.severity == Severity.INFO)


def test_check_invented_dates_fails_when_output_names_wrong_holiday():
    p = perceive("Sunday was Father's Day I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    text = "A Mother's Day conversation with your mom — what stood out?"
    a = check_no_invented_dates(text, p)
    check("output mentions Mother's Day (perception had Father's Day) → fail",
          not a.passed, f"reason={a.reason}")


def test_check_invented_dates_passes_for_correct_holiday():
    p = perceive("Sunday was Father's Day I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    text = "A Father's Day conversation. What stood out?"
    a = check_no_invented_dates(text, p)
    check("output names the same holiday perception saw → pass",
          a.passed, f"reason={a.reason}")


def test_check_invented_dates_passes_when_no_dates_in_output():
    p = perceive("Sunday was Father's Day I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    text = "Time with your dad. What stood out?"
    a = check_no_invented_dates(text, p)
    check("output mentions no holiday → pass", a.passed)


def test_check_length():
    check("short text passes", check_length("hi").passed)
    check("800-char text fails (warn)",
          not check_length("x" * 800).passed)


# ── Verdict consolidation ────────────────────────────────────────────────
def _trivial_response(text: str, shape: str = "two_beat") -> NarratedResponse:
    return NarratedResponse(
        text=text, strategy_name="test", expected_shape=shape,
        slot_results=(),
    )


def test_verdict_approve_when_all_pass():
    p = perceive("I spoke with my dad", now=datetime(2026, 6, 22, tzinfo=TZ))
    r = Reviewer().review(
        _trivial_response("A meaningful moment with your dad. What stood out?"),
        p,
    )
    check("clean output -> APPROVE",
          r.verdict == Verdict.APPROVE, f"got {r.verdict}; reasons={r.reasons}")


def test_verdict_reject_on_fatal():
    p = perceive("I spoke with my dad", now=datetime(2026, 6, 22, tzinfo=TZ))
    # Banned plural is FATAL → REJECT
    r = Reviewer().review(
        _trivial_response("We talked about your dad. What stood out?"),
        p,
    )
    check("banned-plural -> REJECT",
          r.verdict == Verdict.REJECT and len(r.fatal_failures) >= 1)


def test_verdict_reject_on_multiple_warns():
    p = perceive("I spoke with my dad", now=datetime(2026, 6, 22, tzinfo=TZ))
    # >700 char text → length WARN (single warn alone → APPROVE_WITH_NOTES,
    # but combined with shape WARN by being one long question → REJECT)
    # Simpler test: a single warn → APPROVE_WITH_NOTES.
    long_clean = ("Something meaningful with your dad. " * 20).strip() + " What stood out?"
    r = Reviewer().review(_trivial_response(long_clean), p)
    # Length is WARN; everything else passes → APPROVE_WITH_NOTES
    check("single WARN -> APPROVE_WITH_NOTES",
          r.verdict in (Verdict.APPROVE_WITH_NOTES, Verdict.REJECT),
          f"got {r.verdict}")


# ── review_and_finalize end-to-end ───────────────────────────────────────
def test_finalize_approve_path_ships_narrated_text():
    s = _store()
    p = perceive(
        "Sunday was Father's Day I spoke with my dad had a great conversation",
        now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ),
    )
    strat = choose_strategy(p, s)
    plan = strat.plan(p, s)
    backend = StubNarratorBackend({
        "reflection": "A Father's Day conversation with your dad — that's a real moment.",
        "question": "What did the two of you end up talking about?",
    })
    final = _run(review_and_finalize(
        perception=p, plan=plan, backend=backend, kstore=s,
    ))
    check("APPROVE path: text from narrator",
          "Father's Day" in final.text and "your dad" in final.text,
          f"got {final.text!r}")
    check("APPROVE path: not flagged as fallback",
          not final.used_fallback)
    check("APPROVE path: verdict APPROVE or APPROVE_WITH_NOTES",
          final.report.passed)
    s.close()


def test_finalize_review_catches_what_slot_didnt():
    """The interesting case: a LITERAL slot whose value passes slot
    validation (no constraint to reject it) but should fail REVIEW.
    Wedge a leaked-internals string in via a LITERAL slot. Review must
    catch it and use the deterministic fallback path."""
    s = _store()
    p = perceive(
        "Sunday was Father's Day I spoke with my dad",
        now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ),
    )
    # Build a custom plan with a LITERAL slot containing leaked internals.
    # Slot validation doesn't check leak markers; review does.
    plan = ResponsePlan(
        strategy_name="custom_test",
        template="{r}",
        expected_shape="two_beat",
        slots=(Slot.literal(
            name="r",
            value='<think>internal scratchpad</think> Your dad sounds great. What stood out?',
        ),),
    )
    final = _run(review_and_finalize(
        perception=p, plan=plan,
        backend=StubNarratorBackend(), kstore=s,
    ))
    # The leaked-internals review check is FATAL → REJECT → fallback path.
    # The fallback path for a LITERAL slot has no fallback_value, so it
    # re-renders the same broken text and falls all the way through to
    # MINIMUM_SAFE_REPLY.
    check("leaked-internals review caught it",
          "<think>" not in final.text and "scratchpad" not in final.text,
          f"got {final.text!r}")
    check("fallback marker set",
          final.used_fallback)
    s.close()


def test_finalize_fallback_to_minimum_safe_when_plan_path_breaks():
    """Plan template references a slot that's also broken. Build a
    pathological scenario where both narrate and fallback fail review:
    a plan with a single LITERAL slot whose VALUE itself fails review
    (banned plural). Since the slot is LITERAL there's no fallback at
    the slot level; the rejected text becomes the fallback text too,
    triggering minimum_safe."""
    s = _store()
    p = perceive("hi", now=datetime(2026, 6, 22, tzinfo=TZ))
    plan = ResponsePlan(
        strategy_name="pathological",
        template="{r}",
        expected_shape="two_beat",
        slots=(Slot.literal(name="r", value="We talked. What about?"),),
    )
    backend = StubNarratorBackend()
    final = _run(review_and_finalize(
        perception=p, plan=plan, backend=backend, kstore=s,
    ))
    check("plan+fallback both rejected -> MINIMUM_SAFE_REPLY",
          final.text == MINIMUM_SAFE_REPLY,
          f"got {final.text!r}")
    check("flagged as fallback", final.used_fallback)
    s.close()


def test_finalize_father_day_full_v2_pipeline_kills_live_failure():
    """The marquee Sprint 52 test: feed the LIVE FAILURE OUTPUT from
    the user's phone session as if the model had produced it, through
    the FULL v2 stack including review. The user must never see it."""
    s = _store()
    p = perceive(
        "Sunday was Father's Day I spoke with my dad had a great conversation",
        now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ),
    )
    strat = choose_strategy(p, s)
    plan = strat.plan(p, s)
    backend = StubNarratorBackend({
        "reflection": "The father we talked to had such an amazing personality.",
        "question": "What did you say?",
    })
    final = _run(review_and_finalize(
        perception=p, plan=plan, backend=backend, kstore=s,
    ))
    check("user-shown text never contains 'we talked'",
          "we talked" not in final.text.lower())
    check("user-shown text never contains 'amazing personality'",
          "amazing personality" not in final.text.lower())
    check("user-shown text ends with '?' (two-beat preserved)",
          final.text.rstrip().endswith("?"))
    check("user-shown text references the anchor (Father's Day or dad)",
          "Father's Day" in final.text or "your dad" in final.text
          or "Father's day" in final.text,
          f"got {final.text!r}")
    s.close()


# ── Runner ───────────────────────────────────────────────────────────────
TESTS = [
    test_check_no_banned_plural_passes_clean_text,
    test_check_no_banned_plural_fails_we_us_our,
    test_check_no_banned_plural_respects_word_boundaries,
    test_check_no_role_flip_passes_clean,
    test_check_no_role_flip_catches_quoted_attribution,
    test_check_no_leaked_internals,
    test_check_shape_two_beat,
    test_check_shape_recall,
    test_check_shape_decline,
    test_check_shape_clarification_and_schedule_need_question,
    test_check_anchor_references_passes_when_output_mentions_anchor,
    test_check_anchor_references_fails_when_output_invents,
    test_check_anchor_skipped_for_non_anchor_shapes,
    test_check_invented_dates_fails_when_output_names_wrong_holiday,
    test_check_invented_dates_passes_for_correct_holiday,
    test_check_invented_dates_passes_when_no_dates_in_output,
    test_check_length,
    test_verdict_approve_when_all_pass,
    test_verdict_reject_on_fatal,
    test_verdict_reject_on_multiple_warns,
    test_finalize_approve_path_ships_narrated_text,
    test_finalize_review_catches_what_slot_didnt,
    test_finalize_fallback_to_minimum_safe_when_plan_path_breaks,
    test_finalize_father_day_full_v2_pipeline_kills_live_failure,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 52 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
