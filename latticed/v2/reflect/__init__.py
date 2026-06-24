"""reflect — LatticeD v2 reflection layer.

The system improves itself by reviewing its own conversations.

Three components:
  TurnLog       — append-only record of every v2 turn (perception +
                  plan + final response + review verdict). Source of
                  truth for the reflector.
  Distiller     — reads a turn, emits typed Proposals (CREATE_ENTITY,
                  ADD_RELATION, RECORD_EVENT) with confidence scores.
                  Deterministic; uses perception's typed mentions, not
                  the response text.
  Reflector     — orchestrator: scan unprocessed turns, run distiller,
                  auto-apply high-confidence proposals to kstore, mark
                  turns processed. Idempotent.

The 1.5B model is NOT used in this layer. Reflection is a Python job
over typed data — exactly the kind of reasoning the model can't do
reliably but Python can do perfectly.
"""
from latticed.v2.reflect.turn_log import (
    TurnLog,
    TurnRecord,
)
from latticed.v2.reflect.distiller import (
    Proposal,
    ProposalKind,
    distill_turn,
    HIGH_CONFIDENCE_THRESHOLD,
)
from latticed.v2.reflect.reflector import (
    Reflector,
    ReflectionReport,
)

__all__ = [
    "TurnLog", "TurnRecord",
    "Proposal", "ProposalKind",
    "distill_turn", "HIGH_CONFIDENCE_THRESHOLD",
    "Reflector", "ReflectionReport",
]
