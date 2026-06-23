"""Mood tagger.

Maps user input to a Mood enum based on a small keyword lexicon.
Deliberately coarse — we want a reliable signal, not nuance. The
strategy layer uses mood to pick acknowledgment tone (warmer for sad,
energetic for proud, calm for tired).

For the v2 base, deterministic + cheap is better than slightly more
accurate but slow + opaque. A vector classifier can be added later if
the keyword approach hits its ceiling.
"""
from __future__ import annotations

import re
from typing import Optional

from latticed.v2.kstore.schema import Mood


# Each mood maps to a set of indicator phrases. Order matters only for
# tie-breaking on equal hit-counts (earlier moods win — they're listed
# in priority order: strong negatives first because users surface them
# more deliberately than positives).
_MOOD_LEXICON: list[tuple[Mood, tuple[str, ...]]] = [
    (Mood.ANXIOUS, (
        "anxious", "anxiety", "worried", "worry", "nervous", "panicky",
        "stressed", "stressing", "overwhelmed", "on edge", "freaking out",
    )),
    (Mood.FRUSTRATED, (
        "frustrated", "frustrating", "annoyed", "annoying", "angry", "pissed",
        "irritated", "fed up", "had it", "can't stand", "argh", "ugh",
        "drives me crazy",
    )),
    (Mood.SAD, (
        "sad", "down", "miserable", "depressed", "blue", "hurting",
        "crying", "tearing up", "lonely", "alone", "missing",
        "lost", "grief", "grieving",
    )),
    (Mood.TIRED, (
        "tired", "exhausted", "drained", "wiped", "worn out", "beat",
        "sleepy", "burned out", "burnt out", "running on empty",
    )),
    (Mood.PRIDE, (
        "proud", "accomplished", "nailed it", "crushed it", "smashed it",
        "won", "earned", "achievement", "milestone",
    )),
    (Mood.JOY, (
        "happy", "joyful", "thrilled", "elated", "amazing", "wonderful",
        "fantastic", "great day", "best day", "loved", "love it",
        "having a blast", "great conversation", "great time",
    )),
    (Mood.CALM, (
        "peaceful", "calm", "relaxed", "centered", "settled", "at ease",
        "quiet day", "slow morning",
    )),
    (Mood.CURIOUS, (
        "curious", "wondering", "thinking about", "been thinking",
        "what if", "how come", "i wonder",
    )),
]


def _has_phrase(text_lower: str, phrase: str) -> bool:
    """Whole-word/phrase match (no substring false positives)."""
    pattern = r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])"
    return re.search(pattern, text_lower) is not None


def detect_mood(text: str) -> Optional[Mood]:
    """Return the most likely Mood, or None if no signal is present.

    'None' is informative: the strategy layer can use it to mean
    'neutral/unmarked' rather than guessing.
    """
    if not text:
        return None
    lowered = text.lower()
    scores: dict[Mood, int] = {}
    for mood, phrases in _MOOD_LEXICON:
        hits = sum(1 for p in phrases if _has_phrase(lowered, p))
        if hits:
            scores[mood] = hits
    if not scores:
        return None
    # Highest hit count wins; ties broken by lexicon order (priority).
    best_count = max(scores.values())
    for mood, _ in _MOOD_LEXICON:
        if scores.get(mood) == best_count:
            return mood
    return None
