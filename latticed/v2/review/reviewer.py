"""Reviewer + review_and_finalize entry point.

Reviewer.review() runs every registered axis check and consolidates
into a ReviewReport. review_and_finalize() is the full pipeline:

    perception  +  plan  ->  narrate  ->  review  ->  approve? ship
                                                 \\
                                                  ->  reject?  fallback path
                                                              ->  review again
                                                                       \\
                                                                        -> ship safe minimal
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from latticed.v2.narrate import narrate, NarratedResponse
from latticed.v2.strategies.base import (
    NarratorBackend, ResponsePlan, Slot, StubNarratorBackend,
)
from latticed.v2.review.checks import (
    check_no_banned_plural,
    check_no_role_flip,
    check_no_leaked_internals,
    check_shape,
    check_anchor_references,
    check_no_invented_dates,
    check_length,
)
from latticed.v2.review.types import (
    AxisScore, FinalizedResponse, ReviewReport, Severity, Verdict,
)

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore
    from latticed.v2.perceive.perception import Perception


logger = logging.getLogger("latticed.v2.review")


# Minimum safe reply when even the fallback path fails review. Honest,
# short, structurally valid — and impossible to fail any deterministic
# check (no plurals, no role flip, no internals, no holidays, no anchors
# required for "free" shape).
MINIMUM_SAFE_REPLY = (
    "I want to make sure I get this right — could you say a bit more about that?"
)


class Reviewer:
    """Runs every deterministic check + consolidates into ReviewReport."""

    def review(
        self,
        response: NarratedResponse,
        perception: "Perception",
    ) -> ReviewReport:
        axes: list[AxisScore] = [
            check_no_banned_plural(response.text),
            check_no_role_flip(response.text),
            check_no_leaked_internals(response.text),
            check_shape(response.text, response.expected_shape),
            check_anchor_references(
                response.text, perception,
                expected_shape=response.expected_shape,
            ),
            check_no_invented_dates(response.text, perception),
            check_length(response.text),
        ]
        return _consolidate(axes, response.expected_shape)


def _consolidate(
    axes: list[AxisScore],
    expected_shape: str,
) -> ReviewReport:
    """Apply verdict rules to a set of axis scores.

    Any FATAL failure → REJECT.
    >=2 WARN failures   → REJECT.
    1 WARN failure      → APPROVE_WITH_NOTES.
    0 failures          → APPROVE.
    """
    fatals  = [a for a in axes if not a.passed and a.severity == Severity.FATAL]
    warns   = [a for a in axes if not a.passed and a.severity == Severity.WARN]

    if fatals:
        verdict = Verdict.REJECT
        reasons = tuple(f"{a.axis}: {a.reason}" for a in fatals)
    elif len(warns) >= 2:
        verdict = Verdict.REJECT
        reasons = tuple(f"{a.axis}: {a.reason}" for a in warns)
    elif warns:
        verdict = Verdict.APPROVE_WITH_NOTES
        reasons = tuple(f"{a.axis}: {a.reason}" for a in warns)
    else:
        verdict = Verdict.APPROVE
        reasons = ()

    return ReviewReport(
        verdict=verdict,
        axes=tuple(axes),
        expected_shape=expected_shape,
        reasons=reasons,
    )


def _fallback_only_backend(plan: ResponsePlan) -> StubNarratorBackend:
    """Build a stub backend that returns each MODEL slot's
    fallback_value. Used to render the plan's "safe" form when the
    real narration was rejected."""
    canned = {}
    for slot in plan.slots:
        if slot.fallback_value:
            canned[slot.name] = slot.fallback_value
    return StubNarratorBackend(canned)


async def review_and_finalize(
    *,
    perception: "Perception",
    plan: ResponsePlan,
    backend: NarratorBackend,
    kstore: "KStore",
    reviewer: "Reviewer | None" = None,
) -> FinalizedResponse:
    """Full pipeline: narrate → review → (fallback on reject) → ship.

    Returns FinalizedResponse with the final user-facing text plus the
    full review report. Caller decides whether to log/expose the report
    (production: log only; dev/debug: surface for "why did you say that").
    """
    reviewer = reviewer or Reviewer()

    # 1. Narrate with the real backend.
    response = await narrate(
        plan, backend=backend, kstore=kstore, perception=perception
    )

    # 2. Review.
    report = reviewer.review(response, perception)
    if report.passed:
        return FinalizedResponse(
            text=response.text,
            report=report,
            strategy_name=plan.strategy_name,
            used_fallback=False,
        )

    logger.warning(
        "[review] strategy=%s rejected: %s -- trying fallback path",
        plan.strategy_name, report.reasons,
    )

    # 3. Reject path: re-narrate using fallback-only stub backend.
    fb_backend = _fallback_only_backend(plan)
    fb_response = await narrate(
        plan, backend=fb_backend, kstore=kstore, perception=perception,
    )
    fb_report = reviewer.review(fb_response, perception)

    if fb_report.passed:
        return FinalizedResponse(
            text=fb_response.text,
            report=fb_report,
            strategy_name=plan.strategy_name,
            used_fallback=True,
            fallback_reason="; ".join(report.reasons[:3]),
        )

    # 4. Even the fallback failed review -- ship minimum safe reply.
    logger.error(
        "[review] fallback also rejected for strategy=%s: %s -- using minimum safe reply",
        plan.strategy_name, fb_report.reasons,
    )
    minimum_report = ReviewReport(
        verdict=Verdict.APPROVE_WITH_NOTES,
        axes=(AxisScore(axis="minimum_safe", passed=True,
                        reason="degraded to safe minimum",
                        severity=Severity.INFO),),
        expected_shape="free",
        reasons=("plan_and_fallback_both_rejected",),
    )
    return FinalizedResponse(
        text=MINIMUM_SAFE_REPLY,
        report=minimum_report,
        strategy_name=plan.strategy_name,
        used_fallback=True,
        fallback_reason="plan+fallback both rejected",
    )
