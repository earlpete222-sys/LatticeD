"""v2 runtime: V2Runtime + OllamaNarratorBackend.

V2Runtime is the singleton that owns the v2 KStore (separate SQLite from
v1) and the Reviewer instance. Construct once per server process; pass
it into request handlers.

OllamaNarratorBackend is the production NarratorBackend that wires slot
prompts to ollama_client.generate. Each slot becomes ONE small generate
call -- the per-slot token budget keeps the model honest and the
latency low.

Graceful degradation: if Ollama is unreachable or the model isn't pulled,
the backend returns the slot's fallback_value and logs the failure.
The reviewer + fallback layers handle the rest -- the user still gets a
clean reply.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from latticed.v2.kstore.store import KStore
from latticed.v2.kstore.migrate import migrate_v1_belief_graph
from latticed.v2.reflect.reflector import Reflector
from latticed.v2.reflect.turn_log import TurnLog
from latticed.v2.review.reviewer import Reviewer
from latticed.v2.strategies.base import NarratorBackend, Slot

if TYPE_CHECKING:
    pass


logger = logging.getLogger("latticed.v2.runtime")


# ── Default paths ─────────────────────────────────────────────────────────
def _default_kstore_path() -> Path:
    """latticed/runtime/storage/v2_kstore.db by default; override via
    LATTICED_V2_KSTORE_PATH for tests or alternative installs."""
    override = os.environ.get("LATTICED_V2_KSTORE_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent.parent   # .../latticed/
    return here / "runtime" / "storage" / "v2_kstore.db"


def _default_v1_db_path() -> Path:
    """The v1 belief_graph lives in latticed/runtime/storage/end_game.db.
    Used for the one-shot v1→v2 migration on first v2 start."""
    override = os.environ.get("LATTICED_V1_DB_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent.parent
    return here / "runtime" / "storage" / "end_game.db"


def _default_turn_log_path() -> Path:
    """v2_turns.db alongside v2_kstore.db; override via env."""
    override = os.environ.get("LATTICED_V2_TURNLOG_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent.parent
    return here / "runtime" / "storage" / "v2_turns.db"


# ── OllamaNarratorBackend ─────────────────────────────────────────────────
class OllamaNarratorBackend(NarratorBackend):
    """Production NarratorBackend: calls Ollama once per MODEL slot.

    Construction:
        backend = OllamaNarratorBackend(
            ollama_client=ollama,
            model_name="deepseek-r1:1.5b",
            timeout_s=60.0,
        )

    Each fill_model_slot call:
      1. Builds a short prompt (slot.model_prompt only -- no system
         prompt, no scaffolding, no context bloat)
      2. Calls ollama.generate with temperature/num_predict from the slot
      3. Strips any <think>...</think> wrappers and trims whitespace
      4. Returns the result (raw -- the narrator validates against
         slot.constraint and decides retry/fallback)
      5. On any exception (Ollama down, model missing, timeout) returns
         slot.fallback_value instead of raising
    """

    _THINK_RX = re.compile(r"<think>.*?</think>", re.DOTALL)

    def __init__(
        self,
        *,
        ollama_client: Any,
        model_name: str = "deepseek-r1:1.5b",
        timeout_s: float = 60.0,
        keep_alive: str = "2m",
    ) -> None:
        self._client = ollama_client
        self._model = model_name
        self._timeout = timeout_s
        self._keep_alive = keep_alive

    async def fill_model_slot(self, slot: Slot, plan_context: dict) -> str:
        prompt = slot.model_prompt or ""
        options = {
            "temperature": slot.model_temperature,
            "num_predict": slot.model_max_tokens,
            # Small context: slot prompts are short; no point allocating
            # the full 4k KV cache for them.
            "num_ctx": 1024,
            "keep_alive": self._keep_alive,
        }

        def _do_call() -> str:
            resp = self._client.generate(
                model=self._model, prompt=prompt, options=options
            )
            return resp["response"]

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_do_call), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            logger.warning("[v2/narrate] slot %s timed out after %.0fs -- fallback",
                           slot.name, self._timeout)
            return slot.fallback_value
        except Exception as e:
            logger.warning(
                "[v2/narrate] slot %s call failed (%s: %s) -- fallback",
                slot.name, type(e).__name__, str(e)[:120],
            )
            return slot.fallback_value

        # Strip <think> blocks the reasoning model emits and trim.
        cleaned = self._THINK_RX.sub("", raw or "").strip()
        return cleaned


# ── V2Runtime ─────────────────────────────────────────────────────────────
class V2Runtime:
    """Process-wide singleton for v2. Holds the KStore + Reviewer + the
    NarratorBackend. Construct once at app startup; share across requests.

    The narrator backend is injectable so tests can pass StubNarratorBackend
    and the production path can pass OllamaNarratorBackend.
    """

    def __init__(
        self,
        *,
        kstore_path: Optional[Path] = None,
        backend: Optional[NarratorBackend] = None,
        v1_db_path: Optional[Path] = None,
        turn_log_path: Optional[Path] = None,
    ) -> None:
        self.kstore = KStore(kstore_path or _default_kstore_path())
        self.reviewer = Reviewer()
        self.backend: Optional[NarratorBackend] = backend
        self._v1_db_path = v1_db_path or _default_v1_db_path()
        self._migration_attempted = False
        # Sprint 54 — turn log + reflector for off-peak self-improvement
        self.turn_log = TurnLog(turn_log_path or _default_turn_log_path())
        self.reflector = Reflector(kstore=self.kstore, turn_log=self.turn_log)

    def attach_backend(self, backend: NarratorBackend) -> None:
        """Late-bind the backend (e.g. after Ollama init completes in lifespan)."""
        self.backend = backend

    def maybe_migrate_v1(self, force: bool = False) -> dict:
        """One-shot migration from v1 belief_graph. No-op if already
        attempted in this process AND the store already has anything
        beyond the two singletons -- safe to call from a request handler.
        Returns the migration report as a dict (empty when skipped)."""
        if self._migration_attempted and not force:
            return {}
        self._migration_attempted = True
        if not self._v1_db_path.exists():
            return {}
        live = self.kstore.stats()
        # Singletons (USER + SYSTEM) are 2 entities by default; skip migration
        # only if the store has been populated already by a prior run.
        if not force and (
            live["live_entities"] > 2
            or live["live_relations"] > 0
            or live["live_events"] > 0
        ):
            logger.info("[v2/migrate] store non-empty; skipping v1 migration")
            return {}
        logger.info("[v2/migrate] running one-shot v1->v2 migration from %s",
                    self._v1_db_path)
        report = migrate_v1_belief_graph(
            v1_db_path=self._v1_db_path, store=self.kstore,
        )
        report_d = report.as_dict()
        logger.info("[v2/migrate] complete: %d typed, %d legacy, %d entities",
                    report_d["typed_records_created"],
                    report_d["legacy_stashed"],
                    report_d["entities_created"])
        return report_d

    def close(self) -> None:
        self.kstore.close()
        try:
            self.turn_log.close()
        except Exception:
            pass
