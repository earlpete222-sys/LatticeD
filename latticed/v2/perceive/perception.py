"""Perception — the top-level v2 entry point for raw user input.

    perception = perceive(
        user_input="Today is Father's Day, I spoke with my dad",
        now=datetime.now(tz=local_tz),
        kstore=kstore,
    )

Returns an immutable typed record carrying everything the strategy
layer needs to dispatch on. No open model generation in this layer —
the result is deterministic given (input, now, kstore-state).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from latticed.v2.kstore.schema import Mood

from latticed.v2.perceive.entities import Mention, extract_mentions
from latticed.v2.perceive.intent import Intent, IntentResult, classify_intent
from latticed.v2.perceive.mood import detect_mood
from latticed.v2.perceive.temporal import (
    TemporalRef,
    resolve_temporal_refs,
)

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore


@dataclass(frozen=True)
class Perception:
    """The structured view of a single user utterance.

    All fields are immutable. ``trace`` accumulates short reason tags
    from each sub-parser so a debug endpoint can show "why did you
    classify it this way?" without re-running the pipeline.
    """
    user_input: str
    now: datetime
    intent: Intent
    intent_confidence: float
    mood: Optional[Mood]
    mentions: tuple[Mention, ...]
    temporal_refs: tuple[TemporalRef, ...]
    trace: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_question(self) -> bool:
        return self.user_input.strip().endswith("?")

    @property
    def specific_detail(self) -> Optional[str]:
        """Best guess at the single most specific detail the user
        mentioned — used by strategy templates that need to anchor a
        reflection or question. Picks the highest-confidence mention,
        falling back to the first resolved temporal ref."""
        if self.mentions:
            best = max(self.mentions, key=lambda m: m.confidence)
            return best.canonical
        if self.temporal_refs:
            return self.temporal_refs[0].text
        return None

    def mentions_of(self, kind) -> tuple[Mention, ...]:
        """All mentions whose kind matches (single kind or iterable)."""
        if hasattr(kind, "__iter__") and not isinstance(kind, str):
            kinds = set(kind)
            return tuple(m for m in self.mentions if m.kind in kinds)
        return tuple(m for m in self.mentions if m.kind == kind)


def perceive(
    user_input: str,
    *,
    now: datetime,
    kstore: Optional["KStore"] = None,
) -> Perception:
    """Run the full perception pipeline on a single utterance.

    Order matters slightly: temporal refs are resolved first so that
    mention extraction doesn't accidentally treat 'Father's Day' as a
    bare person mention. (entities.py already avoids that by not
    treating bare 'father' alone as a Mention without 'my', but the
    ordering keeps the trace clean.)
    """
    if now.tzinfo is None:
        raise ValueError("perceive: now must be timezone-aware")

    temporal = resolve_temporal_refs(user_input, now)
    mentions = extract_mentions(user_input, kstore=kstore)
    intent_res: IntentResult = classify_intent(user_input)
    mood = detect_mood(user_input)

    trace = [
        f"intent:{intent_res.intent.value}({intent_res.reason})",
        f"intent_confidence:{intent_res.confidence:.2f}",
        f"mood:{mood.value if mood else 'none'}",
        f"mentions:{len(mentions)}",
        f"temporal_refs:{len(temporal)}",
    ]

    return Perception(
        user_input=user_input,
        now=now,
        intent=intent_res.intent,
        intent_confidence=intent_res.confidence,
        mood=mood,
        mentions=mentions,
        temporal_refs=temporal,
        trace=tuple(trace),
    )
