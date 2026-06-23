"""v1 → v2 belief-graph migration.

The v1 belief_graph stores facts as free-text strings. We can't parse all
of them into typed v2 records — that's what the model never reliably did
either. Instead:

  * Best-effort parse the easy patterns into typed Entities + Relations
    (activities the user enjoys, people in their life, places, mood notes)
  * Stash everything else in `legacy_beliefs` so nothing is lost
  * Report a migration summary so the user/operator can see what landed
    where and what may need manual review

Idempotent — re-running won't double-write because every successful match
is keyed by (subject, kind, object) lookup before insert.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from latticed.v2.kstore.schema import (
    Entity, EntityKind,
    Relation, RelationKind,
    Source, SourceKind,
    USER_ENTITY_ID,
)
from latticed.v2.kstore.store import KStore


# Order matters: more specific patterns first. Each pattern captures the
# object phrase (e.g. "hiking", "Alex", "Bellevue") and infers the relation
# kind. Patterns are deliberately narrow — false positives leak garbage
# into the typed store; misses just go to legacy_beliefs, which is fine.
_PATTERNS: list[tuple[re.Pattern[str], RelationKind, EntityKind]] = [
    # "user enjoys hiking", "user loves cooking", "user likes the park"
    (re.compile(r"^\s*user\s+(?:enjoys?|loves?|likes?)\s+(?:to\s+)?(?:go\s+)?(.+?)\.?\s*$",
                re.IGNORECASE),
     RelationKind.ENJOYS, EntityKind.ACTIVITY),
    # "user dislikes ...", "user hates ..."
    (re.compile(r"^\s*user\s+(?:dislikes?|hates?|doesn'?t\s+like)\s+(.+?)\.?\s*$",
                re.IGNORECASE),
     RelationKind.DISLIKES, EntityKind.ACTIVITY),
    # "user avoids ..."
    (re.compile(r"^\s*user\s+avoids?\s+(.+?)\.?\s*$", re.IGNORECASE),
     RelationKind.AVOIDS, EntityKind.ACTIVITY),
    # "user lives in Bellevue" / "user lives in Seattle"
    (re.compile(r"^\s*user\s+lives?\s+in\s+(.+?)\.?\s*$", re.IGNORECASE),
     RelationKind.LIVES_IN, EntityKind.PLACE),
    # "user works at Boeing"
    (re.compile(r"^\s*user\s+works?\s+(?:at|for)\s+(.+?)\.?\s*$", re.IGNORECASE),
     RelationKind.WORKS_AT, EntityKind.PLACE),
    # "user's dad is X", "user's brother is X"
    (re.compile(
        r"^\s*user(?:'s)?\s+(dad|mom|mother|father|brother|sister|son|daughter|wife|husband|partner)\s+"
        r"(?:is\s+(?:called\s+|named\s+)?)?(.+?)\.?\s*$",
        re.IGNORECASE),
     RelationKind.FAMILY_OF, EntityKind.PERSON),
    # "user knows X", "user's friend X"
    (re.compile(r"^\s*user(?:'s)?\s+friend\s+(?:is\s+)?(.+?)\.?\s*$", re.IGNORECASE),
     RelationKind.FRIEND_OF, EntityKind.PERSON),
]


@dataclass
class MigrationReport:
    rows_seen: int = 0
    typed_records_created: int = 0
    relations_created: int = 0
    entities_created: int = 0
    legacy_stashed: int = 0
    skipped_empty: int = 0
    sample_parsed: list[str] = None
    sample_stashed: list[str] = None

    def __post_init__(self) -> None:
        if self.sample_parsed is None:
            self.sample_parsed = []
        if self.sample_stashed is None:
            self.sample_stashed = []

    def as_dict(self) -> dict:
        return {
            "rows_seen": self.rows_seen,
            "typed_records_created": self.typed_records_created,
            "relations_created": self.relations_created,
            "entities_created": self.entities_created,
            "legacy_stashed": self.legacy_stashed,
            "skipped_empty": self.skipped_empty,
            "sample_parsed": list(self.sample_parsed[:10]),
            "sample_stashed": list(self.sample_stashed[:10]),
        }


def _normalize_object_phrase(s: str) -> str:
    """Trim filler words and trailing punctuation off a captured object."""
    s = s.strip().strip(".!,").strip()
    s = re.sub(r"^(the|a|an)\s+", "", s, flags=re.IGNORECASE)
    return s


def _existing_relation(
    store: KStore,
    subject_id: str,
    kind: RelationKind,
    object_id: str,
) -> bool:
    """True if this exact live relation already exists — keeps re-running
    the migrator idempotent."""
    for r in store.recall_relations(subject_id, kind=kind):
        if r.object_id == object_id:
            return True
    return False


def _get_or_create_entity(
    store: KStore,
    name: str,
    kind: EntityKind,
    source: Source,
) -> Entity:
    """Look up by name (case-insensitive, including aliases). Create if missing."""
    existing = store.find_entity(name, kind=kind)
    if existing is not None:
        return existing
    return store.add_entity(Entity(
        id=Entity.new_id(),
        kind=kind,
        name=name,
        source=source,
    ))


def migrate_v1_belief_graph(
    *,
    v1_db_path: Path,
    store: KStore,
    limit: Optional[int] = None,
) -> MigrationReport:
    """Read the v1 belief_graph table and move what we can into the v2 store.

    The v1 table schema (from latticed.py init_db):
        id INTEGER PK, fact TEXT UNIQUE, confidence REAL, last_seen REAL,
        source TEXT, categories TEXT
    """
    report = MigrationReport()
    if not v1_db_path.exists():
        return report

    conn = sqlite3.connect(str(v1_db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Tolerate the table not existing yet (fresh install case).
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='belief_graph'"
        ).fetchall()
        if not rows:
            return report
        sql = "SELECT fact, confidence, last_seen, source, categories FROM belief_graph"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    legacy_src = Source(
        kind=SourceKind.LEGACY_V1,
        note="migrated from v1 belief_graph",
    )

    for r in rows:
        report.rows_seen += 1
        fact = (r["fact"] or "").strip()
        if not fact:
            report.skipped_empty += 1
            continue

        matched = False
        for pattern, rel_kind, obj_kind in _PATTERNS:
            m = pattern.match(fact)
            if not m:
                continue
            obj_phrase = _normalize_object_phrase(m.group(m.lastindex))
            if not obj_phrase:
                continue
            ent = _get_or_create_entity(store, obj_phrase, obj_kind, legacy_src)
            if not _existing_relation(store, USER_ENTITY_ID, rel_kind, ent.id):
                store.add_relation(Relation(
                    id=Relation.new_id(),
                    subject_id=USER_ENTITY_ID,
                    kind=rel_kind,
                    object_id=ent.id,
                    confidence=float(r["confidence"] or 0.5),
                    source=legacy_src,
                ))
                report.relations_created += 1
                if ent.created_at >= datetime.now(timezone.utc).replace(microsecond=0):
                    report.entities_created += 1
            report.typed_records_created += 1
            if len(report.sample_parsed) < 10:
                report.sample_parsed.append(fact)
            matched = True
            break

        if not matched:
            store.stash_legacy_belief(
                fact=fact,
                v1_confidence=r["confidence"],
                v1_last_seen=r["last_seen"],
                v1_source=r["source"],
                v1_categories=r["categories"],
            )
            report.legacy_stashed += 1
            if len(report.sample_stashed) < 10:
                report.sample_stashed.append(fact)

    return report
