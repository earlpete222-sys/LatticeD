"""perceive — LatticeD v2 perception layer.

Turns raw user input into structured Perception records. Deterministic
or near-deterministic — no open model generation happens here. The
perception layer is the FIRST thing every v2 turn does; everything
downstream consumes typed records, never the original string.

Top-level entry point:

    perception = perceive(user_input="...", now=datetime.now(tz=UTC),
                          kstore=kstore_instance)

The Perception object carries: resolved temporal references, extracted
entities, intent classification, and mood tag. All of these are
immutable typed records the strategy + narration layers can rely on.
"""
from latticed.v2.perceive.temporal import (
    TemporalRef,
    TemporalGrain,
    resolve_temporal_refs,
    holiday_date_for,
    KNOWN_HOLIDAYS,
)
from latticed.v2.perceive.entities import (
    Mention,
    extract_mentions,
)
from latticed.v2.perceive.intent import (
    Intent,
    classify_intent,
)
from latticed.v2.perceive.mood import detect_mood
from latticed.v2.perceive.perception import (
    Perception,
    perceive,
)

__all__ = [
    "TemporalRef", "TemporalGrain", "resolve_temporal_refs",
    "holiday_date_for", "KNOWN_HOLIDAYS",
    "Mention", "extract_mentions",
    "Intent", "classify_intent",
    "detect_mood",
    "Perception", "perceive",
]
