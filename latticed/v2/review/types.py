"""Reviewer typed contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from latticed.v2.narrate import NarratedResponse


class Verdict(str, Enum):
    """The reviewer's overall judgment on a NarratedResponse."""
    APPROVE = "approve"
    APPROVE_WITH_NOTES = "approve_with_notes"
    REJECT  = "reject"


class Severity(str, Enum):
    """How serious a single axis failure is.

    FATAL  — any fatal failure means REJECT.
    WARN   — accumulates; multiple warnings can also REJECT (threshold).
    INFO   — notes only; never affects verdict.
    """
    FATAL = "fatal"
    WARN  = "warn"
    INFO  = "info"


@dataclass(frozen=True)
class AxisScore:
    """One reviewer check's result.

    axis: short identifier ('banned_plural', 'shape_two_beat', ...)
    passed: True if the check accepted the output
    reason: short failure description (empty when passed)
    severity: how this failure feeds the final verdict
    """
    axis: str
    passed: bool
    reason: str = ""
    severity: Severity = Severity.WARN


@dataclass(frozen=True)
class ReviewReport:
    """The full review outcome — every axis score plus the consolidated
    verdict. Carried forward into FinalizedResponse so the operator (or
    a 'why did you say that' endpoint) can see exactly which checks
    fired and why."""
    verdict: Verdict
    axes: tuple[AxisScore, ...]
    expected_shape: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.verdict in (Verdict.APPROVE, Verdict.APPROVE_WITH_NOTES)

    @property
    def fatal_failures(self) -> tuple[AxisScore, ...]:
        return tuple(a for a in self.axes
                     if not a.passed and a.severity == Severity.FATAL)

    @property
    def warnings(self) -> tuple[AxisScore, ...]:
        return tuple(a for a in self.axes
                     if not a.passed and a.severity == Severity.WARN)


@dataclass(frozen=True)
class FinalizedResponse:
    """The end-to-end result of plan → narrate → review → (optional fallback).

    text is what the user sees. report is the audit trail. used_fallback
    is true when the narrated output was rejected by review and the
    deterministic fallback path was used instead.
    """
    text: str
    report: ReviewReport
    strategy_name: str
    used_fallback: bool = False
    fallback_reason: Optional[str] = None
