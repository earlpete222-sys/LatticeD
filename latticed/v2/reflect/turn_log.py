"""TurnLog — append-only record of every v2 turn.

The reflector reads from this; nothing else writes. Each row captures
enough structured information to re-run reflection later if we change
the distiller logic — that's how the system gets smarter without
losing history.

Stored fields are JSON-serialized typed values, NOT raw model outputs
where possible. We want the reflector reasoning over Perception, not
over text.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_turns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL,
    user_input        TEXT NOT NULL,
    perception_json   TEXT NOT NULL,
    strategy_name     TEXT NOT NULL,
    expected_shape    TEXT NOT NULL,
    final_text        TEXT NOT NULL,
    verdict           TEXT NOT NULL,
    used_fallback     INTEGER NOT NULL DEFAULT 0,
    fallback_reason   TEXT,
    processed_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_v2_turns_unprocessed
    ON v2_turns(processed_at, id) WHERE processed_at IS NULL;
"""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TurnRecord:
    """One historic v2 turn — what the distiller reads."""
    id: int
    created_at: datetime
    user_input: str
    perception_json: str       # Stored as raw JSON; Distiller reconstitutes
    strategy_name: str
    expected_shape: str
    final_text: str
    verdict: str
    used_fallback: bool
    fallback_reason: Optional[str]
    processed_at: Optional[datetime]


class TurnLog:
    """SQLite-backed append-only turn log. Lives alongside the kstore;
    construct with the same db_path-derivation pattern."""

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

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── Append ────────────────────────────────────────────────────────────
    def append_turn(
        self,
        *,
        user_input: str,
        perception_json: str,
        strategy_name: str,
        expected_shape: str,
        final_text: str,
        verdict: str,
        used_fallback: bool,
        fallback_reason: Optional[str] = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO v2_turns ("
                "created_at, user_input, perception_json, strategy_name, "
                "expected_shape, final_text, verdict, used_fallback, "
                "fallback_reason) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    _iso_now(), user_input, perception_json,
                    strategy_name, expected_shape, final_text,
                    verdict, 1 if used_fallback else 0,
                    fallback_reason,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    # ── Read ──────────────────────────────────────────────────────────────
    def list_unprocessed(self, limit: int = 100) -> list[TurnRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM v2_turns WHERE processed_at IS NULL "
                "ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_turn(self, turn_id: int) -> Optional[TurnRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM v2_turns WHERE id = ?", (turn_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def unprocessed_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM v2_turns WHERE processed_at IS NULL"
            ).fetchone()
        return int(row["n"])

    def total_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM v2_turns"
            ).fetchone()
        return int(row["n"])

    # ── Mark processed ───────────────────────────────────────────────────
    def mark_processed(self, turn_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE v2_turns SET processed_at = ? "
                "WHERE id = ? AND processed_at IS NULL",
                (_iso_now(), turn_id),
            )
            self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> TurnRecord:
        return TurnRecord(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            user_input=row["user_input"],
            perception_json=row["perception_json"],
            strategy_name=row["strategy_name"],
            expected_shape=row["expected_shape"],
            final_text=row["final_text"],
            verdict=row["verdict"],
            used_fallback=bool(row["used_fallback"]),
            fallback_reason=row["fallback_reason"],
            processed_at=(datetime.fromisoformat(row["processed_at"])
                          if row["processed_at"] else None),
        )


# ── Serialization helper used by the endpoint to record perception ─────────
def perception_to_json(perception) -> str:
    """Serialize a Perception into the JSON-stable shape we persist.

    Only the typed fields we need for reflection — surface form, kind,
    confidence, relation hint, temporal text + resolved date.
    """
    return json.dumps({
        "intent": perception.intent.value,
        "intent_confidence": perception.intent_confidence,
        "mood": perception.mood.value if perception.mood else None,
        "user_input": perception.user_input,
        "now": perception.now.isoformat(),
        "mentions": [
            {
                "surface": m.surface,
                "canonical": m.canonical,
                "kind": m.kind.value,
                "confidence": m.confidence,
                "entity_id": m.entity_id,
                "relation_hint": m.relation_hint,
            }
            for m in perception.mentions
        ],
        "temporal_refs": [
            {
                "text": t.text,
                "when_iso": t.when.isoformat(),
                "grain": t.grain.value,
                "confidence": t.confidence,
            }
            for t in perception.temporal_refs
        ],
    }, separators=(",", ":"))
