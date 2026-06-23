"""DeclineUnknown — the user asked us something we genuinely don't know.

Triggered when:
  - Intent is FACTUAL_QUESTION and we have no grounding (no kstore
    entity, no tool that handles it)
  - OR as the final fallback when no other strategy matches

Honesty over guessing. The 1.5B model used to fabricate confident
answers; this strategy returns a structured admission instead. Offers
to look it up together (sets up the next turn well) rather than
flatly stopping.
"""
from __future__ import annotations

from latticed.v2.perceive.intent import Intent
from latticed.v2.strategies.base import (
    Slot, ResponsePlan, Strategy,
)


# Templates rotated to feel natural across repeated unknowns.
_OPENERS = (
    "I don't have a confident answer for that — I don't want to guess.",
    "I'd be making that up if I answered now — that's not what I'm here for.",
    "I don't actually know that for sure.",
)
_OFFERS = (
    "Want to look it up together?",
    "Should we dig into it?",
    "Want me to grab a real source on this?",
)


class DeclineUnknown(Strategy):
    name = "decline_unknown"
    priority = 1   # lowest — only matches when nothing else does

    def matches(self, perception, kstore) -> bool:
        # Catch-all. Router also returns this when no priority-higher
        # strategy matches.
        return True

    def plan(self, perception, kstore) -> ResponsePlan:
        return ResponsePlan(
            strategy_name=self.name,
            template="{opener} {offer}",
            expected_shape="decline",
            slots=(
                Slot.choice(name="opener", options=_OPENERS),
                Slot.choice(name="offer",  options=_OFFERS),
            ),
            trace=(f"intent={perception.intent.value}",),
        )
