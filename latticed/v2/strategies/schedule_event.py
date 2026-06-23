"""ScheduleEvent — the user wants a reminder or scheduled action.

"Remind me to call mom tomorrow" / "schedule the dentist for Friday"

This v2 strategy confirms what we heard (the what + when) and asks
to confirm before committing — scheduling actually persisting is a
later sprint, but the confirmation shape is correct from day one.

Slots are deterministic when perception gave us what we need; we
fall back to clarification language when the temporal anchor is
missing.
"""
from __future__ import annotations

import re

from latticed.v2.perceive.intent import Intent
from latticed.v2.strategies.base import (
    Slot, ResponsePlan, Strategy,
)


# Crude what-extractor: grab the verb phrase after the schedule trigger.
_WHAT_RX = re.compile(
    r"\b(?:remind\s+me\s+to|schedule|put\s+(?:this|it|that)\s+on\s+my\s+\w+\s+to|"
    r"don'?t\s+let\s+me\s+forget\s+to|set\s+a\s+reminder\s+to|"
    r"reminder\s+to)\s+(.+?)(?:\s+(?:on|at|this|next|tomorrow|today|tonight)|[,.?!]|$)",
    re.IGNORECASE,
)


def _extract_what(user_input: str) -> str:
    """Best-effort extraction of the action phrase. Returns 'that' as a
    safe fallback so the confirmation template still reads naturally."""
    m = _WHAT_RX.search(user_input)
    if m:
        return m.group(1).strip().rstrip(".,!? ")
    return "that"


class ScheduleEvent(Strategy):
    name = "schedule_event"
    priority = 75

    def matches(self, perception, kstore) -> bool:
        return perception.intent == Intent.SCHEDULE

    def plan(self, perception, kstore) -> ResponsePlan:
        what = _extract_what(perception.user_input)
        when = (
            perception.temporal_refs[0].text
            if perception.temporal_refs else None
        )

        if when:
            confirmation = (
                f"Got it — you want to be reminded to {what} on {when}. "
                f"Want me to lock that in?"
            )
            trace = (f"what={what}", f"when={when}")
        else:
            confirmation = (
                f"I can set a reminder to {what} — when do you want to be reminded?"
            )
            trace = (f"what={what}", "when=missing")

        return ResponsePlan(
            strategy_name=self.name,
            template="{confirmation}",
            expected_shape="schedule_confirm",
            slots=(Slot.literal(name="confirmation", value=confirmation),),
            trace=trace,
        )
