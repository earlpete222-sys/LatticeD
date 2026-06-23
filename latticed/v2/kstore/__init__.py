"""kstore — LatticeD v2 typed knowledge store.

The store holds what's TRUE about the user's world. Strings are user-facing
artifacts; the store traffics in typed entities, events, and relations with
absolute timestamps, source provenance, and confidence scores.

Design principles:
  - Every fact has a source (TurnRef, ToolCall, UserCorrection, etc.).
  - Every fact has a time. "yesterday" never reaches the store — perception
    resolves it to a datetime first.
  - Every fact has a confidence in [0.0, 1.0]. 1.0 = user stated it directly.
  - Records are immutable. Updates create a new record and supersede the old
    (the superseded one stays, with end_time set, for audit + reflection).
  - The model NEVER queries the store with free text. Callers use typed
    query methods (find_entity, list_events_about, recall_attribute).
    No SQL, no embedding similarity inside the store API itself.
"""
from latticed.v2.kstore.schema import (
    Entity,
    EntityKind,
    Event,
    EventKind,
    Relation,
    RelationKind,
    Source,
    SourceKind,
    Mood,
)
from latticed.v2.kstore.store import KStore

__all__ = [
    "Entity", "EntityKind",
    "Event", "EventKind",
    "Relation", "RelationKind",
    "Source", "SourceKind",
    "Mood",
    "KStore",
]
