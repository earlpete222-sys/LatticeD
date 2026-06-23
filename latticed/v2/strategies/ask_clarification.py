"""AskClarification — perception was thin or ambiguous; ask for more.

Triggered when:
  - intent_confidence is below threshold, OR
  - intent is RECALL_QUERY but kstore has nothing relevant
    (the recall_from_history strategy passed because results were empty)
  - intent is OTHER (no pattern matched)

The Sprint 47 lesson: "I need help" should be a winning move, not a
failure. This strategy makes asking a targeted clarification the
RIGHT response in these conditions, rather than forcing the model
to generate something it doesn't have material for.
"""
from __future__ import annotations

from latticed.v2.kstore.schema import RelationKind, USER_ENTITY_ID
from latticed.v2.perceive.intent import Intent
from latticed.v2.strategies.base import (
    Slot, ResponsePlan, Strategy,
)
from latticed.v2.strategies.recall_from_history import _detect_recall_kind


# Confidence below which we always clarify, regardless of intent.
LOW_CONFIDENCE_THRESHOLD = 0.65


class AskClarification(Strategy):
    name = "ask_clarification"
    priority = 70   # below recall_from_history (80), above acknowledge (50)

    def matches(self, perception, kstore) -> bool:
        # Case 1: a recall query we can't answer because the store is empty
        if perception.intent == Intent.RECALL_QUERY:
            rel, _ = _detect_recall_kind(perception.user_input)
            if rel is not None:
                results = kstore.recall_attribute(USER_ENTITY_ID, rel)
                return len(results) == 0
        # Case 2: intent is OTHER -- no pattern matched
        if perception.intent == Intent.OTHER:
            return True
        # Case 3: very low confidence overall
        if perception.intent_confidence < LOW_CONFIDENCE_THRESHOLD:
            return True
        return False

    def plan(self, perception, kstore) -> ResponsePlan:
        # Recall-empty case: name what we DON'T have and ask the user
        # to tell us, so the kstore can grow.
        if perception.intent == Intent.RECALL_QUERY:
            rel, verb = _detect_recall_kind(perception.user_input)
            if rel is not None:
                question = (
                    f"I don't have anything stored about what you {verb} yet. "
                    f"What would you want me to remember?"
                )
                return ResponsePlan(
                    strategy_name=self.name,
                    template="{question}",
                    expected_shape="clarification",
                    slots=(Slot.literal(name="question", value=question),),
                    trace=(f"reason=recall_empty_for_{rel.value}",),
                )

        # General clarification: short, honest, invites a more specific share.
        question = (
            "I want to make sure I get this right — "
            "can you say a bit more about what you're sharing?"
        )
        return ResponsePlan(
            strategy_name=self.name,
            template="{question}",
            expected_shape="clarification",
            slots=(Slot.literal(name="question", value=question),),
            trace=(f"reason=low_conf_or_other",
                   f"intent={perception.intent.value}",
                   f"conf={perception.intent_confidence:.2f}"),
        )
