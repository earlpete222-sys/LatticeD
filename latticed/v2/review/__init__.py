"""review — LatticeD v2 always-on reviewer.

Every NarratedResponse passes through review() before reaching the
user. The reviewer is the verification gate -- it doesn't generate,
it judges.

Sprint 52 implements the deterministic axis checks (no model call
required). A model-based "judge" axis can be added later as one more
AxisScore feeding the same ReviewReport; the public API stays the
same.

Public API:
    from latticed.v2.review import Reviewer, review_and_finalize
    final = await review_and_finalize(
        perception=p,
        plan=plan,
        backend=narrator_backend,
        kstore=kstore,
    )
    # final.text is the user-facing string
    # final.report is the full audit trail
"""
from latticed.v2.review.types import (
    Verdict, AxisScore, Severity, ReviewReport, FinalizedResponse,
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
from latticed.v2.review.reviewer import Reviewer, review_and_finalize

__all__ = [
    "Verdict", "AxisScore", "Severity", "ReviewReport", "FinalizedResponse",
    "check_no_banned_plural", "check_no_role_flip",
    "check_no_leaked_internals", "check_shape",
    "check_anchor_references", "check_no_invented_dates",
    "check_length",
    "Reviewer", "review_and_finalize",
]
