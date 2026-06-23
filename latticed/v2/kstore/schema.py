"""kstore typed schema.

All records are frozen dataclasses. Construction validates invariants;
mutation goes through KStore.supersede() which writes a new record and
marks the prior one ended.

We use Enums (string-valued) for the taxonomies so the SQLite columns
stay human-readable and migrations are forgiving.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


# ── Enumerated taxonomies ────────────────────────────────────────────────────
class EntityKind(str, Enum):
    """What sort of thing this Entity represents.

    Deliberately small. Adding a kind is an architectural decision — most
    "new kinds" should be modeled as Relations between existing kinds, or
    as attributes on an existing kind.
    """
    PERSON       = "person"        # the user, their dad, a friend
    PLACE        = "place"         # the park, work, home
    ACTIVITY     = "activity"      # hiking, cooking, journaling
    TOPIC        = "topic"         # finances, retirement, the dog
    HOLIDAY      = "holiday"       # Father's Day, Thanksgiving — known calendar entries
    PROJECT      = "project"       # a multi-event goal the user is pursuing
    USER         = "user"          # singleton: the human this LatticeD serves
    SYSTEM       = "system"        # singleton: LatticeD itself
    OTHER        = "other"         # escape hatch — but use Relation instead when possible


class EventKind(str, Enum):
    """The flavor of moment an Event captures.

    Strategy layer dispatches on this — adding a kind usually means adding
    a strategy template.
    """
    CONVERSATION = "conversation"   # the user talked with someone
    MILESTONE    = "milestone"      # paid off debt, got the job, ran the race
    ROUTINE      = "routine"        # the recurring thing they do
    ENCOUNTER    = "encounter"      # ran into someone, visited a place
    HOLIDAY      = "holiday"        # a calendar event that occurred
    MOOD         = "mood"           # the user reported how they felt
    DECISION     = "decision"       # they chose something
    QUESTION     = "question"       # they asked LatticeD something
    NOTE         = "note"           # generic captured fact
    CORRECTION   = "correction"     # the user told LatticeD it was wrong


class RelationKind(str, Enum):
    """How two entities relate.

    Directional (subject → object). The model never invents new relation
    kinds; the perception layer maps natural-language verbs to this set.
    """
    KNOWS        = "knows"         # user knows dad
    FAMILY_OF    = "family_of"     # dad is family_of user
    FRIEND_OF    = "friend_of"     # alex is friend_of user
    LIVES_IN     = "lives_in"      # user lives_in place
    WORKS_AT     = "works_at"
    ENJOYS       = "enjoys"        # user enjoys hiking
    DISLIKES     = "dislikes"
    AVOIDS       = "avoids"
    PURSUES      = "pursues"       # user pursues fitness-goal
    OWNS         = "owns"
    PART_OF      = "part_of"       # event part_of project
    ABOUT        = "about"         # event about topic
    PARTICIPANT  = "participant"   # event participant person


class SourceKind(str, Enum):
    """Where a record came from. Critical for confidence + audit."""
    USER_STATED   = "user_stated"     # the user said this directly
    USER_CONFIRMED = "user_confirmed" # we asked, they said yes
    USER_CORRECTED = "user_corrected" # they fixed something we had wrong
    INFERRED      = "inferred"        # derived from other records by reasoning
    TOOL          = "tool"            # a deterministic tool produced it (calendar lookup, etc.)
    LEGACY_V1     = "legacy_v1"       # migrated from the v1 belief_graph string store
    SYSTEM        = "system"          # LatticeD itself wrote this (e.g. a built-in holiday)


class Mood(str, Enum):
    """Compact mood taxonomy — perception tags each user turn with one."""
    JOY        = "joy"
    PRIDE      = "pride"
    CALM       = "calm"
    CURIOUS    = "curious"
    NEUTRAL    = "neutral"
    TIRED      = "tired"
    FRUSTRATED = "frustrated"
    SAD        = "sad"
    ANXIOUS    = "anxious"
    OTHER      = "other"


# ── Source: provenance of every record ──────────────────────────────────────
@dataclass(frozen=True)
class Source:
    """Why we believe a fact. Attached to every Entity/Event/Relation.

    turn_ref points at the conversation turn that produced it (when
    applicable), so a reviewer or the user can audit "where did you get
    this?" and the system can answer with a real citation.
    """
    kind: SourceKind
    turn_ref: Optional[str] = None       # opaque ID into the conversation log
    tool_name: Optional[str] = None      # for SourceKind.TOOL
    note: Optional[str] = None           # free-text context, dev-only

    def __post_init__(self) -> None:
        if self.kind == SourceKind.TOOL and not self.tool_name:
            raise ValueError("SourceKind.TOOL requires tool_name")


# ── Entity: a thing the system knows about ─────────────────────────────────
@dataclass(frozen=True)
class Entity:
    """A typed thing — person, place, activity, topic, holiday.

    name is the canonical handle ('Dad', 'the park', 'hiking'). aliases
    are alternate forms the perception layer may see.
    """
    id: str
    kind: EntityKind
    name: str
    aliases: tuple[str, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()   # immutable key/value list
    source: Source = field(default_factory=lambda: Source(kind=SourceKind.SYSTEM))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    superseded_at: Optional[datetime] = None       # set when a newer record replaces this

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Entity.name cannot be empty")
        if not self.id:
            raise ValueError("Entity.id required (use new_id() if creating)")

    @staticmethod
    def new_id() -> str:
        return f"ent_{uuid4().hex[:16]}"


# ── Event: something that happened (or will happen) ────────────────────────
@dataclass(frozen=True)
class Event:
    """A moment in the user's life, with absolute time, participants, and
    optional mood.

    when_start is ALWAYS absolute (datetime); perception resolves
    'yesterday' / 'tomorrow' before the event reaches the store.

    description is a SHORT user-grounded summary — used for retrieval
    relevance, not as the source of truth (the structured fields are).
    """
    id: str
    kind: EventKind
    when_start: datetime
    when_end: Optional[datetime] = None
    participants: tuple[str, ...] = ()         # tuple of Entity.id values
    about: tuple[str, ...] = ()                # entity IDs the event is about (Topics, Holidays)
    description: str = ""
    mood: Optional[Mood] = None
    confidence: float = 1.0
    source: Source = field(default_factory=lambda: Source(kind=SourceKind.USER_STATED))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    superseded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence out of range: {self.confidence}")
        if self.when_end and self.when_end < self.when_start:
            raise ValueError("when_end before when_start")
        if self.when_start.tzinfo is None:
            raise ValueError("when_start must be timezone-aware")
        if not self.id:
            raise ValueError("Event.id required")

    @staticmethod
    def new_id() -> str:
        return f"evt_{uuid4().hex[:16]}"


# ── Relation: how two entities relate ──────────────────────────────────────
@dataclass(frozen=True)
class Relation:
    """A typed, directional relation between two entities (subject → object).

    'My dad' becomes: Relation(subject=user_id, kind=FAMILY_OF, object=dad_id).
    Relations are first-class records so they have source + confidence too.
    """
    id: str
    subject_id: str
    kind: RelationKind
    object_id: str
    confidence: float = 1.0
    source: Source = field(default_factory=lambda: Source(kind=SourceKind.USER_STATED))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    superseded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence out of range: {self.confidence}")
        if self.subject_id == self.object_id:
            raise ValueError("Relation subject and object cannot be identical")
        if not self.id:
            raise ValueError("Relation.id required")

    @staticmethod
    def new_id() -> str:
        return f"rel_{uuid4().hex[:16]}"


# ── Singleton conveniences ─────────────────────────────────────────────────
USER_ENTITY_ID = "ent_user"     # the human LatticeD serves — created at store init
SYSTEM_ENTITY_ID = "ent_system" # LatticeD itself — created at store init
