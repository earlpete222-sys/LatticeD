"""Distiller — turn → typed kstore proposals.

Reads ONE turn's perception (deserialized from the turn log) and emits
typed Proposals: new Entities, new Relations, new Events. Each proposal
carries a confidence score; the reflector decides whether to auto-apply.

This module is deterministic — same input always yields the same
proposals. The model is not involved.

Rules implemented (in priority order):

  1. A mention with both a proper-name canonical AND a relation_hint
     (e.g. "my brother Greg") proposes:
       - CREATE_ENTITY  Greg (PERSON)  conf 0.9
       - ADD_RELATION   USER FAMILY_OF Greg  conf 0.9
     (Skipped if Greg already exists with the same name + alias check.)

  2. A mention with a relation_hint but NO proper name (e.g. "my dad")
     proposes:
       - CREATE_ENTITY  with name=hint (e.g. "dad")   conf 0.7
       - ADD_RELATION   USER FAMILY_OF "dad"           conf 0.7
     (Skipped if hint already represents an existing entity.)

  3. An ACTIVITY mention in a SHARE_EVENT turn proposes:
       - CREATE_ENTITY  the activity                  conf 0.8
       - ADD_RELATION   USER ENJOYS activity           conf 0.6
     (Lower-confidence on ENJOYS because one mention isn't proof of
     enjoyment; needs a second observation to auto-apply.)

  4. SHARE_EVENT with at least one anchor proposes:
       - RECORD_EVENT  Event(kind=CONVERSATION or NOTE,
                              when_start=temporal or now,
                              participants=resolved PERSON entities,
                              about=resolved TOPIC/HOLIDAY entities,
                              description=short summary)   conf 0.85

  5. CORRECTION turns are NOT auto-distilled. They go to a "needs human
     review" queue (later sprint). For now we emit no proposals.

Auto-apply threshold (in reflector.py): 0.85.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING

from latticed.v2.kstore.schema import (
    Entity, EntityKind, Event, EventKind, Relation, RelationKind,
    Source, SourceKind, USER_ENTITY_ID,
)

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore
    from latticed.v2.reflect.turn_log import TurnRecord


HIGH_CONFIDENCE_THRESHOLD = 0.85


class ProposalKind(str, Enum):
    CREATE_ENTITY = "create_entity"
    ADD_RELATION  = "add_relation"
    RECORD_EVENT  = "record_event"


@dataclass(frozen=True)
class Proposal:
    """A suggested kstore mutation derived from a turn.

    Only one of entity / relation / event is set per Proposal, matching
    the kind. Mirrors a discriminated union with explicit fields so
    callers can pattern-match without isinstance noise.
    """
    kind: ProposalKind
    confidence: float
    source_turn_id: int
    reason: str
    entity: Optional[Entity] = None
    relation: Optional[Relation] = None
    event: Optional[Event] = None

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= HIGH_CONFIDENCE_THRESHOLD


# Map a relation_hint to the appropriate RelationKind. Family terms map
# to FAMILY_OF; friend terms to FRIEND_OF; the rest fall back to KNOWS.
_HINT_TO_RELATION: dict[str, RelationKind] = {
    "dad":         RelationKind.FAMILY_OF,
    "father":      RelationKind.FAMILY_OF,
    "mom":         RelationKind.FAMILY_OF,
    "mother":      RelationKind.FAMILY_OF,
    "brother":     RelationKind.FAMILY_OF,
    "sister":      RelationKind.FAMILY_OF,
    "son":         RelationKind.FAMILY_OF,
    "daughter":    RelationKind.FAMILY_OF,
    "wife":        RelationKind.FAMILY_OF,
    "husband":     RelationKind.FAMILY_OF,
    "partner":     RelationKind.FAMILY_OF,
    "boyfriend":   RelationKind.FAMILY_OF,
    "girlfriend":  RelationKind.FAMILY_OF,
    "kid":         RelationKind.FAMILY_OF,
    "kids":        RelationKind.FAMILY_OF,
    "child":       RelationKind.FAMILY_OF,
    "children":    RelationKind.FAMILY_OF,
    "friend":      RelationKind.FRIEND_OF,
    "coworker":    RelationKind.KNOWS,
    "boss":        RelationKind.KNOWS,
    "neighbor":    RelationKind.KNOWS,
    "doctor":      RelationKind.KNOWS,
    "teacher":     RelationKind.KNOWS,
}


def _has_relation(
    kstore: "KStore",
    subject_id: str,
    rel_kind: RelationKind,
    object_id: str,
) -> bool:
    for r in kstore.recall_relations(subject_id, kind=rel_kind):
        if r.object_id == object_id:
            return True
    return False


def distill_turn(
    turn: "TurnRecord",
    *,
    kstore: "KStore",
) -> list[Proposal]:
    """Emit zero or more typed Proposals for the kstore based on this
    turn's perception. Pure function (modulo kstore reads for dedup).
    """
    proposals: list[Proposal] = []
    try:
        p = json.loads(turn.perception_json)
    except json.JSONDecodeError:
        return proposals

    intent = p.get("intent", "")
    mentions = p.get("mentions", []) or []
    temporal_refs = p.get("temporal_refs", []) or []
    src = Source(
        kind=SourceKind.INFERRED,
        note=f"distilled from turn #{turn.id}",
    )

    # ── Rule 5 (early return): corrections are never auto-distilled ──────
    if intent == "correction":
        return proposals

    # ── Rule 1+2: relation-hinted mentions become person + relation ──────
    resolved_persons: list[str] = []   # entity_ids of PERSON mentions in this turn
    for m in mentions:
        hint = (m.get("relation_hint") or "").lower()
        canonical = m.get("canonical", "")
        if not hint or m.get("kind") != "person":
            continue
        has_proper_name = (canonical.lower() != hint)
        existing = kstore.find_entity(canonical, kind=EntityKind.PERSON)
        if existing is not None:
            resolved_persons.append(existing.id)
            continue

        # Confidence: 0.9 if the user gave a proper name, 0.7 if only the role.
        ent_conf = 0.9 if has_proper_name else 0.7
        new_ent = Entity(
            id=Entity.new_id(), kind=EntityKind.PERSON, name=canonical,
            source=src,
        )
        proposals.append(Proposal(
            kind=ProposalKind.CREATE_ENTITY, confidence=ent_conf,
            source_turn_id=turn.id, reason=f"mention with hint '{hint}'",
            entity=new_ent,
        ))
        rel_kind = _HINT_TO_RELATION.get(hint, RelationKind.KNOWS)
        # Confidence for the relation is identical -- one mention with a
        # named role is strong evidence of the relation.
        proposals.append(Proposal(
            kind=ProposalKind.ADD_RELATION, confidence=ent_conf,
            source_turn_id=turn.id,
            reason=f"USER {rel_kind.value} {canonical}",
            relation=Relation(
                id=Relation.new_id(),
                subject_id=USER_ENTITY_ID,
                kind=rel_kind,
                object_id=new_ent.id,
                confidence=ent_conf,
                source=src,
            ),
        ))
        resolved_persons.append(new_ent.id)

    # ── Rule 3: activity mentions become typed entities + tentative ENJOYS
    # Intent-agnostic — the activity is in the user's input regardless of
    # how the intent classifier labeled the turn. A turn like "My friend
    # Alex and I went hiking" doesn't match share_event by starter word
    # (no "I"/"Today"/weekday opener) but still contains a real activity
    # mention worth recording.
    for m in mentions:
        if m.get("kind") != "activity":
            continue
        canonical = m.get("canonical", "")
        if not canonical:
            continue
        existing = kstore.find_entity(canonical, kind=EntityKind.ACTIVITY)
        if existing is None:
            new_ent = Entity(
                id=Entity.new_id(), kind=EntityKind.ACTIVITY,
                name=canonical, source=src,
            )
            proposals.append(Proposal(
                kind=ProposalKind.CREATE_ENTITY, confidence=0.8,
                source_turn_id=turn.id,
                reason=f"activity '{canonical}' mentioned",
                entity=new_ent,
            ))
            act_id = new_ent.id
        else:
            act_id = existing.id

        # ENJOYS gets a lower confidence -- one mention isn't proof
        # of enjoyment. The auto-apply threshold (0.85) skips this;
        # the reflector queues it. A second similar mention will
        # bump confidence in a later sprint (counting evidence).
        if not _has_relation(kstore, USER_ENTITY_ID,
                             RelationKind.ENJOYS, act_id):
            proposals.append(Proposal(
                kind=ProposalKind.ADD_RELATION, confidence=0.6,
                source_turn_id=turn.id,
                reason=f"USER tentatively ENJOYS {canonical}",
                relation=Relation(
                    id=Relation.new_id(),
                    subject_id=USER_ENTITY_ID,
                    kind=RelationKind.ENJOYS,
                    object_id=act_id,
                    confidence=0.6,
                    source=src,
                ),
            ))

    # ── Rule 4: SHARE_EVENT with anchors records an Event ────────────────
    if intent == "share_event":
        # When did it happen? Use the first resolved temporal ref, else
        # the perception's 'now' timestamp.
        when_iso = (
            temporal_refs[0]["when_iso"] if temporal_refs
            else p.get("now")
        )
        if when_iso:
            try:
                when_start = datetime.fromisoformat(when_iso)
            except ValueError:
                when_start = None
        else:
            when_start = None

        if when_start is not None:
            # Topic / about: any HOLIDAY or TOPIC mentions resolved in
            # this turn. For now we just record participants; HOLIDAY
            # entities aren't auto-created at this layer (they're a
            # global concept seeded by the temporal parser).
            description = (turn.user_input or "")[:160]
            evt = Event(
                id=Event.new_id(),
                kind=EventKind.CONVERSATION,
                when_start=when_start,
                participants=tuple([USER_ENTITY_ID] + resolved_persons),
                description=description,
                mood=None,    # set explicitly later if perception has mood
                confidence=0.85,
                source=src,
            )
            proposals.append(Proposal(
                kind=ProposalKind.RECORD_EVENT, confidence=0.85,
                source_turn_id=turn.id,
                reason="share_event with anchor → log event",
                event=evt,
            ))

    return proposals
