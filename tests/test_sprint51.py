"""Sprint 51 — v2 strategies + narration.

End-to-end tests of the third v2 layer: perception → router →
strategy.plan() → narrate() → final text. With a StubNarratorBackend
none of these tests need a live model — they verify that the SYSTEM
produces correct shape regardless of what the model would emit.

The marquee test (test_father_day_full_pipeline_deterministic) runs
the live failure prompt through the full v2 stack with a clean stub
backend and confirms:
  - The right strategy is chosen (AcknowledgeEvent)
  - The reflection slot accepts a clean candidate
  - The question slot accepts a clean candidate
  - Final text is a clean two-beat with no fabrication
  - SlotConstraint would have caught the banned "we talked" /
    "amazing personality" output if the model had emitted it
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

from latticed.v2.kstore import (  # noqa: E402
    KStore, Entity, EntityKind, Relation, RelationKind,
    Source, SourceKind,
)
from latticed.v2.kstore.schema import USER_ENTITY_ID  # noqa: E402
from latticed.v2.perceive import perceive, Intent  # noqa: E402
from latticed.v2.strategies import (  # noqa: E402
    choose_strategy,
    AcknowledgeEvent, RecallFromHistory, DeclineUnknown,
    AskClarification, ScheduleEvent,
    StubNarratorBackend, SlotConstraint, Slot, ResponsePlan,
)
from latticed.v2.narrate import narrate  # noqa: E402


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


# ── SlotConstraint validation logic ────────────────────────────────────────
def test_constraint_catches_banned_plurals():
    c = SlotConstraint(no_banned_plurals=True)
    check("'we talked' triggers banned_plural",
          c.validate("we talked about your dad") == "banned_plural")
    check("'your dad' passes",
          c.validate("your dad sounds great") is None)


def test_constraint_max_words():
    c = SlotConstraint(max_words=5)
    check("6-word string fails",
          c.validate("one two three four five six").startswith("too_long"))
    check("5-word string passes",
          c.validate("one two three four five") is None)


def test_constraint_must_end_with_question():
    c = SlotConstraint(must_end_with="?")
    check("ends with '?' passes", c.validate("How are you?") is None)
    check("ends with '.' fails",
          c.validate("That's nice.") == "missing_end('?')")


def test_constraint_must_contain():
    c = SlotConstraint(must_contain=("dad", "father"))
    check("contains 'dad' passes",
          c.validate("Your dad sounds great") is None)
    check("contains neither fails",
          c.validate("Your friend sounds great")
          == "missing_required_phrase")


def test_constraint_must_not_contain():
    c = SlotConstraint(must_not_contain=("amazing personality",))
    check("phrase forbidden -> failure",
          c.validate("had such an amazing personality")
          == "contains('amazing personality')")


def test_constraint_empty_fails():
    check("empty string fails",
          SlotConstraint().validate("") == "empty")
    check("whitespace fails",
          SlotConstraint().validate("   \n") == "empty")


# ── Slot construction guards ──────────────────────────────────────────────
def test_model_slot_requires_fallback():
    try:
        Slot.model(name="x", prompt="...", fallback_value="")
        check("Slot.model requires fallback_value", False)
    except ValueError:
        check("Slot.model requires fallback_value", True)


def test_choice_slot_requires_options():
    try:
        Slot.choice(name="x", options=())
        check("Slot.choice requires options", False)
    except ValueError:
        check("Slot.choice requires options", True)


# ── Router picks the right strategy ───────────────────────────────────────
def test_router_picks_acknowledge_for_share():
    s = _store()
    p = perceive(
        "Sunday was Father's Day I spoke with my dad had a great conversation",
        now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ),
    )
    strat = choose_strategy(p, s)
    check("share_event -> AcknowledgeEvent",
          isinstance(strat, AcknowledgeEvent),
          f"got {type(strat).__name__}")
    s.close()


def test_router_picks_recall_when_kstore_has_answer():
    s = _store()
    hiking = s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.ACTIVITY, name="hiking"))
    s.add_relation(Relation(
        id=Relation.new_id(), subject_id=USER_ENTITY_ID,
        kind=RelationKind.ENJOYS, object_id=hiking.id,
    ))
    p = perceive("What do I like to do?",
                 now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ))
    strat = choose_strategy(p, s)
    check("recall with stored answer -> RecallFromHistory",
          isinstance(strat, RecallFromHistory),
          f"got {type(strat).__name__}")
    s.close()


def test_router_falls_through_to_clarification_for_empty_recall():
    s = _store()    # nothing stored
    p = perceive("What do I like to do?",
                 now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ))
    strat = choose_strategy(p, s)
    check("recall with empty store -> AskClarification",
          isinstance(strat, AskClarification),
          f"got {type(strat).__name__}")
    s.close()


def test_router_picks_schedule_for_reminder():
    s = _store()
    p = perceive("Remind me to call mom tomorrow",
                 now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ))
    strat = choose_strategy(p, s)
    check("schedule intent -> ScheduleEvent",
          isinstance(strat, ScheduleEvent),
          f"got {type(strat).__name__}")
    s.close()


def test_router_always_returns_something():
    s = _store()
    # Pathological: empty string is OTHER intent
    p = perceive("",
                 now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ)) \
        if False else None
    # Build a perception manually for the edge case
    from latticed.v2.perceive.perception import Perception
    p = Perception(
        user_input="???",
        now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ),
        intent=Intent.OTHER,
        intent_confidence=0.3,
        mood=None,
        mentions=(),
        temporal_refs=(),
    )
    strat = choose_strategy(p, s)
    check("router always returns a strategy",
          strat is not None and hasattr(strat, "name"))
    s.close()


# ── Narrator: stub backend behavior ───────────────────────────────────────
def test_narrate_literal_slot_passes_through():
    s = _store()
    p = perceive("hi", now=datetime(2026, 6, 22, tzinfo=TZ))
    plan = ResponsePlan(
        strategy_name="test",
        template="{greeting}",
        slots=(Slot.literal(name="greeting", value="Hello there!"),),
    )
    result = _run(narrate(plan, backend=StubNarratorBackend(),
                          kstore=s, perception=p))
    check("literal slot passes through",
          result.text == "Hello there!")
    s.close()


def test_narrate_choice_slot_is_deterministic():
    s = _store()
    p = perceive("hi there", now=datetime(2026, 6, 22, tzinfo=TZ))
    plan = ResponsePlan(
        strategy_name="test",
        template="{g}",
        slots=(Slot.choice(name="g", options=("A", "B", "C")),),
    )
    r1 = _run(narrate(plan, backend=StubNarratorBackend(),
                      kstore=s, perception=p))
    r2 = _run(narrate(plan, backend=StubNarratorBackend(),
                      kstore=s, perception=p))
    check("choice slot stable for same input",
          r1.text == r2.text, f"{r1.text!r} vs {r2.text!r}")
    check("choice slot picks from options",
          r1.text in ("A", "B", "C"))
    s.close()


def test_narrate_model_slot_validates_and_passes():
    s = _store()
    p = perceive("I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    plan = ResponsePlan(
        strategy_name="test",
        template="{r}",
        slots=(Slot.model(
            name="r",
            prompt="say something",
            fallback_value="A moment to keep.",
            constraint=SlotConstraint(no_banned_plurals=True, max_words=10),
        ),),
    )
    backend = StubNarratorBackend({"r": "Your dad sounds great."})
    result = _run(narrate(plan, backend=backend, kstore=s, perception=p))
    check("clean model slot passes",
          result.text == "Your dad sounds great.")
    check("backend called once",
          len(backend.calls) == 1)
    s.close()


def test_narrate_model_slot_retries_then_falls_back():
    """If model slot fails validation twice, the fallback ships."""
    s = _store()
    p = perceive("I spoke with my dad",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    plan = ResponsePlan(
        strategy_name="test",
        template="{r}",
        slots=(Slot.model(
            name="r",
            prompt="say something",
            fallback_value="A moment to keep.",
            constraint=SlotConstraint(no_banned_plurals=True),
        ),),
    )
    # Stub always returns banned plural -- validation fails both times
    backend = StubNarratorBackend({"r": "we talked about it"})
    result = _run(narrate(plan, backend=backend, kstore=s, perception=p))
    check("fallback shipped when both attempts fail",
          result.text == "A moment to keep.")
    check("slot result records both failures",
          len(result.slot_results[0].validation_failures) == 2
          and result.slot_results[0].used_fallback)
    check("backend called twice",
          len(backend.calls) == 2)
    s.close()


# ── Strategy-level outputs end-to-end ─────────────────────────────────────
def test_recall_strategy_produces_deterministic_text():
    s = _store()
    hiking = s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.ACTIVITY, name="hiking"))
    cooking = s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.ACTIVITY, name="cooking"))
    s.add_relation(Relation(
        id=Relation.new_id(), subject_id=USER_ENTITY_ID,
        kind=RelationKind.ENJOYS, object_id=hiking.id, confidence=0.9,
    ))
    s.add_relation(Relation(
        id=Relation.new_id(), subject_id=USER_ENTITY_ID,
        kind=RelationKind.ENJOYS, object_id=cooking.id, confidence=0.7,
    ))
    p = perceive("What do I like to do?",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    strat = choose_strategy(p, s)
    plan = strat.plan(p, s)
    result = _run(narrate(plan, backend=StubNarratorBackend(),
                          kstore=s, perception=p))
    check("recall reply mentions hiking + cooking",
          "hiking" in result.text and "cooking" in result.text,
          f"got {result.text!r}")
    check("recall uses 'You enjoy'",
          "You enjoy" in result.text)
    check("recall used no model calls (deterministic)",
          all(r.kind.value != "model" for r in result.slot_results))
    s.close()


def test_clarification_for_empty_recall_is_honest():
    s = _store()
    p = perceive("What do I like to do?",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    strat = choose_strategy(p, s)
    plan = strat.plan(p, s)
    result = _run(narrate(plan, backend=StubNarratorBackend(),
                          kstore=s, perception=p))
    check("empty recall -> clarification mentions 'don't have'",
          "don't have" in result.text, f"got {result.text!r}")
    check("empty recall -> asks what to remember",
          "want me to remember" in result.text.lower())
    s.close()


def test_schedule_strategy_confirms_when_when_present():
    s = _store()
    p = perceive("Remind me to call mom tomorrow",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    strat = choose_strategy(p, s)
    plan = strat.plan(p, s)
    result = _run(narrate(plan, backend=StubNarratorBackend(),
                          kstore=s, perception=p))
    check("schedule includes the what",
          "call mom" in result.text, f"got {result.text!r}")
    check("schedule includes the when",
          "tomorrow" in result.text)
    check("schedule asks to confirm",
          "lock that in" in result.text or "confirm" in result.text.lower())
    s.close()


def test_schedule_strategy_asks_for_time_when_missing():
    s = _store()
    p = perceive("Remind me to call mom",
                 now=datetime(2026, 6, 22, tzinfo=TZ))
    strat = choose_strategy(p, s)
    plan = strat.plan(p, s)
    result = _run(narrate(plan, backend=StubNarratorBackend(),
                          kstore=s, perception=p))
    check("schedule without when asks for it",
          "when" in result.text.lower() and "?" in result.text,
          f"got {result.text!r}")
    s.close()


def test_decline_unknown_is_always_safe():
    s = _store()
    from latticed.v2.perceive.perception import Perception
    p = Perception(
        user_input="????",
        now=datetime(2026, 6, 22, tzinfo=TZ),
        intent=Intent.OTHER,
        intent_confidence=0.3,
        mood=None,
        mentions=(),
        temporal_refs=(),
    )
    # Force decline path
    strat = DeclineUnknown()
    plan = strat.plan(p, s)
    result = _run(narrate(plan, backend=StubNarratorBackend(),
                          kstore=s, perception=p))
    check("decline reply non-empty", bool(result.text.strip()))
    check("decline says 'don't' or 'making' (honesty)",
          "don't" in result.text.lower()
          or "making" in result.text.lower())
    s.close()


# ── THE MARQUEE TEST: live Father's Day failure killed deterministically ──
def test_father_day_full_pipeline_clean_output():
    """The full live failure scenario through the v2 stack with a stub
    backend that returns CLEAN candidates. Verifies the system produces
    a clean two-beat reply end-to-end."""
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
    result = _run(narrate(plan, backend=backend, kstore=s, perception=p))

    check("strategy = AcknowledgeEvent", plan.strategy_name == "acknowledge_event")
    check("expected_shape = two_beat", result.expected_shape == "two_beat")
    check("output contains 'your dad' (not 'we talked')",
          "your dad" in result.text and "we talked" not in result.text.lower(),
          f"got {result.text!r}")
    check("output contains 'Father's Day' temporal anchor",
          "Father's Day" in result.text)
    check("output ends with '?' (question beat)",
          result.text.rstrip().endswith("?"))
    check("output has both beats (declarative + question)",
          result.text.count(".") >= 1 or "—" in result.text)
    check("no fallback was used (clean stub)",
          not result.used_any_fallback)
    s.close()


def test_father_day_pipeline_falls_back_on_banned_plural_model():
    """Same scenario but stub returns BANNED 'we talked' for reflection
    -- system must catch via constraint and ship the fallback (still
    a clean two-beat) rather than the broken text."""
    s = _store()
    p = perceive(
        "Sunday was Father's Day I spoke with my dad had a great conversation",
        now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ),
    )
    strat = choose_strategy(p, s)
    plan = strat.plan(p, s)
    # Stub returns banned plural for reflection. Question is clean.
    backend = StubNarratorBackend({
        "reflection": "The father we talked to had such an amazing personality.",
        "question": "What did the two of you end up talking about?",
    })
    result = _run(narrate(plan, backend=backend, kstore=s, perception=p))

    check("banned-plural reflection never reaches output",
          "we talked" not in result.text.lower(),
          f"got {result.text!r}")
    check("amazing personality never reaches output",
          "amazing personality" not in result.text.lower(),
          f"got {result.text!r}")
    check("fallback used for reflection slot",
          result.slot_results[0].used_fallback)
    check("output still ends with '?'",
          result.text.rstrip().endswith("?"))


# ── Runner ────────────────────────────────────────────────────────────────
TESTS = [
    test_constraint_catches_banned_plurals,
    test_constraint_max_words,
    test_constraint_must_end_with_question,
    test_constraint_must_contain,
    test_constraint_must_not_contain,
    test_constraint_empty_fails,
    test_model_slot_requires_fallback,
    test_choice_slot_requires_options,
    test_router_picks_acknowledge_for_share,
    test_router_picks_recall_when_kstore_has_answer,
    test_router_falls_through_to_clarification_for_empty_recall,
    test_router_picks_schedule_for_reminder,
    test_router_always_returns_something,
    test_narrate_literal_slot_passes_through,
    test_narrate_choice_slot_is_deterministic,
    test_narrate_model_slot_validates_and_passes,
    test_narrate_model_slot_retries_then_falls_back,
    test_recall_strategy_produces_deterministic_text,
    test_clarification_for_empty_recall_is_honest,
    test_schedule_strategy_confirms_when_when_present,
    test_schedule_strategy_asks_for_time_when_missing,
    test_decline_unknown_is_always_safe,
    test_father_day_full_pipeline_clean_output,
    test_father_day_pipeline_falls_back_on_banned_plural_model,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 51 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
