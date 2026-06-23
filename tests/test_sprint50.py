"""Sprint 50 — v2 perception layer: temporal + entities + intent + mood.

Tests cover:
  - Holiday computation across years (Father's Day 2026, 2027, 2028)
  - Temporal parsing: yesterday/today/tomorrow, day-of-week qualifiers,
    explicit month-day, ISO dates, slash dates
  - "Father's Day" never gets fabricated — perception resolves it to the
    correct date regardless of model behavior (kills the live failure)
  - Entity extraction with + without kstore; "my dad / my friend Alex"
    patterns; activity + place keyword scans; de-duplication
  - Intent classifier covers all 8 intent buckets
  - Mood tagger correct on joy/sad/anxious/tired/proud/neutral
  - perceive() integrates all four into a single Perception record
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from latticed.v2.kstore import (  # noqa: E402
    KStore, Entity, EntityKind, Source, SourceKind,
)
from latticed.v2.perceive import (  # noqa: E402
    holiday_date_for,
    resolve_temporal_refs,
    TemporalGrain,
    extract_mentions,
    classify_intent,
    Intent,
    detect_mood,
    perceive,
    Perception,
)
from latticed.v2.kstore.schema import Mood  # noqa: E402


results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


def _store() -> KStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return KStore(Path(tmp.name))


TZ = timezone.utc


# ── Holiday calendar ────────────────────────────────────────────────────────
def test_holiday_dates_known_years():
    # Father's Day in the US: 3rd Sunday of June
    check("Father's Day 2026 = Jun 21",
          holiday_date_for("Father's Day", 2026) == date(2026, 6, 21))
    check("Father's Day 2027 = Jun 20",
          holiday_date_for("Father's Day", 2027) == date(2027, 6, 20))
    # Mother's Day 2026: 2nd Sunday of May = May 10
    check("Mother's Day 2026 = May 10",
          holiday_date_for("Mother's Day", 2026) == date(2026, 5, 10))
    # Thanksgiving 2026: 4th Thursday of November = Nov 26
    check("Thanksgiving 2026 = Nov 26",
          holiday_date_for("Thanksgiving", 2026) == date(2026, 11, 26))
    # Memorial Day 2026: last Monday of May = May 25
    check("Memorial Day 2026 = May 25",
          holiday_date_for("Memorial Day", 2026) == date(2026, 5, 25))
    # Independence Day = July 4 every year
    check("Independence Day always Jul 4",
          holiday_date_for("Independence Day", 2026) == date(2026, 7, 4))
    # Easter 2026 = April 5 (verified externally)
    check("Easter 2026 = Apr 5",
          holiday_date_for("Easter", 2026) == date(2026, 4, 5))


def test_holiday_aliases():
    check("'fathers day' → Father's Day",
          holiday_date_for("fathers day", 2026) == date(2026, 6, 21))
    check("'fourth of july' → Independence Day",
          holiday_date_for("fourth of july", 2026) == date(2026, 7, 4))
    check("'thanksgiving' case-insensitive",
          holiday_date_for("THANKSGIVING", 2026) == date(2026, 11, 26))
    check("unknown holiday returns None",
          holiday_date_for("Festivus", 2026) is None)


# ── Temporal parsing ────────────────────────────────────────────────────────
def test_temporal_resolves_fathers_day_no_fabrication():
    """The live failure: model fabricated 'first Saturday of June' for
    Father's Day. Perception resolves it before the model is ever called."""
    now = datetime(2026, 6, 22, 12, 0, tzinfo=TZ)
    refs = resolve_temporal_refs(
        "Sunday was Father's Day I spoke with my dad", now
    )
    fday = [r for r in refs if "father" in r.text.lower()]
    check("Father's Day resolved exactly", len(fday) == 1
          and fday[0].when.date() == date(2026, 6, 21),
          f"got {[r.when.date() for r in fday]}")


def test_temporal_yesterday_today_tomorrow():
    now = datetime(2026, 6, 22, 15, 0, tzinfo=TZ)
    refs = resolve_temporal_refs(
        "Yesterday I called mom, today I'm working, tomorrow I rest",
        now,
    )
    texts = {r.text.lower(): r.when.date() for r in refs}
    check("yesterday → 2026-06-21",
          texts.get("yesterday") == date(2026, 6, 21), f"got {texts}")
    check("today → 2026-06-22",
          texts.get("today") == date(2026, 6, 22), f"got {texts}")
    check("tomorrow → 2026-06-23",
          texts.get("tomorrow") == date(2026, 6, 23), f"got {texts}")


def test_temporal_day_of_week():
    now = datetime(2026, 6, 22, 12, 0, tzinfo=TZ)   # Monday
    refs = resolve_temporal_refs("on last Friday we went hiking", now)
    fri = [r for r in refs if "friday" in r.text.lower()]
    check("'last Friday' = 2026-06-19",
          len(fri) == 1 and fri[0].when.date() == date(2026, 6, 19),
          f"got {[r.when.date() for r in fri]}")


def test_temporal_explicit_dates():
    now = datetime(2026, 6, 22, 12, 0, tzinfo=TZ)
    refs = resolve_temporal_refs(
        "Let's meet on August 12 or 2026-09-01 or 12/25/2026",
        now,
    )
    dates = {r.text: r.when.date() for r in refs}
    check("'August 12' resolves to Aug 12",
          any(d == date(2026, 8, 12) for d in dates.values()), f"got {dates}")
    check("ISO 2026-09-01 resolves exactly",
          any(d == date(2026, 9, 1) for d in dates.values()), f"got {dates}")
    check("12/25/2026 resolves exactly",
          any(d == date(2026, 12, 25) for d in dates.values()), f"got {dates}")


def test_temporal_requires_tz_aware_now():
    try:
        resolve_temporal_refs("today", datetime.now())
        check("rejects tz-naive now", False)
    except ValueError:
        check("rejects tz-naive now", True)


# ── Entity extraction ──────────────────────────────────────────────────────
def test_entities_extracts_my_relation_with_proper_name():
    mentions = extract_mentions("My friend Alex came by today.")
    by_canonical = {m.canonical: m for m in mentions}
    check("'my friend Alex' → Alex as PERSON",
          "Alex" in by_canonical and by_canonical["Alex"].relation_hint == "friend",
          f"got {[(m.canonical, m.relation_hint) for m in mentions]}")


def test_entities_extracts_my_dad_without_name():
    mentions = extract_mentions("I spoke with my dad")
    persons = [m for m in mentions if m.relation_hint == "dad"]
    check("'my dad' → dad PERSON mention",
          len(persons) == 1 and persons[0].canonical == "dad",
          f"got {[(m.canonical, m.relation_hint) for m in mentions]}")


def test_entities_picks_up_activity_keywords():
    mentions = extract_mentions("I went hiking on Saturday morning")
    activities = [m for m in mentions if m.canonical == "hiking"]
    check("'hiking' verb form → hiking ACTIVITY",
          len(activities) == 1 and activities[0].kind == EntityKind.ACTIVITY,
          f"got {[(m.canonical, m.kind.value) for m in mentions]}")


def test_entities_picks_up_common_place_nouns():
    mentions = extract_mentions("Spent the morning at the park.")
    parks = [m for m in mentions if m.canonical == "park"]
    check("'at the park' → park PLACE", len(parks) == 1
          and parks[0].kind == EntityKind.PLACE)


def test_entities_kstore_lookup_high_confidence():
    s = _store()
    src = Source(kind=SourceKind.USER_STATED)
    s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.PERSON, name="Greg",
        aliases=("Gregory", "Pops"), source=src,
    ))
    mentions = extract_mentions("Pops dropped by today", kstore=s)
    greg = [m for m in mentions if m.canonical == "Greg"]
    check("'Pops' alias → Greg entity_id at conf 1.0",
          len(greg) == 1 and greg[0].entity_id is not None
          and greg[0].confidence == 1.0,
          f"got {[(m.canonical, m.entity_id, m.confidence) for m in mentions]}")
    s.close()


def test_entities_dedupes_overlapping_spans():
    s = _store()
    src = Source(kind=SourceKind.USER_STATED)
    s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.ACTIVITY, name="hiking",
        source=src,
    ))
    mentions = extract_mentions("I went hiking", kstore=s)
    hiking = [m for m in mentions if m.canonical == "hiking"]
    check("kstore + lexicon overlap → one mention only",
          len(hiking) == 1, f"got {len(hiking)} hiking mentions")
    check("kstore wins (high conf)",
          hiking[0].confidence == 1.0 and hiking[0].entity_id is not None)
    s.close()


# ── Intent classification ──────────────────────────────────────────────────
def test_intent_all_buckets_hit():
    cases = [
        ("I spoke with my dad today",                  Intent.SHARE_EVENT),
        ("What do I like to do for fun?",               Intent.RECALL_QUERY),
        ("When is Thanksgiving?",                       Intent.FACTUAL_QUESTION),
        ("Remind me to call mom tomorrow",              Intent.SCHEDULE),
        ("hi",                                          Intent.CHITCHAT),
        ("How are you today?",                          Intent.CHITCHAT),
        ("No, that's wrong — my dad's name is Greg",    Intent.CORRECTION),
        ("What do you know about me?",                  Intent.META),
        ("What should I do about this?",                Intent.REQUEST_ADVICE),
    ]
    for text, want in cases:
        got = classify_intent(text).intent
        check(f"intent({text!r}) = {want.value}",
              got == want, f"got {got.value}")


def test_intent_correction_beats_other_patterns():
    # Correction phrase combined with first-person share — correction should win
    got = classify_intent("Actually, my dad's name is Greg, not Gary.")
    check("correction beats share_event", got.intent == Intent.CORRECTION)


def test_intent_meta_beats_factual():
    got = classify_intent("What do you know about me?")
    check("'what do you know' → META, not FACTUAL",
          got.intent == Intent.META)


def test_intent_bare_question_low_confidence():
    got = classify_intent("Why?")
    check("bare 'Why?' → FACTUAL at low conf",
          got.intent == Intent.FACTUAL_QUESTION and got.confidence <= 0.6)


# ── Mood tagging ───────────────────────────────────────────────────────────
def test_mood_basic_signals():
    cases = [
        ("Had an amazing day today!",         Mood.JOY),
        ("I'm feeling really anxious",        Mood.ANXIOUS),
        ("I'm so frustrated with this",       Mood.FRUSTRATED),
        ("Feeling down today",                Mood.SAD),
        ("I'm exhausted",                     Mood.TIRED),
        ("Proud of what we accomplished",     Mood.PRIDE),
        ("It's been a peaceful morning",      Mood.CALM),
        ("Just curious about this",           Mood.CURIOUS),
    ]
    for text, want in cases:
        got = detect_mood(text)
        check(f"mood({text!r}) = {want.value}",
              got == want, f"got {got.value if got else 'None'}")


def test_mood_returns_none_when_unmarked():
    check("'I went to the store' → no mood signal",
          detect_mood("I went to the store") is None)


# ── perceive() integration ─────────────────────────────────────────────────
def test_perceive_father_day_full_pipeline():
    """The full live-failure scenario, end-to-end through perception.
    Verifies: Father's Day resolved correctly, 'my dad' extracted as
    PERSON, intent=SHARE_EVENT, mood=JOY (from 'great conversation').
    None of these depend on the 1.5B model behaving well."""
    now = datetime(2026, 6, 22, 12, 0, tzinfo=TZ)
    p = perceive(
        "Sunday was Father's Day I spoke with my dad had a great conversation",
        now=now,
    )
    fday = [r for r in p.temporal_refs if "father" in r.text.lower()]
    check("perceive: Father's Day → 2026-06-21",
          len(fday) == 1 and fday[0].when.date() == date(2026, 6, 21))
    dad = [m for m in p.mentions if m.relation_hint == "dad"]
    check("perceive: 'my dad' extracted", len(dad) == 1)
    check("perceive: intent = SHARE_EVENT", p.intent == Intent.SHARE_EVENT)
    check("perceive: mood = JOY", p.mood == Mood.JOY,
          f"got {p.mood.value if p.mood else 'None'}")


def test_perceive_specific_detail_helper():
    now = datetime(2026, 6, 22, 12, 0, tzinfo=TZ)
    p = perceive("My friend Alex came by today", now=now)
    check("specific_detail returns the highest-conf mention",
          p.specific_detail == "Alex", f"got {p.specific_detail}")


def test_perceive_trace_summarizes_pipeline():
    now = datetime(2026, 6, 22, 12, 0, tzinfo=TZ)
    p = perceive("Today I'm tired", now=now)
    joined = " ".join(p.trace)
    check("trace mentions intent", "intent:share_event" in joined
          or "intent:other" in joined, f"got {p.trace}")
    check("trace mentions mood", "mood:tired" in joined)
    check("trace mentions temporal count",
          "temporal_refs:" in joined)


def test_perceive_requires_tz_aware_now():
    try:
        perceive("hi", now=datetime.now())
        check("perceive rejects tz-naive now", False)
    except ValueError:
        check("perceive rejects tz-naive now", True)


# ── Runner ────────────────────────────────────────────────────────────────
TESTS = [
    test_holiday_dates_known_years,
    test_holiday_aliases,
    test_temporal_resolves_fathers_day_no_fabrication,
    test_temporal_yesterday_today_tomorrow,
    test_temporal_day_of_week,
    test_temporal_explicit_dates,
    test_temporal_requires_tz_aware_now,
    test_entities_extracts_my_relation_with_proper_name,
    test_entities_extracts_my_dad_without_name,
    test_entities_picks_up_activity_keywords,
    test_entities_picks_up_common_place_nouns,
    test_entities_kstore_lookup_high_confidence,
    test_entities_dedupes_overlapping_spans,
    test_intent_all_buckets_hit,
    test_intent_correction_beats_other_patterns,
    test_intent_meta_beats_factual,
    test_intent_bare_question_low_confidence,
    test_mood_basic_signals,
    test_mood_returns_none_when_unmarked,
    test_perceive_father_day_full_pipeline,
    test_perceive_specific_detail_helper,
    test_perceive_trace_summarizes_pipeline,
    test_perceive_requires_tz_aware_now,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 50 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
