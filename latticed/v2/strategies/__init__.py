"""strategies — LatticeD v2 response strategy library.

A Strategy maps a (perception × kstore state) to a typed ResponsePlan.
Each Plan has named slots with constraints; the narrator fills them
(deterministic / choice / kstore lookup / constrained model call) and
assembles the final reply.

The 1.5B model is called ONLY through model slots, with tight per-slot
prompts (~50 tokens output max) and validators that enforce factual
fidelity (no inventions, no banned plurals, references real mentions).

Public API:
    from latticed.v2.strategies import choose_strategy, ALL_STRATEGIES
    strategy = choose_strategy(perception, kstore)
    plan = strategy.plan(perception, kstore)
"""
from latticed.v2.strategies.base import (
    Slot,
    SlotKind,
    SlotConstraint,
    ResponsePlan,
    Strategy,
    NarratorBackend,
    StubNarratorBackend,
)
from latticed.v2.strategies.acknowledge_event import AcknowledgeEvent
from latticed.v2.strategies.recall_from_history import RecallFromHistory
from latticed.v2.strategies.decline_unknown import DeclineUnknown
from latticed.v2.strategies.ask_clarification import AskClarification
from latticed.v2.strategies.schedule_event import ScheduleEvent
from latticed.v2.strategies.router import choose_strategy, ALL_STRATEGIES

__all__ = [
    "Slot", "SlotKind", "SlotConstraint", "ResponsePlan",
    "Strategy", "NarratorBackend", "StubNarratorBackend",
    "AcknowledgeEvent", "RecallFromHistory", "DeclineUnknown",
    "AskClarification", "ScheduleEvent",
    "choose_strategy", "ALL_STRATEGIES",
]
