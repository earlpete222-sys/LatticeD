"""Entity extractor.

Finds mentions of typed entities (people, places, activities, holidays,
topics) in user input. Three passes, in priority order:

  1. KStore lookup — anything we already know about (case-insensitive
     name + alias match). Highest confidence; the system already has
     a typed record for it.
  2. Relationship-pattern extraction — "my dad", "my friend Alex",
     "at the park". Pulls out the role + the proper noun (if present)
     and produces a Mention even when we don't yet have the entity in
     kstore. The store/strategy layer can decide whether to add it.
  3. Activity / topic keyword scan — small lexicon of common activities
     ('hiking', 'cooking', 'running'). Pre-seeds slots without needing
     prior kstore records.

The model never runs in this layer. All output is deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from latticed.v2.kstore.schema import EntityKind

if TYPE_CHECKING:
    from latticed.v2.kstore.store import KStore


@dataclass(frozen=True)
class Mention:
    """A reference to an entity found in user input.

    entity_id is set ONLY when this mention resolved to an existing
    record in kstore. surface gives the literal text; canonical gives
    the normalized form ("hiking" rather than "Hiking" or "go hike").
    relation_hint hints at how the user described the entity (e.g.
    'dad', 'friend') so the strategy layer can ask "do you mean the
    same Greg you mentioned last week?" rather than always creating
    a new entity.
    """
    surface: str
    canonical: str
    kind: EntityKind
    start: int
    end: int
    confidence: float
    entity_id: Optional[str] = None
    relation_hint: Optional[str] = None    # "dad", "friend", "wife", etc.


# ── Lexicons ──────────────────────────────────────────────────────────────
# Common activities. Verbs are matched as the verb form; noun forms are
# matched as bare words. Each entry is a tuple (regex pattern, canonical).
_ACTIVITY_LEXICON: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bhik(?:ing|ed?|e)\b", re.IGNORECASE),       "hiking"),
    (re.compile(r"\b(?:bik(?:ing|ed?|e)|cycling|cycled?)\b", re.IGNORECASE), "biking"),
    (re.compile(r"\bcook(?:ing|ed?)\b", re.IGNORECASE),        "cooking"),
    (re.compile(r"\brun(?:ning|s)?\b", re.IGNORECASE),          "running"),
    (re.compile(r"\bread(?:ing)?\b", re.IGNORECASE),            "reading"),
    (re.compile(r"\bwrit(?:ing|e|es)\b", re.IGNORECASE),        "writing"),
    (re.compile(r"\bswim(?:ming|s)?\b", re.IGNORECASE),         "swimming"),
    (re.compile(r"\bgolf(?:ing)?\b", re.IGNORECASE),            "golf"),
    (re.compile(r"\bfish(?:ing|ed)?\b", re.IGNORECASE),         "fishing"),
    (re.compile(r"\bcamping\b", re.IGNORECASE),                 "camping"),
    (re.compile(r"\bgardening\b", re.IGNORECASE),               "gardening"),
    (re.compile(r"\bpainting\b", re.IGNORECASE),                "painting"),
    (re.compile(r"\bjournal(?:ing|ed)?\b", re.IGNORECASE),      "journaling"),
    (re.compile(r"\bmeditat(?:ion|ing|ed?|e)\b", re.IGNORECASE), "meditation"),
    (re.compile(r"\byoga\b", re.IGNORECASE),                    "yoga"),
    (re.compile(r"\bworkout|working out|exercise|exercising\b", re.IGNORECASE), "exercise"),
]

# Relationship words → (kind, relation_hint).
_RELATIONSHIP_WORDS: dict[str, tuple[EntityKind, str]] = {
    "dad":      (EntityKind.PERSON, "dad"),
    "father":   (EntityKind.PERSON, "father"),
    "mom":      (EntityKind.PERSON, "mom"),
    "mother":   (EntityKind.PERSON, "mother"),
    "brother":  (EntityKind.PERSON, "brother"),
    "sister":   (EntityKind.PERSON, "sister"),
    "son":      (EntityKind.PERSON, "son"),
    "daughter": (EntityKind.PERSON, "daughter"),
    "wife":     (EntityKind.PERSON, "wife"),
    "husband":  (EntityKind.PERSON, "husband"),
    "partner":  (EntityKind.PERSON, "partner"),
    "boyfriend": (EntityKind.PERSON, "boyfriend"),
    "girlfriend": (EntityKind.PERSON, "girlfriend"),
    "friend":   (EntityKind.PERSON, "friend"),
    "coworker": (EntityKind.PERSON, "coworker"),
    "boss":     (EntityKind.PERSON, "boss"),
    "neighbor": (EntityKind.PERSON, "neighbor"),
    "doctor":   (EntityKind.PERSON, "doctor"),
    "teacher":  (EntityKind.PERSON, "teacher"),
    "kid":      (EntityKind.PERSON, "kid"),
    "kids":     (EntityKind.PERSON, "kids"),
    "child":    (EntityKind.PERSON, "child"),
    "children": (EntityKind.PERSON, "children"),
}

# Pattern: "my dad", "my friend Alex", "my dad Greg"
# Note: only the "my <relation>" head is case-insensitive. The proper-name
# tail uses an inline (?-i:...) modifier so '[A-Z]' really means uppercase
# only — otherwise IGNORECASE folds A-Z and 'came' / 'today' / etc. get
# captured as proper names. (Live failure: "my friend Alex came by today"
# captured "Alex came" instead of just "Alex".)
_MY_RELATION_RX = re.compile(
    r"\bmy\s+(" + "|".join(sorted(_RELATIONSHIP_WORDS, key=len, reverse=True))
    + r")(?:\s+(?-i:([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)))?\b",
    re.IGNORECASE,
)

# Pattern: "at the park", "in Bellevue", "to the gym"
_PLACE_PREP_RX = re.compile(
    r"\b(?:at|in|to|from)\s+(?:the\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b"
)
_COMMON_PLACE_NOUNS = re.compile(
    r"\b(?:at|in|to|from)\s+(?:the\s+)?(park|gym|office|store|airport|"
    r"restaurant|cafe|library|school|beach|mountains?|trail|river|lake)\b",
    re.IGNORECASE,
)


def extract_mentions(
    text: str,
    *,
    kstore: Optional["KStore"] = None,
) -> tuple[Mention, ...]:
    """Pull every typed mention out of ``text``.

    If ``kstore`` is provided, known entities (matched by name or alias)
    are tagged with their entity_id at high confidence. Mentions are
    returned in start-offset order; overlapping spans are de-duplicated
    in favor of the higher-confidence / longer span.
    """
    found: list[Mention] = []

    # Pass 1 — KStore lookup. We do a simple scan: for each live entity,
    # search for its name (and aliases) as a word-boundary match.
    if kstore is not None:
        for ent in kstore.list_entities():
            for surface in (ent.name, *ent.aliases):
                if not surface:
                    continue
                pattern = re.compile(
                    r"(?<![A-Za-z0-9])" + re.escape(surface) + r"(?![A-Za-z0-9])",
                    re.IGNORECASE,
                )
                for m in pattern.finditer(text):
                    found.append(Mention(
                        surface=m.group(0),
                        canonical=ent.name,
                        kind=ent.kind,
                        start=m.start(), end=m.end(),
                        confidence=1.0,
                        entity_id=ent.id,
                    ))

    # Pass 2 — relationship patterns: "my dad", "my friend Alex"
    for m in _MY_RELATION_RX.finditer(text):
        word = m.group(1).lower()
        proper = (m.group(2) or "").strip()
        kind, hint = _RELATIONSHIP_WORDS[word]
        canonical = proper if proper else hint
        found.append(Mention(
            surface=m.group(0),
            canonical=canonical,
            kind=kind,
            start=m.start(), end=m.end(),
            confidence=0.9 if proper else 0.7,
            relation_hint=hint,
        ))

    # Pass 3 — activity keyword scan
    for pattern, canonical in _ACTIVITY_LEXICON:
        for m in pattern.finditer(text):
            found.append(Mention(
                surface=m.group(0),
                canonical=canonical,
                kind=EntityKind.ACTIVITY,
                start=m.start(), end=m.end(),
                confidence=0.75,
            ))

    # Pass 4 — place keywords ("at the park", "in Bellevue")
    for m in _COMMON_PLACE_NOUNS.finditer(text):
        place = m.group(1).lower()
        # offset of the captured group
        gs, ge = m.span(1)
        found.append(Mention(
            surface=m.group(1),
            canonical=place,
            kind=EntityKind.PLACE,
            start=gs, end=ge,
            confidence=0.7,
        ))
    for m in _PLACE_PREP_RX.finditer(text):
        gs, ge = m.span(1)
        place = m.group(1)
        # skip if already captured by common-noun matcher or if it looks
        # like a stop-word (e.g. proper name we already have)
        if any(not (ge <= f.start or gs >= f.end) for f in found):
            continue
        found.append(Mention(
            surface=place,
            canonical=place,
            kind=EntityKind.PLACE,
            start=gs, end=ge,
            confidence=0.55,
        ))

    # De-duplicate overlapping spans: keep the higher-confidence match
    # for any pair of overlapping spans. If equal confidence, keep the
    # longer (more specific) one.
    found.sort(key=lambda m: (m.start, -m.confidence, -(m.end - m.start)))
    kept: list[Mention] = []
    for m in found:
        if any(not (m.end <= k.start or m.start >= k.end) for k in kept):
            continue
        kept.append(m)
    kept.sort(key=lambda m: m.start)
    return tuple(kept)
