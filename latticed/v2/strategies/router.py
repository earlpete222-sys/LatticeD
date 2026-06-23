"""Strategy router.

Iterates ALL_STRATEGIES in descending priority order, returns the first
that matches the current (perception, kstore). DeclineUnknown matches
everything at priority 1, so the router always returns something —
"I don't know" is a valid response, "no strategy matched" should never
reach the user.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from latticed.v2.strategies.acknowledge_event import AcknowledgeEvent
from latticed.v2.strategies.recall_from_history import RecallFromHistory
from latticed.v2.strategies.decline_unknown import DeclineUnknown
from latticed.v2.strategies.ask_clarification import AskClarification
from latticed.v2.strategies.schedule_event import ScheduleEvent

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore
    from latticed.v2.perceive.perception import Perception
    from latticed.v2.strategies.base import Strategy


# Tuple is intentional: ordering is by priority (desc), built once at
# module import. Adding a strategy = appending here + ensuring priority
# slots it in the right place.
ALL_STRATEGIES: tuple = (
    RecallFromHistory(),   # priority 80
    ScheduleEvent(),       # priority 75
    AskClarification(),    # priority 70
    AcknowledgeEvent(),    # priority 50
    DeclineUnknown(),      # priority  1 (catch-all)
)


def choose_strategy(perception: "Perception", kstore: "KStore") -> "Strategy":
    """Return the first matching strategy in priority order. Always
    returns something — DeclineUnknown's matches() returns True."""
    ordered = sorted(ALL_STRATEGIES, key=lambda s: -s.priority)
    for s in ordered:
        if s.matches(perception, kstore):
            return s
    # Defensive: DeclineUnknown.matches always returns True, so this
    # is unreachable, but keep it explicit so any future refactor that
    # removes the catch-all fails loudly rather than silently.
    raise RuntimeError("No strategy matched and no catch-all present")
