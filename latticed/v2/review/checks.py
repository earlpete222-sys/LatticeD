"""Deterministic axis checks for the reviewer.

No model calls in this module. Every check is a pure function over
(text, perception, expected_shape) returning an AxisScore.

Adding a new check: implement here, register in reviewer.Reviewer.
"""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from latticed.v2.perceive.temporal import KNOWN_HOLIDAYS, holiday_date_for
from latticed.v2.review.types import AxisScore, Severity

if TYPE_CHECKING:
    from latticed.v2.perceive.perception import Perception


# ── Banned plurals (we/us/our as whole words) ──────────────────────────────
_BANNED_PLURAL_RX = re.compile(
    r"\b(?:we|us|our|we're|we've|we'll|we'd|ourselves)\b",
    re.IGNORECASE,
)


def check_no_banned_plural(text: str) -> AxisScore:
    m = _BANNED_PLURAL_RX.search(text or "")
    if m:
        return AxisScore(
            axis="no_banned_plural",
            passed=False,
            reason=f"output uses first-person plural: '{m.group(0)}'",
            severity=Severity.FATAL,
        )
    return AxisScore(axis="no_banned_plural", passed=True)


# ── Role flip (output attributes a reply to the user) ──────────────────────
_ROLE_FLIP_RX = re.compile(
    r"^\s*(?:you|user|the user)\s*"
    r"(?:said|wrote|asked|replied|responded|stated)?\s*[:—\-]\s*[\"“‘]",
    re.IGNORECASE | re.MULTILINE,
)


def check_no_role_flip(text: str) -> AxisScore:
    if _ROLE_FLIP_RX.search(text or ""):
        return AxisScore(
            axis="no_role_flip",
            passed=False,
            reason="output attributes a quoted reply to the user",
            severity=Severity.FATAL,
        )
    return AxisScore(axis="no_role_flip", passed=True)


# ── Leaked internals (prompt scaffolding, tool calls, etc.) ────────────────
_LEAKED_PHRASES = (
    "context blueprint",
    "system prompt",
    "structured analysis of your query",
    "the user's request",
    "operating discipline",
    "reflection loop",
    "{tool",      # tool-call JSON fragments
    '"tool":',
    '"params":',
    "[SHELL:",
    "<think>",
    "</think>",
)


def check_no_leaked_internals(text: str) -> AxisScore:
    lo = (text or "").lower()
    for marker in _LEAKED_PHRASES:
        if marker.lower() in lo:
            return AxisScore(
                axis="no_leaked_internals",
                passed=False,
                reason=f"output contains internal marker: {marker!r}",
                severity=Severity.FATAL,
            )
    return AxisScore(axis="no_leaked_internals", passed=True)


# ── Shape check (per expected_shape) ───────────────────────────────────────
def _two_beat(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t.endswith("?"):
        return False, "does not end with '?'"
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", t) if p.strip()]
    if len(parts) < 2:
        return False, "needs at least one declarative sentence before the question"
    if not any(not p.endswith("?") and len(p.split()) >= 3 for p in parts[:-1]):
        return False, "declarative half is too short or itself a question"
    return True, ""


def _recall(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, "empty"
    # Recall replies are declarative; ending with '?' would imply the system
    # is asking, not recalling.
    if t.endswith("?"):
        return False, "recall reply should not be a question"
    if len(t.split()) < 3:
        return False, "recall reply too short"
    return True, ""


def _decline(text: str) -> tuple[bool, str]:
    t = (text or "").lower()
    if not t.strip():
        return False, "empty"
    if not any(marker in t for marker in (
        "don't", "do not", "making", "not sure", "i'm not", "not confident",
    )):
        return False, "decline reply should signal uncertainty"
    return True, ""


def _clarification(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if "?" not in t:
        return False, "clarification reply should include a question"
    return True, ""


def _schedule_confirm(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if "?" not in t:
        return False, "schedule confirm should include a confirm question"
    return True, ""


_SHAPE_CHECKERS = {
    "two_beat":         _two_beat,
    "recall":           _recall,
    "decline":          _decline,
    "clarification":    _clarification,
    "schedule_confirm": _schedule_confirm,
    "free":             lambda t: (bool((t or "").strip()), "" if (t or "").strip() else "empty"),
}


def check_shape(text: str, expected_shape: str) -> AxisScore:
    checker = _SHAPE_CHECKERS.get(expected_shape)
    if checker is None:
        return AxisScore(
            axis=f"shape_{expected_shape}",
            passed=False,
            reason=f"unknown expected_shape: {expected_shape!r}",
            severity=Severity.WARN,
        )
    ok, reason = checker(text)
    return AxisScore(
        axis=f"shape_{expected_shape}",
        passed=ok,
        reason=reason if not ok else "",
        severity=Severity.FATAL if not ok else Severity.WARN,
    )


# ── Anchor reference (output mentions a real perception anchor) ────────────
def check_anchor_references(
    text: str,
    perception: "Perception",
    *,
    only_for_shapes: tuple[str, ...] = ("two_beat", "schedule_confirm"),
    expected_shape: str = "free",
) -> AxisScore:
    """For shapes where reflection-anchoring matters, verify the output
    actually references something the user mentioned. Otherwise the
    reflection is invented (the 'amazing personality' failure mode)."""
    if expected_shape not in only_for_shapes:
        return AxisScore(axis="anchor_references", passed=True,
                         reason="not applicable", severity=Severity.INFO)
    anchors: list[str] = []
    for m in perception.mentions:
        anchors.append(m.canonical)
        if m.relation_hint:
            anchors.append(m.relation_hint)
    for t in perception.temporal_refs:
        anchors.append(t.text)
    if not anchors:
        # Nothing to anchor to -- can't fail this check
        return AxisScore(axis="anchor_references", passed=True,
                         reason="no anchors in perception", severity=Severity.INFO)
    lo = (text or "").lower()
    hits = [a for a in anchors if a.lower() in lo]
    if hits:
        return AxisScore(axis="anchor_references", passed=True,
                         reason=f"matched: {hits[:3]}", severity=Severity.INFO)
    return AxisScore(
        axis="anchor_references",
        passed=False,
        reason=f"output references none of {anchors[:5]}",
        severity=Severity.FATAL,
    )


# ── No invented dates (any date/holiday mentioned matches perception) ──────
def check_no_invented_dates(
    text: str,
    perception: "Perception",
) -> AxisScore:
    """If the output names a date, weekday, or known holiday, it must
    match what perception resolved -- otherwise the system is asserting
    a calendar fact it doesn't know."""
    lo = (text or "").lower()
    # If the output mentions a known holiday, verify it's the same one
    # perception resolved (or perception didn't mention any date).
    perceived_holiday_dates: set[date] = set()
    for t in perception.temporal_refs:
        # Only treat resolved holiday refs (full text contains a known
        # holiday name) as anchors here.
        for name in KNOWN_HOLIDAYS:
            if name in t.text.lower():
                perceived_holiday_dates.add(t.when.date())
                break

    for name in KNOWN_HOLIDAYS:
        if name in lo:
            # Output names this holiday. Compare against perception's
            # resolved date if any.
            if perceived_holiday_dates:
                # We have to compute the candidate date for the current
                # context year (use perception.now.year).
                candidate = holiday_date_for(name, perception.now.year)
                if candidate is None:
                    continue
                if candidate in perceived_holiday_dates:
                    # Output names the same holiday perception saw -- fine.
                    return AxisScore(axis="no_invented_dates", passed=True)
                # If output names a DIFFERENT holiday than perception
                # resolved, that's a fabrication.
                return AxisScore(
                    axis="no_invented_dates", passed=False,
                    reason=f"output mentions {name!r} but perception "
                           f"resolved {perceived_holiday_dates}",
                    severity=Severity.FATAL,
                )
            # Output mentions a holiday perception didn't see at all --
            # the system is asserting something out of nowhere.
            return AxisScore(
                axis="no_invented_dates", passed=False,
                reason=f"output mentions {name!r} but perception found no holiday",
                severity=Severity.FATAL,
            )

    return AxisScore(axis="no_invented_dates", passed=True)


# ── Length cap ──────────────────────────────────────────────────────────────
MAX_OUTPUT_CHARS = 700   # chat-path responses should be brief


def check_length(text: str) -> AxisScore:
    n = len(text or "")
    if n > MAX_OUTPUT_CHARS:
        return AxisScore(
            axis="length",
            passed=False,
            reason=f"output too long ({n} > {MAX_OUTPUT_CHARS} chars)",
            severity=Severity.WARN,
        )
    return AxisScore(axis="length", passed=True)
