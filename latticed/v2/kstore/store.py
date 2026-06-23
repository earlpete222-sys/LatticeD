"""KStore — SQLite-backed persistence for the v2 typed knowledge layer.

API design rules:
  - Callers NEVER see SQL. Everything goes through typed methods.
  - The model NEVER reaches this layer directly. Code that calls a model
    is a level up; the model receives only the result of typed queries.
  - Writes always supersede rather than mutate. The prior record stays
    with superseded_at set so the reflection layer can study what changed.
  - The store is process-local; thread-safe via a single lock around the
    connection. (Cross-process concurrency isn't a v2 goal yet.)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from latticed.v2.kstore.schema import (
    Entity, EntityKind,
    Event, EventKind,
    Relation, RelationKind,
    Source, SourceKind,
    Mood,
    USER_ENTITY_ID, SYSTEM_ENTITY_ID,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    aliases_json    TEXT NOT NULL DEFAULT '[]',
    attributes_json TEXT NOT NULL DEFAULT '[]',
    source_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    superseded_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind, superseded_at);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    when_start      TEXT NOT NULL,
    when_end        TEXT,
    participants_json TEXT NOT NULL DEFAULT '[]',
    about_json      TEXT NOT NULL DEFAULT '[]',
    description     TEXT NOT NULL DEFAULT '',
    mood            TEXT,
    confidence      REAL NOT NULL DEFAULT 1.0,
    source_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    superseded_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_when ON events(when_start DESC, superseded_at);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, superseded_at);

CREATE TABLE IF NOT EXISTS relations (
    id              TEXT PRIMARY KEY,
    subject_id      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    object_id       TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    source_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    superseded_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id, kind, superseded_at);
CREATE INDEX IF NOT EXISTS idx_relations_object  ON relations(object_id, kind, superseded_at);

-- Legacy bucket: v1 belief_graph rows that couldn't be parsed into
-- typed records are preserved here so we never lose data during migration.
CREATE TABLE IF NOT EXISTS legacy_beliefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fact            TEXT NOT NULL,
    v1_confidence   REAL,
    v1_last_seen    REAL,
    v1_source       TEXT,
    v1_categories   TEXT,
    migrated_at     TEXT NOT NULL
);
"""


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("kstore stores only timezone-aware datetimes")
    return dt.isoformat()


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _source_to_json(src: Source) -> str:
    return json.dumps({
        "kind": src.kind.value,
        "turn_ref": src.turn_ref,
        "tool_name": src.tool_name,
        "note": src.note,
    })


def _source_from_json(s: str) -> Source:
    d = json.loads(s)
    return Source(
        kind=SourceKind(d["kind"]),
        turn_ref=d.get("turn_ref"),
        tool_name=d.get("tool_name"),
        note=d.get("note"),
    )


def _entity_from_row(row: sqlite3.Row) -> Entity:
    return Entity(
        id=row["id"],
        kind=EntityKind(row["kind"]),
        name=row["name"],
        aliases=tuple(json.loads(row["aliases_json"])),
        attributes=tuple(tuple(kv) for kv in json.loads(row["attributes_json"])),
        source=_source_from_json(row["source_json"]),
        created_at=_from_iso(row["created_at"]),
        superseded_at=_from_iso(row["superseded_at"]),
    )


def _event_from_row(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        kind=EventKind(row["kind"]),
        when_start=_from_iso(row["when_start"]),
        when_end=_from_iso(row["when_end"]),
        participants=tuple(json.loads(row["participants_json"])),
        about=tuple(json.loads(row["about_json"])),
        description=row["description"] or "",
        mood=Mood(row["mood"]) if row["mood"] else None,
        confidence=row["confidence"],
        source=_source_from_json(row["source_json"]),
        created_at=_from_iso(row["created_at"]),
        superseded_at=_from_iso(row["superseded_at"]),
    )


def _relation_from_row(row: sqlite3.Row) -> Relation:
    return Relation(
        id=row["id"],
        subject_id=row["subject_id"],
        kind=RelationKind(row["kind"]),
        object_id=row["object_id"],
        confidence=row["confidence"],
        source=_source_from_json(row["source_json"]),
        created_at=_from_iso(row["created_at"]),
        superseded_at=_from_iso(row["superseded_at"]),
    )


class KStore:
    """Typed knowledge store, SQLite-backed.

    Construct once per process. Pass the database path explicitly so v2
    storage stays separate from v1 (and from tests).
    """

    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.commit()
        self._ensure_singletons()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── singleton seeding ──────────────────────────────────────────────────
    def _ensure_singletons(self) -> None:
        """User + System entities are guaranteed to exist after init."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM entities WHERE id IN (?, ?)",
                (USER_ENTITY_ID, SYSTEM_ENTITY_ID),
            )
            existing = {r["id"] for r in cur.fetchall()}
            now = datetime.now(timezone.utc)
            sys_src = Source(kind=SourceKind.SYSTEM)
            if USER_ENTITY_ID not in existing:
                self._insert_entity_row(Entity(
                    id=USER_ENTITY_ID, kind=EntityKind.USER, name="user",
                    source=sys_src, created_at=now,
                ))
            if SYSTEM_ENTITY_ID not in existing:
                self._insert_entity_row(Entity(
                    id=SYSTEM_ENTITY_ID, kind=EntityKind.SYSTEM, name="LatticeD",
                    source=sys_src, created_at=now,
                ))
            self._conn.commit()

    # ── write API ──────────────────────────────────────────────────────────
    def add_entity(self, entity: Entity) -> Entity:
        with self._lock:
            self._insert_entity_row(entity)
            self._conn.commit()
        return entity

    def add_event(self, event: Event) -> Event:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (id, kind, when_start, when_end, "
                "participants_json, about_json, description, mood, confidence, "
                "source_json, created_at, superseded_at) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.id, event.kind.value,
                    _iso(event.when_start), _iso(event.when_end),
                    json.dumps(list(event.participants)),
                    json.dumps(list(event.about)),
                    event.description,
                    event.mood.value if event.mood else None,
                    event.confidence,
                    _source_to_json(event.source),
                    _iso(event.created_at),
                    _iso(event.superseded_at),
                ),
            )
            self._conn.commit()
        return event

    def add_relation(self, relation: Relation) -> Relation:
        with self._lock:
            self._conn.execute(
                "INSERT INTO relations (id, subject_id, kind, object_id, "
                "confidence, source_json, created_at, superseded_at) VALUES "
                "(?,?,?,?,?,?,?,?)",
                (
                    relation.id, relation.subject_id, relation.kind.value,
                    relation.object_id, relation.confidence,
                    _source_to_json(relation.source),
                    _iso(relation.created_at),
                    _iso(relation.superseded_at),
                ),
            )
            self._conn.commit()
        return relation

    def _insert_entity_row(self, entity: Entity) -> None:
        """Caller must hold self._lock and call commit() itself."""
        self._conn.execute(
            "INSERT INTO entities (id, kind, name, aliases_json, attributes_json, "
            "source_json, created_at, superseded_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                entity.id, entity.kind.value, entity.name,
                json.dumps(list(entity.aliases)),
                json.dumps([list(kv) for kv in entity.attributes]),
                _source_to_json(entity.source),
                _iso(entity.created_at),
                _iso(entity.superseded_at),
            ),
        )

    def supersede_entity(self, old_id: str, new_entity: Entity) -> Entity:
        """Mark the old record ended at now and insert the new record."""
        now = datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute(
                "UPDATE entities SET superseded_at = ? WHERE id = ? AND superseded_at IS NULL",
                (_iso(now), old_id),
            )
            self._insert_entity_row(new_entity)
            self._conn.commit()
        return new_entity

    # ── typed read API — these are the methods the rest of v2 calls ────────
    def find_entity(
        self,
        name: str,
        *,
        kind: Optional[EntityKind] = None,
        include_aliases: bool = True,
    ) -> Optional[Entity]:
        """Return the live entity matching ``name`` (or one of its aliases),
        optionally filtered to a kind. Case-insensitive. None if not found."""
        sql = (
            "SELECT * FROM entities WHERE superseded_at IS NULL "
            "AND name = ? COLLATE NOCASE"
        )
        params: list = [name]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        if row is not None:
            return _entity_from_row(row)
        if not include_aliases:
            return None
        # Alias scan — small table in practice; OK to fetch and filter in Python.
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM entities WHERE superseded_at IS NULL"
                + (" AND kind = ?" if kind else ""),
                ([kind.value] if kind else []),
            )
            for r in cur:
                aliases = [a.lower() for a in json.loads(r["aliases_json"])]
                if name.lower() in aliases:
                    return _entity_from_row(r)
        return None

    def list_entities(self, kind: Optional[EntityKind] = None) -> list[Entity]:
        sql = "SELECT * FROM entities WHERE superseded_at IS NULL"
        params: list = []
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        sql += " ORDER BY created_at"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_entity_from_row(r) for r in rows]

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
        return _entity_from_row(row) if row else None

    def list_events_about(
        self,
        entity_ids: Iterable[str],
        *,
        limit: int = 20,
        since: Optional[datetime] = None,
    ) -> list[Event]:
        """All events whose participants or about includes any of entity_ids,
        newest first, live records only."""
        ids = list(entity_ids)
        if not ids:
            return []
        # Use JSON_EACH for efficient containment scan; SQLite has it built in.
        # We do an OR of participants_json and about_json containment.
        placeholders = ",".join("?" * len(ids))
        sql = (
            "SELECT DISTINCT e.* FROM events e "
            "WHERE e.superseded_at IS NULL "
            "AND ("
            f"  EXISTS (SELECT 1 FROM json_each(e.participants_json) WHERE value IN ({placeholders})) "
            f"  OR EXISTS (SELECT 1 FROM json_each(e.about_json)        WHERE value IN ({placeholders}))"
            ")"
        )
        params: list = [*ids, *ids]
        if since is not None:
            sql += " AND e.when_start >= ?"
            params.append(_iso(since))
        sql += " ORDER BY e.when_start DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_event_from_row(r) for r in rows]

    def recall_relations(
        self,
        subject_id: str,
        *,
        kind: Optional[RelationKind] = None,
    ) -> list[Relation]:
        """All live relations originating at subject_id, optionally
        filtered to one relation kind. Used for 'who is X?' and 'what does
        the user enjoy?' style queries."""
        sql = (
            "SELECT * FROM relations WHERE subject_id = ? AND superseded_at IS NULL"
        )
        params: list = [subject_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        sql += " ORDER BY confidence DESC, created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_relation_from_row(r) for r in rows]

    def recall_attribute(
        self,
        subject_id: str,
        relation_kind: RelationKind,
    ) -> list[Entity]:
        """Convenience: 'what does the user enjoy?' →
        recall_attribute(USER, ENJOYS) → list[Entity of kind ACTIVITY]."""
        rels = self.recall_relations(subject_id, kind=relation_kind)
        out: list[Entity] = []
        for r in rels:
            ent = self.get_entity(r.object_id)
            if ent and ent.superseded_at is None:
                out.append(ent)
        return out

    # ── legacy bucket (v1 migration overflow) ──────────────────────────────
    def stash_legacy_belief(
        self,
        fact: str,
        v1_confidence: Optional[float],
        v1_last_seen: Optional[float],
        v1_source: Optional[str],
        v1_categories: Optional[str],
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO legacy_beliefs (fact, v1_confidence, v1_last_seen, "
                "v1_source, v1_categories, migrated_at) VALUES (?,?,?,?,?,?)",
                (fact, v1_confidence, v1_last_seen, v1_source, v1_categories,
                 _iso(datetime.now(timezone.utc))),
            )
            self._conn.commit()

    def legacy_belief_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM legacy_beliefs"
            ).fetchone()
        return int(row["n"])

    # ── introspection (for tests + reflection layer) ───────────────────────
    def stats(self) -> dict:
        with self._lock:
            ent = self._conn.execute(
                "SELECT COUNT(*) AS n FROM entities WHERE superseded_at IS NULL"
            ).fetchone()["n"]
            evt = self._conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE superseded_at IS NULL"
            ).fetchone()["n"]
            rel = self._conn.execute(
                "SELECT COUNT(*) AS n FROM relations WHERE superseded_at IS NULL"
            ).fetchone()["n"]
            legacy = self._conn.execute(
                "SELECT COUNT(*) AS n FROM legacy_beliefs"
            ).fetchone()["n"]
        return {
            "live_entities": int(ent),
            "live_events": int(evt),
            "live_relations": int(rel),
            "legacy_beliefs": int(legacy),
        }
