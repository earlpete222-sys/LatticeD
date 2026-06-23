"""Intent classifier.

Bucketizes user input into one of a small typed set of intents. The
strategy layer dispatches on this — adding a new intent usually means
adding a strategy template.

Pure rule-based for now (questions, recall patterns, share patterns,
correction phrases, etc.). Fast, predictable, easy to debug. When a
class becomes ambiguous we can layer a vector classifier on top of the
same labels without changing callers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    """The kind of move the user is making.

    Strategy layer maps (intent x state) -> response template.
    """
    SHARE_EVENT       = "share_event"        # "I spoke with my dad today"
    RECALL_QUERY      = "recall_query"       # "what do I like to do?"
    FACTUAL_QUESTION  = "factual_question"   # "when is Father's Day?"
    SCHEDULE          = "schedule"           # "remind me to call mom tomorrow"
    CHITCHAT          = "chitchat"           # "hi", "how are you"
    CORRECTION        = "correction"         # "no, that's wrong"
    META              = "meta"               # "what do you know about me?"
    REQUEST_ADVICE    = "request_advice"     # "what should I do?"
    OTHER             = "other"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    confidence: float
    reason: str   # short tag for debugging / explainability traces


# ── Patterns ────────────────────────────────────────────────────────────────
_QUESTION_MARK_RX = re.compile(r"\?\s*$")

# "what do I / where do I / when do I / how do I / how am I" — these are
# RECALL queries: the user is asking the system to recall them to themselves.
_RECALL_RX = re.compile(
    r"\b(?:what|where|when|how|who)\s+(?:do|did|am|was|were|is|are)\s+i\b"
    r"|\bmy\s+(?:favorite|usual|routine|goal|plan|preference|habit)s?\b"
    r"|\b(?:tell|remind)\s+me\s+(?:what|about)\b"
    r"|\bdo\s+i\b",
    re.IGNORECASE,
)

# Factual questions: "when is", "what's the date", "what year", etc.
# These are about THE WORLD, not the user.
_FACTUAL_RX = re.compile(
    r"\b(?:what\s+(?:is|are|was|were)|when\s+is|when\s+was|where\s+is|"
    r"who\s+(?:is|was|wrote|invented|discovered)|how\s+(?:do|does|did|much|many))\b",
    re.IGNORECASE,
)

# Meta questions about the system: "what do you know", "who are you"
_META_RX = re.compile(
    r"\b(?:what\s+do\s+you\s+know|what\s+do\s+you\s+remember|"
    r"who\s+are\s+you|what\s+are\s+you|tell\s+me\s+about\s+yourself|"
    r"how\s+do\s+you\s+work|what\s+can\s+you\s+do)\b",
    re.IGNORECASE,
)

# Schedule / reminder requests
_SCHEDULE_RX = re.compile(
    r"\b(?:remind\s+me|schedule|set\s+a\s+reminder|"
    r"don'?t\s+let\s+me\s+forget|put\s+(?:this|it|that)\s+on\s+my)\b",
    re.IGNORECASE,
)

# Corrections
_CORRECTION_RX = re.compile(
    r"\b(?:no,?\s+(?:that'?s|that\s+is)\s+(?:wrong|not\s+right|incorrect)|"
    r"actually(?:,)?\s+(?:my|i|it'?s)|"
    r"you\s+(?:got\s+that\s+)?wrong|"
    r"that'?s\s+not\s+(?:right|true|correct)|"
    r"i\s+(?:said|told\s+you|never)\s+|"
    r"correction)\b",
    re.IGNORECASE,
)

# Greetings / chitchat (only kick in if message is short)
_CHITCHAT_PHRASES = {
    "hi", "hey", "hello", "yo", "sup", "howdy",
    "good morning", "good evening", "good night", "good afternoon",
    "morning", "afternoon", "evening",
    "how are you", "how's it going", "what's up", "whats up",
    "thanks", "thank you", "thx",
    "bye", "goodbye", "see you", "later",
}

# Advice requests
_ADVICE_RX = re.compile(
    r"\b(?:what\s+should\s+i|should\s+i|what\s+(?:do\s+)?you\s+think|"
    r"any\s+advice|any\s+thoughts|what\s+would\s+you|"
    r"help\s+me\s+(?:figure|decide|choose|pick))\b",
    re.IGNORECASE,
)

# Share-event indicators: first-person past or present action verbs with
# context, OR a temporal-anchored opener (weekday, time-of-day, holiday
# date). The live failure pattern "Sunday was Father's Day I spoke with my
# dad..." needs the weekday-anchored opener to be recognized as a share.
_SHARE_RX = re.compile(
    r"^\s*(?:i|we|today|yesterday|tonight|tomorrow|"
    r"this\s+(?:morning|afternoon|evening|week|weekend)|"
    r"last\s+(?:night|week|weekend|month)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"just|earlier|recently|finally)\b",
    re.IGNORECASE,
)


def classify_intent(text: str) -> IntentResult:
    """Return the best intent label + confidence + a short reason tag.

    Priority order is deliberate: corrections and meta-questions are
    explicit and override question/recall patterns; recall/factual/advice
    are distinguished by their syntactic shape; share-event is the
    default for declarative first-person input.
    """
    t = text.strip()
    if not t:
        return IntentResult(Intent.OTHER, 0.5, "empty")

    lowered = t.lower().rstrip("!.?,")
    is_question = bool(_QUESTION_MARK_RX.search(t))

    # 1. Correction — strongest override.
    if _CORRECTION_RX.search(t):
        return IntentResult(Intent.CORRECTION, 0.95, "correction_phrase")

    # 2. Chitchat short forms
    if lowered in _CHITCHAT_PHRASES or any(
        lowered == p or lowered.startswith(p + " ") for p in _CHITCHAT_PHRASES
    ):
        return IntentResult(Intent.CHITCHAT, 0.95, "chitchat_phrase")

    # 3. Meta about the system
    if _META_RX.search(t):
        return IntentResult(Intent.META, 0.9, "meta_phrase")

    # 4. Schedule / reminder
    if _SCHEDULE_RX.search(t):
        return IntentResult(Intent.SCHEDULE, 0.9, "schedule_phrase")

    # 5. Recall query (about the user) — must check before factual since
    # "what do I like" matches both. Recall wins because "I" anchors it
    # to the user's own past statements.
    if _RECALL_RX.search(t):
        return IntentResult(Intent.RECALL_QUERY, 0.9, "recall_phrase")

    # 6. Advice request
    if _ADVICE_RX.search(t):
        return IntentResult(Intent.REQUEST_ADVICE, 0.85, "advice_phrase")

    # 7. Factual question (about the world)
    if is_question and _FACTUAL_RX.search(t):
        return IntentResult(Intent.FACTUAL_QUESTION, 0.85, "factual_phrase")

    # 8. Bare question with no specific pattern — call it factual at lower
    # confidence so the strategy layer can ask clarification if needed.
    if is_question:
        return IntentResult(Intent.FACTUAL_QUESTION, 0.55, "bare_question")

    # 9. Share event — first-person / time-anchored declarative
    if _SHARE_RX.match(t):
        return IntentResult(Intent.SHARE_EVENT, 0.85, "first_person_share")

    return IntentResult(Intent.OTHER, 0.5, "no_pattern_matched")
