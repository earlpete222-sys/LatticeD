"""Sprint 49 — LatticeD v2: typed knowledge store (kstore) foundation.

Tests cover:
  - Schema invariants (immutability, validation, timezone-aware timestamps)
  - KStore round-trips for Entity, Event, Relation
  - Typed query API (find_entity, list_entities, list_events_about,
    recall_relations, recall_attribute) returns correct typed records
  - Supersede semantics (old record retained, new record live, queries
    skip superseded by default)
  - Singleton seeding (USER + SYSTEM entities exist after init)
  - v1 → v2 migration parses representative belief lines into typed
    relations, stashes the rest in legacy_beliefs, and is idempotent
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from latticed.v2.kstore import (  # noqa: E402
    Entity, EntityKind,
    Event, EventKind,
    Relation, RelationKind,
    Source, SourceKind,
    Mood,
    KStore,
)
from latticed.v2.kstore.schema import (  # noqa: E402
    USER_ENTITY_ID, SYSTEM_ENTITY_ID,
)
from latticed.v2.kstore.migrate import migrate_v1_belief_graph  # noqa: E402


results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


def _store() -> KStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return KStore(Path(tmp.name))


# ── Schema invariants ────────────────────────────────────────────────────────
def test_entity_frozen_and_validated():
    e = Entity(id=Entity.new_id(), kind=EntityKind.PERSON, name="Dad")
    try:
        e.name = "Mom"   # type: ignore[misc]
        check("Entity is frozen (immutable)", False, "mutation should raise")
    except Exception:
        check("Entity is frozen (immutable)", True)

    try:
        Entity(id="ent_x", kind=EntityKind.PERSON, name="")
        check("Entity rejects empty name", False)
    except ValueError:
        check("Entity rejects empty name", True)

    try:
        Entity(id="", kind=EntityKind.PERSON, name="x")
        check("Entity rejects empty id", False)
    except ValueError:
        check("Entity rejects empty id", True)


def test_event_validates_time_and_confidence():
    now = datetime.now(timezone.utc)
    # tz-naive when_start should be rejected
    try:
        Event(id=Event.new_id(), kind=EventKind.NOTE, when_start=datetime.now())
        check("Event rejects tz-naive when_start", False)
    except ValueError:
        check("Event rejects tz-naive when_start", True)

    # end before start should be rejected
    try:
        Event(id=Event.new_id(), kind=EventKind.NOTE,
              when_start=now, when_end=now - timedelta(hours=1))
        check("Event rejects when_end < when_start", False)
    except ValueError:
        check("Event rejects when_end < when_start", True)

    # confidence out of range
    try:
        Event(id=Event.new_id(), kind=EventKind.NOTE, when_start=now, confidence=1.5)
        check("Event rejects confidence > 1", False)
    except ValueError:
        check("Event rejects confidence > 1", True)


def test_relation_rejects_self_loop():
    try:
        Relation(id=Relation.new_id(), subject_id="x",
                 kind=RelationKind.KNOWS, object_id="x")
        check("Relation rejects subject == object", False)
    except ValueError:
        check("Relation rejects subject == object", True)


def test_source_requires_tool_name_for_tool_kind():
    try:
        Source(kind=SourceKind.TOOL)
        check("Source(TOOL) requires tool_name", False)
    except ValueError:
        check("Source(TOOL) requires tool_name", True)
    s = Source(kind=SourceKind.TOOL, tool_name="get_date")
    check("Source(TOOL, tool_name=...) ok", s.tool_name == "get_date")


# ── Singletons exist after init ────────────────────────────────────────────
def test_singletons_seeded():
    s = _store()
    user = s.get_entity(USER_ENTITY_ID)
    sysent = s.get_entity(SYSTEM_ENTITY_ID)
    check("USER singleton exists", user is not None and user.kind == EntityKind.USER)
    check("SYSTEM singleton exists", sysent is not None and sysent.kind == EntityKind.SYSTEM)
    s.close()


# ── Round-trips ────────────────────────────────────────────────────────────
def test_entity_round_trip():
    s = _store()
    src = Source(kind=SourceKind.USER_STATED, turn_ref="turn_42")
    e = Entity(
        id=Entity.new_id(), kind=EntityKind.PERSON, name="Dad",
        aliases=("Father", "Pops"),
        attributes=(("relation", "father"), ("nickname", "Pops")),
        source=src,
    )
    s.add_entity(e)
    got = s.get_entity(e.id)
    check("entity round-trips by id", got is not None and got.name == "Dad")
    check("entity preserves aliases", got.aliases == ("Father", "Pops"))
    check("entity preserves attributes",
          got.attributes == (("relation", "father"), ("nickname", "Pops")))
    check("entity preserves source", got.source.turn_ref == "turn_42")
    s.close()


def test_find_entity_by_name_and_alias():
    s = _store()
    s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.PLACE, name="Bellevue",
        aliases=("home", "BVU"),
    ))
    check("find by exact name (case insensitive)",
          s.find_entity("bellevue") is not None)
    check("find by alias", s.find_entity("home") is not None)
    check("not found returns None", s.find_entity("Spokane") is None)
    s.close()


def test_event_round_trip_with_participants_and_about():
    s = _store()
    dad = s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.PERSON, name="Dad"))
    fday = s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.HOLIDAY, name="Father's Day"))
    when = datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc)
    evt = Event(
        id=Event.new_id(), kind=EventKind.CONVERSATION,
        when_start=when,
        participants=(USER_ENTITY_ID, dad.id),
        about=(fday.id,),
        description="great conversation",
        mood=Mood.JOY,
        confidence=0.95,
    )
    s.add_event(evt)
    got = s.list_events_about([dad.id])
    check("event findable via participant", len(got) == 1 and got[0].id == evt.id)
    found_by_about = s.list_events_about([fday.id])
    check("event findable via about", len(found_by_about) == 1)
    check("event preserves mood", got[0].mood == Mood.JOY)
    check("event preserves description", got[0].description == "great conversation")
    s.close()


def test_relation_round_trip_and_recall():
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
    enjoyed = s.recall_attribute(USER_ENTITY_ID, RelationKind.ENJOYS)
    names = sorted(e.name for e in enjoyed)
    check("recall_attribute returns all entities of that relation",
          names == ["cooking", "hiking"])
    rels = s.recall_relations(USER_ENTITY_ID, kind=RelationKind.ENJOYS)
    check("recall_relations sorts by confidence desc",
          [r.object_id for r in rels] == [hiking.id, cooking.id])
    s.close()


# ── Supersede semantics ────────────────────────────────────────────────────
def test_supersede_marks_old_and_inserts_new():
    s = _store()
    old = Entity(id=Entity.new_id(), kind=EntityKind.PERSON, name="Old Name")
    s.add_entity(old)
    new = Entity(id=Entity.new_id(), kind=EntityKind.PERSON, name="New Name")
    s.supersede_entity(old.id, new)
    old_after = s.get_entity(old.id)
    new_after = s.find_entity("New Name")
    check("superseded record has timestamp",
          old_after is not None and old_after.superseded_at is not None)
    check("new record is live and findable",
          new_after is not None and new_after.superseded_at is None)
    # list_entities returns only live
    persons = [e.name for e in s.list_entities(EntityKind.PERSON)]
    check("list_entities skips superseded",
          "New Name" in persons and "Old Name" not in persons)
    s.close()


# ── stats reflects reality ─────────────────────────────────────────────────
def test_stats_counts():
    s = _store()
    base = s.stats()
    # Singletons make this 2 entities, 0 events, 0 relations after construction
    check("stats has live_entities key", "live_entities" in base)
    check("stats counts singletons",
          base["live_entities"] == 2 and base["live_events"] == 0
          and base["live_relations"] == 0)
    s.close()


# ── v1 → v2 migration ──────────────────────────────────────────────────────
def _make_v1_db(facts: list[tuple[str, float, float, str, str]]) -> Path:
    """Build a temporary v1-shaped SQLite with belief_graph rows."""
    tmp = tempfile.NamedTemporaryFile(suffix="_v1.db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute(
        "CREATE TABLE belief_graph ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT UNIQUE NOT NULL, "
        "confidence REAL, last_seen REAL, source TEXT, categories TEXT)"
    )
    for fact, conf, last, src, cats in facts:
        conn.execute(
            "INSERT INTO belief_graph (fact, confidence, last_seen, source, categories) "
            "VALUES (?,?,?,?,?)",
            (fact, conf, last, src, cats),
        )
    conn.commit()
    conn.close()
    return Path(tmp.name)


def test_migration_parses_known_patterns():
    s = _store()
    v1 = _make_v1_db([
        ("user enjoys hiking",                  0.9, 1.0, "chat", ""),
        ("user loves to go cooking",            0.8, 1.0, "chat", ""),
        ("user dislikes loud restaurants",      0.7, 1.0, "chat", ""),
        ("user lives in Bellevue",              0.95, 1.0, "chat", ""),
        ("user works at Boeing",                0.9, 1.0, "chat", ""),
        ("user's dad is Greg",                  0.95, 1.0, "chat", ""),
        ("user's friend is Alex",               0.85, 1.0, "chat", ""),
        # Unparseable -> legacy bucket
        ("the meeting went poorly yesterday",   0.5, 1.0, "chat", ""),
        ("something vague about preferences",   0.4, 1.0, "chat", ""),
    ])
    report = migrate_v1_belief_graph(v1_db_path=v1, store=s)

    check("rows_seen counts every belief", report.rows_seen == 9)
    check("typed_records_created == 7", report.typed_records_created == 7,
          f"got {report.typed_records_created}")
    check("legacy_stashed == 2", report.legacy_stashed == 2,
          f"got {report.legacy_stashed}")
    enjoyed = sorted(e.name for e in
                     s.recall_attribute(USER_ENTITY_ID, RelationKind.ENJOYS))
    check("ENJOYS includes hiking + cooking", enjoyed == ["cooking", "hiking"])
    disliked = [e.name for e in
                s.recall_attribute(USER_ENTITY_ID, RelationKind.DISLIKES)]
    check("DISLIKES includes 'loud restaurants'",
          "loud restaurants" in disliked, f"got {disliked}")
    lives = [e.name for e in
             s.recall_attribute(USER_ENTITY_ID, RelationKind.LIVES_IN)]
    check("LIVES_IN includes Bellevue", "Bellevue" in lives)
    family = [e.name for e in
              s.recall_attribute(USER_ENTITY_ID, RelationKind.FAMILY_OF)]
    check("FAMILY_OF includes Greg", "Greg" in family)
    friends = [e.name for e in
               s.recall_attribute(USER_ENTITY_ID, RelationKind.FRIEND_OF)]
    check("FRIEND_OF includes Alex", "Alex" in friends)
    check("legacy bucket holds the rest",
          s.legacy_belief_count() == 2)
    s.close()


def test_migration_is_idempotent():
    s = _store()
    v1 = _make_v1_db([
        ("user enjoys hiking",  0.9, 1.0, "chat", ""),
        ("user's dad is Greg",  0.9, 1.0, "chat", ""),
    ])
    r1 = migrate_v1_belief_graph(v1_db_path=v1, store=s)
    r2 = migrate_v1_belief_graph(v1_db_path=v1, store=s)
    enjoyed = s.recall_attribute(USER_ENTITY_ID, RelationKind.ENJOYS)
    family = s.recall_attribute(USER_ENTITY_ID, RelationKind.FAMILY_OF)
    check("idempotent: ENJOYS still single entry",
          len(enjoyed) == 1, f"got {len(enjoyed)}")
    check("idempotent: FAMILY_OF still single entry",
          len(family) == 1, f"got {len(family)}")
    check("first run created relations", r1.relations_created == 2)
    check("second run created zero relations",
          r2.relations_created == 0, f"got {r2.relations_created}")
    s.close()


def test_migration_missing_v1_db_is_noop():
    s = _store()
    fake = Path(tempfile.gettempdir()) / "no_such_v1.db"
    if fake.exists():
        fake.unlink()
    report = migrate_v1_belief_graph(v1_db_path=fake, store=s)
    check("missing v1 db: rows_seen == 0", report.rows_seen == 0)
    check("missing v1 db: nothing in store",
          s.stats()["live_relations"] == 0)
    s.close()


# ── Runner ────────────────────────────────────────────────────────────────
TESTS = [
    test_entity_frozen_and_validated,
    test_event_validates_time_and_confidence,
    test_relation_rejects_self_loop,
    test_source_requires_tool_name_for_tool_kind,
    test_singletons_seeded,
    test_entity_round_trip,
    test_find_entity_by_name_and_alias,
    test_event_round_trip_with_participants_and_about,
    test_relation_round_trip_and_recall,
    test_supersede_marks_old_and_inserts_new,
    test_stats_counts,
    test_migration_parses_known_patterns,
    test_migration_is_idempotent,
    test_migration_missing_v1_db_is_noop,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 49 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
