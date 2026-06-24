"""Sprint 54 — v2 reflection layer: turn log + distiller + reflector.

The sixth and final foundational v2 layer. With reflection in place,
the system learns from its own conversations: every turn through
/api/v2/chat gets logged, the distiller proposes typed kstore facts
from the perception, and the reflector auto-applies the high-confidence
ones. The user's friend Alex doesn't get reinvented on every mention —
they get added to kstore on the first mention and recalled thereafter.

Tests cover:
  - TurnLog append + unprocessed iteration + mark_processed
  - Distiller emits correct proposals for each rule (1–5)
  - Reflector auto-applies high-confidence, defers low-confidence
  - Reflector is idempotent (processed turns skipped on re-run)
  - kstore grows correctly across a 3-turn conversation
  - /api/v2/chat hook persists a turn record per request
  - /api/v2/reflect endpoint runs reflection on demand
  - Correction turns produce no proposals
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

# Point v2 at temp DBs before importing anything that constructs runtime.
_TMP_KSTORE = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False)
_TMP_KSTORE.close()
_TMP_TURNLOG = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False)
_TMP_TURNLOG.close()
os.environ["LATTICED_V2_KSTORE_PATH"] = _TMP_KSTORE.name
os.environ["LATTICED_V2_TURNLOG_PATH"] = _TMP_TURNLOG.name

_TMP_V1 = tempfile.NamedTemporaryFile(suffix="_v1.db", delete=False)
_TMP_V1.close()
os.environ["LATTICED_V1_DB_PATH"] = _TMP_V1.name

# Load latticed.py the main module under a private name (avoids package vs
# file collision; same pattern as Sprint 53).
_spec = importlib.util.spec_from_file_location(
    "_latticed_main", REPO_ROOT / "latticed" / "latticed.py"
)
L = importlib.util.module_from_spec(_spec)
sys.modules["_latticed_main"] = L
_spec.loader.exec_module(L)

from latticed.v2.kstore import (  # noqa: E402
    KStore, Entity, EntityKind, RelationKind,
)
from latticed.v2.kstore.schema import USER_ENTITY_ID  # noqa: E402
from latticed.v2.perceive import perceive  # noqa: E402
from latticed.v2.reflect import (  # noqa: E402
    TurnLog, Reflector, distill_turn, Proposal, ProposalKind,
    HIGH_CONFIDENCE_THRESHOLD,
)
from latticed.v2.reflect.turn_log import perception_to_json  # noqa: E402
from latticed.v2.runtime import V2Runtime  # noqa: E402
from latticed.v2.strategies import StubNarratorBackend  # noqa: E402


results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


TZ = timezone.utc


def _fresh_store() -> KStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return KStore(Path(tmp.name))


def _fresh_log() -> TurnLog:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return TurnLog(Path(tmp.name))


def _log_turn(log: TurnLog, user_input: str, now: datetime,
              *, kstore=None, strategy_name="acknowledge_event",
              expected_shape="two_beat", final_text="A reply.",
              verdict="approve", used_fallback=False) -> int:
    """Helper: perceive a user input and append to the log."""
    p = perceive(user_input, now=now, kstore=kstore)
    return log.append_turn(
        user_input=user_input,
        perception_json=perception_to_json(p),
        strategy_name=strategy_name,
        expected_shape=expected_shape,
        final_text=final_text,
        verdict=verdict,
        used_fallback=used_fallback,
    )


# ── TurnLog basics ────────────────────────────────────────────────────────
def test_turn_log_append_returns_id():
    log = _fresh_log()
    tid = _log_turn(log, "I spoke with my dad",
                    now=datetime(2026, 6, 22, tzinfo=TZ))
    check("append_turn returns positive id", tid >= 1)
    check("total_count == 1", log.total_count() == 1)
    check("unprocessed_count == 1", log.unprocessed_count() == 1)
    log.close()


def test_turn_log_iteration_and_mark_processed():
    log = _fresh_log()
    t1 = _log_turn(log, "first turn", now=datetime(2026, 6, 22, tzinfo=TZ))
    t2 = _log_turn(log, "second turn", now=datetime(2026, 6, 22, tzinfo=TZ))
    unprocessed = log.list_unprocessed()
    check("two unprocessed turns",
          [t.id for t in unprocessed] == [t1, t2])
    log.mark_processed(t1)
    after = log.list_unprocessed()
    check("after mark_processed: only t2 remains",
          [t.id for t in after] == [t2])
    check("unprocessed_count == 1", log.unprocessed_count() == 1)
    check("total_count still 2", log.total_count() == 2)
    log.close()


def test_turn_log_get_turn_round_trip():
    log = _fresh_log()
    tid = _log_turn(log, "I went hiking", now=datetime(2026, 6, 22, tzinfo=TZ))
    turn = log.get_turn(tid)
    check("get_turn returns the record", turn is not None)
    check("turn carries user_input", turn.user_input == "I went hiking")
    check("turn carries perception JSON",
          "share_event" in turn.perception_json)
    check("turn starts unprocessed", turn.processed_at is None)
    log.close()


# ── Distiller rules ───────────────────────────────────────────────────────
def test_distiller_rule1_named_person_proposes_entity_and_relation():
    """Rule 1: 'my friend Alex' → CREATE_ENTITY Alex + ADD_RELATION USER FRIEND_OF Alex."""
    s = _fresh_store()
    log = _fresh_log()
    tid = _log_turn(log, "My friend Alex came by today",
                    now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    turn = log.get_turn(tid)
    props = distill_turn(turn, kstore=s)
    entity_props = [p for p in props if p.kind == ProposalKind.CREATE_ENTITY
                    and p.entity and p.entity.name == "Alex"]
    relation_props = [p for p in props if p.kind == ProposalKind.ADD_RELATION
                      and p.relation and p.relation.kind == RelationKind.FRIEND_OF]
    check("Alex entity proposed", len(entity_props) == 1)
    check("Alex entity high confidence (>= 0.85)",
          entity_props[0].confidence >= HIGH_CONFIDENCE_THRESHOLD)
    check("FRIEND_OF relation proposed",
          len(relation_props) == 1)
    log.close()
    s.close()


def test_distiller_rule2_unnamed_relation_lower_confidence():
    """Rule 2: 'my dad' (no name) → propose 'dad' PERSON at 0.7 (below auto-apply)."""
    s = _fresh_store()
    log = _fresh_log()
    tid = _log_turn(log, "I spoke with my dad today",
                    now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    turn = log.get_turn(tid)
    props = distill_turn(turn, kstore=s)
    dad_ent = [p for p in props if p.kind == ProposalKind.CREATE_ENTITY
               and p.entity and p.entity.name == "dad"]
    check("unnamed 'dad' entity proposed", len(dad_ent) == 1)
    check("unnamed 'dad' is LOW confidence (< threshold)",
          dad_ent[0].confidence < HIGH_CONFIDENCE_THRESHOLD)
    log.close()
    s.close()


def test_distiller_rule3_activity_in_share_event():
    s = _fresh_store()
    log = _fresh_log()
    tid = _log_turn(log, "I went hiking on Saturday",
                    now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    turn = log.get_turn(tid)
    props = distill_turn(turn, kstore=s)
    hiking_ent = [p for p in props if p.kind == ProposalKind.CREATE_ENTITY
                  and p.entity and p.entity.name == "hiking"]
    enjoys_rel = [p for p in props if p.kind == ProposalKind.ADD_RELATION
                  and p.relation and p.relation.kind == RelationKind.ENJOYS]
    check("hiking activity entity proposed", len(hiking_ent) == 1)
    check("ENJOYS relation proposed (low conf)",
          len(enjoys_rel) == 1 and enjoys_rel[0].confidence < HIGH_CONFIDENCE_THRESHOLD)
    log.close()
    s.close()


def test_distiller_rule4_records_event_for_share_with_anchor():
    s = _fresh_store()
    log = _fresh_log()
    tid = _log_turn(log, "Sunday was Father's Day I spoke with my dad",
                    now=datetime(2026, 6, 22, 12, 0, tzinfo=TZ), kstore=s)
    turn = log.get_turn(tid)
    props = distill_turn(turn, kstore=s)
    events = [p for p in props if p.kind == ProposalKind.RECORD_EVENT]
    check("event proposed for share_event with anchor", len(events) == 1)
    check("event is high-confidence (auto-applies)",
          events[0].confidence >= HIGH_CONFIDENCE_THRESHOLD)
    check("event when_start matches the temporal anchor (Father's Day 2026)",
          events[0].event.when_start.date().isoformat() == "2026-06-21")
    log.close()
    s.close()


def test_distiller_rule5_correction_emits_nothing():
    s = _fresh_store()
    log = _fresh_log()
    tid = _log_turn(log, "No, that's wrong — my dad's name is Greg",
                    now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    turn = log.get_turn(tid)
    props = distill_turn(turn, kstore=s)
    check("correction turn produces zero proposals", len(props) == 0)
    log.close()
    s.close()


def test_distiller_skips_existing_entity():
    """Idempotency: if Alex already exists in kstore, don't propose
    creating Alex again or adding the same relation."""
    s = _fresh_store()
    src = L
    from latticed.v2.kstore.schema import Source, SourceKind, Relation
    alex = s.add_entity(Entity(
        id=Entity.new_id(), kind=EntityKind.PERSON, name="Alex",
        source=Source(kind=SourceKind.USER_STATED),
    ))
    s.add_relation(Relation(
        id=Relation.new_id(), subject_id=USER_ENTITY_ID,
        kind=RelationKind.FRIEND_OF, object_id=alex.id,
        source=Source(kind=SourceKind.USER_STATED),
    ))
    log = _fresh_log()
    tid = _log_turn(log, "My friend Alex came by today",
                    now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    turn = log.get_turn(tid)
    props = distill_turn(turn, kstore=s)
    new_ents = [p for p in props if p.kind == ProposalKind.CREATE_ENTITY
                and p.entity and p.entity.name == "Alex"]
    check("Alex not re-proposed when it already exists",
          len(new_ents) == 0,
          f"got {[p.entity.name for p in new_ents]}")
    log.close()
    s.close()


# ── Reflector orchestration ───────────────────────────────────────────────
def test_reflector_auto_applies_high_conf_only():
    s = _fresh_store()
    log = _fresh_log()
    # Named friend (rule 1, high conf) + activity (rule 3, low conf)
    _log_turn(log, "My friend Alex and I went hiking",
              now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    refl = Reflector(kstore=s, turn_log=log)
    report = refl.reflect()
    check("processed 1 turn", report.turns_processed == 1)
    # Alex is high-conf: entity created + relation created
    alex = s.find_entity("Alex", kind=EntityKind.PERSON)
    check("Alex auto-created (high conf)", alex is not None)
    friends = s.recall_attribute(USER_ENTITY_ID, RelationKind.FRIEND_OF)
    check("FRIEND_OF Alex applied",
          any(e.name == "Alex" for e in friends))
    # Hiking entity is mid-conf (0.8) so it might auto-create; ENJOYS is 0.6
    # so it should NOT auto-apply.
    enjoys = s.recall_attribute(USER_ENTITY_ID, RelationKind.ENJOYS)
    check("ENJOYS hiking deferred (low confidence)",
          all(e.name != "hiking" for e in enjoys))
    check("low-conf proposal counted as deferred",
          report.proposals_deferred >= 1)
    log.close()
    s.close()


def test_reflector_is_idempotent():
    s = _fresh_store()
    log = _fresh_log()
    _log_turn(log, "My friend Alex came by today",
              now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    refl = Reflector(kstore=s, turn_log=log)
    r1 = refl.reflect()
    r2 = refl.reflect()
    check("first run processes 1 turn", r1.turns_processed == 1)
    check("second run processes 0 turns (idempotent)",
          r2.turns_processed == 0)
    check("Alex still single entity after 2 runs",
          len([e for e in s.list_entities(EntityKind.PERSON) if e.name == "Alex"]) == 1)
    log.close()
    s.close()


def test_reflector_handles_correction_turns_gracefully():
    s = _fresh_store()
    log = _fresh_log()
    _log_turn(log, "No, that's wrong — my brother is Greg",
              now=datetime(2026, 6, 22, tzinfo=TZ), kstore=s)
    refl = Reflector(kstore=s, turn_log=log)
    report = refl.reflect()
    check("correction turn marked processed",
          report.turns_processed == 1 and log.unprocessed_count() == 0)
    check("correction turn produces no kstore changes",
          report.entities_created == 0 and report.relations_created == 0)
    log.close()
    s.close()


def test_reflector_three_turn_conversation_grows_kstore():
    """Acceptance test: a small realistic conversation should leave the
    kstore with the people, activities, and events that were stated."""
    s = _fresh_store()
    log = _fresh_log()
    now = datetime(2026, 6, 22, 12, 0, tzinfo=TZ)
    _log_turn(log, "My friend Alex came by today", now=now, kstore=s)
    _log_turn(log, "Sunday was Father's Day I spoke with my dad",
              now=now, kstore=s)
    _log_turn(log, "I went hiking with my brother Greg on Saturday",
              now=now, kstore=s)
    refl = Reflector(kstore=s, turn_log=log)
    report = refl.reflect()
    check("processed 3 turns", report.turns_processed == 3)
    # Friends: Alex
    friends = [e.name for e in s.recall_attribute(USER_ENTITY_ID, RelationKind.FRIEND_OF)]
    check("Alex in FRIEND_OF after reflection", "Alex" in friends, f"got {friends}")
    # Family: Greg (named in turn 3); 'dad' from turn 2 is low-conf so deferred
    family = [e.name for e in s.recall_attribute(USER_ENTITY_ID, RelationKind.FAMILY_OF)]
    check("Greg in FAMILY_OF after reflection", "Greg" in family, f"got {family}")
    # Events: at least one event recorded (Father's Day, with date 2026-06-21)
    events = s.list_events_about([USER_ENTITY_ID])
    check("at least one event recorded", len(events) >= 1)
    fday_events = [e for e in events
                   if e.when_start.date().isoformat() == "2026-06-21"]
    check("Father's Day event recorded with correct date",
          len(fday_events) >= 1, f"events={[e.when_start.date() for e in events]}")
    log.close()
    s.close()


# ── Endpoint hooks ────────────────────────────────────────────────────────
def _drain_sse(text: str) -> list[dict]:
    out: list[dict] = []
    for blob in text.split("\n\n"):
        for line in blob.split("\n"):
            line = line.strip()
            if not line.startswith("data: "):
                continue
            try:
                out.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return out


def test_chat_endpoint_persists_turn_to_log():
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    # Fresh kstore + turn log paths so the test starts empty
    ks = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False)
    ks.close()
    tl = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False)
    tl.close()
    rt = V2Runtime(
        kstore_path=Path(ks.name),
        turn_log_path=Path(tl.name),
        backend=StubNarratorBackend({
            "reflection": "A real moment with your dad.",
            "question": "What stood out?",
        }),
    )
    L._v2_runtime = rt
    before = rt.turn_log.total_count()
    with TestClient(L.app) as client:
        r = client.get(
            "/api/v2/chat",
            params={"prompt": "I spoke with my dad"},
            headers={"x-api-key": L.ACTIVE_SECRET},
        )
    check("/api/v2/chat 200", r.status_code == 200)
    after = rt.turn_log.total_count()
    check("turn appended to log",
          after == before + 1, f"before={before}, after={after}")
    rt.close()
    L._v2_runtime = None


def test_reflect_endpoint_runs_reflector():
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    ks = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False)
    ks.close()
    tl = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False)
    tl.close()
    rt = V2Runtime(
        kstore_path=Path(ks.name),
        turn_log_path=Path(tl.name),
        backend=StubNarratorBackend({
            "reflection": "A real moment with your dad.",
            "question": "What stood out?",
        }),
    )
    L._v2_runtime = rt
    # Send a chat turn (creates a turn log row), then call /api/v2/reflect.
    with TestClient(L.app) as client:
        r = client.get(
            "/api/v2/chat",
            params={"prompt": "My friend Alex came by today"},
            headers={"x-api-key": L.ACTIVE_SECRET},
        )
        check("chat 200", r.status_code == 200)
        r2 = client.post(
            "/api/v2/reflect",
            headers={"x-api-key": L.ACTIVE_SECRET},
        )
    check("/api/v2/reflect 200", r2.status_code == 200)
    body = r2.json()
    check("reflect processed >= 1 turn", body.get("turns_processed", 0) >= 1)
    # The reflector should have created Alex (high-conf rule 1)
    alex = rt.kstore.find_entity("Alex", kind=EntityKind.PERSON)
    check("Alex auto-applied via endpoint", alex is not None)
    rt.close()
    L._v2_runtime = None


def test_stats_endpoint_surfaces_turn_counts():
    from fastapi.testclient import TestClient
    L._v2_runtime = None
    ks = tempfile.NamedTemporaryFile(suffix="_v2.db", delete=False)
    ks.close()
    tl = tempfile.NamedTemporaryFile(suffix="_v2t.db", delete=False)
    tl.close()
    rt = V2Runtime(
        kstore_path=Path(ks.name),
        turn_log_path=Path(tl.name),
        backend=StubNarratorBackend({
            "reflection": "Real moment with your dad.",
            "question": "What stood out?",
        }),
    )
    L._v2_runtime = rt
    with TestClient(L.app) as client:
        # one chat then stats
        client.get("/api/v2/chat",
                   params={"prompt": "I spoke with my dad"},
                   headers={"x-api-key": L.ACTIVE_SECRET})
        r = client.get("/api/v2/stats",
                       headers={"x-api-key": L.ACTIVE_SECRET})
    check("stats 200", r.status_code == 200)
    body = r.json()
    check("stats has turns.total >= 1",
          body.get("turns", {}).get("total", 0) >= 1)
    check("stats has turns.unprocessed",
          "unprocessed" in body.get("turns", {}))
    rt.close()
    L._v2_runtime = None


# ── Runner ────────────────────────────────────────────────────────────────
TESTS = [
    test_turn_log_append_returns_id,
    test_turn_log_iteration_and_mark_processed,
    test_turn_log_get_turn_round_trip,
    test_distiller_rule1_named_person_proposes_entity_and_relation,
    test_distiller_rule2_unnamed_relation_lower_confidence,
    test_distiller_rule3_activity_in_share_event,
    test_distiller_rule4_records_event_for_share_with_anchor,
    test_distiller_rule5_correction_emits_nothing,
    test_distiller_skips_existing_entity,
    test_reflector_auto_applies_high_conf_only,
    test_reflector_is_idempotent,
    test_reflector_handles_correction_turns_gracefully,
    test_reflector_three_turn_conversation_grows_kstore,
    test_chat_endpoint_persists_turn_to_log,
    test_reflect_endpoint_runs_reflector,
    test_stats_endpoint_surfaces_turn_counts,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            import traceback as tb
            results.append((fn.__name__, "FAIL",
                            f"raised {type(exc).__name__}: {exc}\n"
                            + tb.format_exc().splitlines()[-3]))
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 54 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
