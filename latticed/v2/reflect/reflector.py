"""Reflector — orchestrator for the v2 reflection layer.

Reads unprocessed turns from the TurnLog, runs the distiller, applies
high-confidence proposals to the kstore, marks turns processed.
Idempotent — safe to call repeatedly; processed turns are skipped.

Returns a ReflectionReport summarizing what changed, so an operator can
see what the system learned without grepping logs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from latticed.v2.reflect.distiller import (
    HIGH_CONFIDENCE_THRESHOLD,
    Proposal,
    ProposalKind,
    distill_turn,
)

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore
    from latticed.v2.reflect.turn_log import TurnLog


logger = logging.getLogger("latticed.v2.reflect")


@dataclass
class ReflectionReport:
    turns_processed: int = 0
    entities_created: int = 0
    relations_created: int = 0
    events_created: int = 0
    proposals_seen: int = 0
    proposals_deferred: int = 0    # low-confidence, not auto-applied
    sample_applied: list[str] = field(default_factory=list)
    sample_deferred: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "turns_processed":     self.turns_processed,
            "entities_created":    self.entities_created,
            "relations_created":   self.relations_created,
            "events_created":      self.events_created,
            "proposals_seen":      self.proposals_seen,
            "proposals_deferred":  self.proposals_deferred,
            "sample_applied":      list(self.sample_applied[:10]),
            "sample_deferred":     list(self.sample_deferred[:10]),
        }


class Reflector:
    """Runs the distiller over unprocessed turns and applies what's safe."""

    def __init__(
        self,
        *,
        kstore: "KStore",
        turn_log: "TurnLog",
        confidence_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._kstore = kstore
        self._turn_log = turn_log
        self._threshold = confidence_threshold

    def reflect(self, *, batch: int = 100) -> ReflectionReport:
        """Process up to ``batch`` unprocessed turns. Returns a report."""
        report = ReflectionReport()
        turns = self._turn_log.list_unprocessed(limit=batch)
        for turn in turns:
            proposals = distill_turn(turn, kstore=self._kstore)
            report.proposals_seen += len(proposals)
            self._apply(proposals, report)
            self._turn_log.mark_processed(turn.id)
            report.turns_processed += 1
        if report.turns_processed:
            logger.info(
                "[v2/reflect] processed %d turns: +%d entities, +%d relations, "
                "+%d events (%d proposals deferred)",
                report.turns_processed, report.entities_created,
                report.relations_created, report.events_created,
                report.proposals_deferred,
            )
        return report

    def _apply(
        self,
        proposals: list[Proposal],
        report: ReflectionReport,
    ) -> None:
        """Apply high-confidence proposals; defer the rest.

        Within a single turn's proposal list, we apply CREATE_ENTITY
        proposals first so subsequent ADD_RELATION proposals can use
        the newly-created entity_id even though the original Proposal
        object holds the stale "not yet inserted" reference. (Our
        Proposal carries the actual Entity / Relation object, so we
        just insert them in order — entity then relation.)
        """
        for proposal in proposals:
            if proposal.confidence < self._threshold:
                report.proposals_deferred += 1
                if len(report.sample_deferred) < 10:
                    report.sample_deferred.append(proposal.reason)
                continue
            try:
                if proposal.kind == ProposalKind.CREATE_ENTITY:
                    if proposal.entity is not None:
                        self._kstore.add_entity(proposal.entity)
                        report.entities_created += 1
                        report.sample_applied.append(
                            f"entity:{proposal.entity.name}"
                        )
                elif proposal.kind == ProposalKind.ADD_RELATION:
                    if proposal.relation is not None:
                        self._kstore.add_relation(proposal.relation)
                        report.relations_created += 1
                        report.sample_applied.append(
                            f"relation:{proposal.relation.kind.value}"
                        )
                elif proposal.kind == ProposalKind.RECORD_EVENT:
                    if proposal.event is not None:
                        self._kstore.add_event(proposal.event)
                        report.events_created += 1
                        report.sample_applied.append(
                            f"event:{proposal.event.kind.value}"
                        )
            except Exception as e:
                logger.warning(
                    "[v2/reflect] failed to apply %s proposal: %s",
                    proposal.kind.value, e,
                )
