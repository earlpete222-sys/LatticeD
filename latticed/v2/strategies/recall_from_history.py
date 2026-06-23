"""RecallFromHistory — the user asked what we know about them.

"What do I like to do?" / "What are my goals?" / "Who's in my life?"

This strategy answers DETERMINISTICALLY from kstore. No model call
needed — recall is a query, not a generation. The 1.5B model used to
invent activities the user never mentioned ("you like rock climbing")
because it was asked to GENERATE a recall. Now we look it up.

If kstore has the answer: format it naturally and return it. No
follow-up question (recall replies don't need one — the user asked
a specific question, they get a specific answer).

If kstore doesn't have the answer: hand off to AskClarification via
the router (this strategy's match() returns False when nothing
relevant is stored).
"""
from __future__ import annotations

import re

from latticed.v2.kstore.schema import (
    EntityKind, RelationKind, USER_ENTITY_ID,
)
from latticed.v2.perceive.intent import Intent
from latticed.v2.strategies.base import (
    Slot, ResponsePlan, Strategy, SlotConstraint,
)


# Map common recall-query phrasings to (relation_kind, friendly_verb).
# The router for "what do I X?" → which relation type to look up.
_RECALL_PATTERNS: list[tuple[re.Pattern[str], RelationKind, str]] = [
    (re.compile(r"\bwhat\s+(?:do\s+)?i\s+(?:like|enjoy|love)\b", re.IGNORECASE),
     RelationKind.ENJOYS, "enjoy"),
    (re.compile(r"\bwhat\s+do\s+i\s+do\s+for\s+fun\b", re.IGNORECASE),
     RelationKind.ENJOYS, "enjoy"),
    (re.compile(r"\bwhat\s+(?:do\s+)?i\s+(?:dislike|hate)\b", re.IGNORECASE),
     RelationKind.DISLIKES, "dislike"),
    (re.compile(r"\bwhat\s+do\s+i\s+avoid\b", re.IGNORECASE),
     RelationKind.AVOIDS, "avoid"),
    (re.compile(r"\bwhere\s+do\s+i\s+live\b", re.IGNORECASE),
     RelationKind.LIVES_IN, "live in"),
    (re.compile(r"\bwhere\s+do\s+i\s+work\b", re.IGNORECASE),
     RelationKind.WORKS_AT, "work at"),
    (re.compile(r"\bwho\s+(?:is\s+)?(?:my\s+)?(family|friends?)\b", re.IGNORECASE),
     RelationKind.FAMILY_OF, "have in your family"),
]


def _detect_recall_kind(user_input: str):
    for pat, rel, verb in _RECALL_PATTERNS:
        if pat.search(user_input):
            return rel, verb
    return None, None


def _format_list(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


class RecallFromHistory(Strategy):
    name = "recall_from_history"
    priority = 80    # higher than acknowledge_event so recall wins on ambiguity

    def matches(self, perception, kstore) -> bool:
        if perception.intent != Intent.RECALL_QUERY:
            return False
        rel, _ = _detect_recall_kind(perception.user_input)
        if rel is None:
            return False
        # Only match if we actually have entities to return -- otherwise
        # let AskClarification handle the empty-store case.
        results = kstore.recall_attribute(USER_ENTITY_ID, rel)
        return len(results) > 0

    def plan(self, perception, kstore) -> ResponsePlan:
        rel, verb = _detect_recall_kind(perception.user_input)
        entities = kstore.recall_attribute(USER_ENTITY_ID, rel)
        names = [e.name for e in entities]
        # Single-shot deterministic answer. No model call, no invention.
        if len(names) == 1:
            text = f"You {verb} {names[0]}, from what you've told me."
        else:
            text = f"You {verb} {_format_list(names)}, from what you've told me."

        return ResponsePlan(
            strategy_name=self.name,
            template="{recall}",
            expected_shape="recall",
            slots=(Slot.literal(name="recall", value=text),),
            trace=(
                f"relation={rel.value}",
                f"results={len(names)}",
            ),
        )
