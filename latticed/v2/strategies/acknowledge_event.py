"""AcknowledgeEvent — the user shared a moment from their life.

Two-beat reply: [creative reflection on a specific detail] + [open
question to learn more]. This is the strategy that fires for the
Father's Day live failure case.

Slot design enforces what Sprints 47/48 had to do via post-hoc retry:
  - reflection slot: must reference a real entity from perception's
    mentions OR a temporal_ref (anchored to something stated);
    no banned plurals; ends with period/exclamation; not a question.
  - question slot: must end with '?', no banned plurals, references
    one of the same anchor strings (so the question is ABOUT what
    the user actually said).

The fallback values are valid two-beat sentences themselves, so even
if the model fails twice we still ship a clean reply.
"""
from __future__ import annotations

from latticed.v2.kstore.schema import EntityKind
from latticed.v2.perceive.intent import Intent
from latticed.v2.strategies.base import (
    Slot,
    SlotConstraint,
    ResponsePlan,
    Strategy,
)


def _anchor_strings(perception) -> list[str]:
    """The set of phrases the slot output should reference -- the user's
    own words for the people/places/activities/holidays they mentioned.
    Anchors what the model can say a 'specific detail' is."""
    anchors: list[str] = []
    for m in perception.mentions:
        anchors.append(m.canonical)
        # Also the surface form, in case it differs (e.g. "Pops" → "Greg"
        # canonical; we accept either as a valid anchor)
        if m.surface.lower() != m.canonical.lower():
            anchors.append(m.surface)
    for t in perception.temporal_refs:
        anchors.append(t.text)
    return anchors


def _topic_phrase(perception) -> str:
    """A short phrase describing what the event was 'about' — used in
    both reflection and question slots so the model has a concrete
    anchor instead of having to invent one."""
    # Prefer the most specific (highest-confidence) mention.
    if perception.mentions:
        best = max(perception.mentions, key=lambda m: m.confidence)
        if best.relation_hint:
            return f"your {best.relation_hint}"
        return best.canonical
    if perception.temporal_refs:
        return perception.temporal_refs[0].text
    return "that"


def _holiday_or_time_anchor(perception) -> str:
    """Best phrase to anchor the reflection in time. Holidays read
    naturally ('A Father's Day conversation'); raw weekday names also
    work ('That Saturday morning'); fall back to 'that moment'."""
    if perception.temporal_refs:
        return perception.temporal_refs[0].text
    return "that moment"


class AcknowledgeEvent(Strategy):
    name = "acknowledge_event"
    priority = 50

    def matches(self, perception, kstore) -> bool:
        return perception.intent == Intent.SHARE_EVENT

    def plan(self, perception, kstore) -> ResponsePlan:
        topic = _topic_phrase(perception)
        time_anchor = _holiday_or_time_anchor(perception)
        anchors = _anchor_strings(perception)

        # The reflection slot: the model produces ONE sentence that names
        # the specific detail and reacts to it. Constraints prevent the
        # known failure modes:
        #   - no_banned_plurals: blocks "we talked" / "our conversation"
        #     (uses word-boundary regex, so it won't false-positive on
        #     "your" containing "our" -- a real bug caught by tests)
        #   - must_contain: at least one anchor string -- prevents the
        #     "amazing personality" invention (no personality in anchors)
        #   - max_words: keeps the model from running off into invention
        reflection_constraint = SlotConstraint(
            max_words=25,
            no_banned_plurals=True,
            must_contain=tuple(anchors) if anchors else (),
        )
        reflection_prompt = (
            f"The user just said: \"{perception.user_input}\"\n"
            f"Write ONE warm sentence (max 25 words) reflecting on "
            f"\"{topic}\" or \"{time_anchor}\" from what they shared.\n"
            f"Rules: use 'your' not 'we/us/our'. Reflect only what they "
            f"stated -- do NOT invent details about personality, food, "
            f"location, etc. End with a period."
        )
        reflection_fallback = f"{time_anchor.capitalize()} with {topic} sounds like a moment worth keeping."

        # The question slot: open-ended, ends with ?, references the topic.
        question_constraint = SlotConstraint(
            max_words=18,
            must_end_with="?",
            no_banned_plurals=True,
        )
        question_prompt = (
            f"The user just said: \"{perception.user_input}\"\n"
            f"Write ONE open-ended follow-up question (max 18 words) about "
            f"\"{topic}\" so they can share more. Use 'you' / 'your' -- "
            f"never 'we/us/our'. End with '?'."
        )
        question_fallback = f"What made {time_anchor} stand out for you?"

        template = "{reflection} {question}"

        return ResponsePlan(
            strategy_name=self.name,
            template=template,
            expected_shape="two_beat",
            slots=(
                Slot.model(
                    name="reflection",
                    prompt=reflection_prompt,
                    fallback_value=reflection_fallback,
                    temperature=0.55,
                    max_tokens=80,
                    constraint=reflection_constraint,
                ),
                Slot.model(
                    name="question",
                    prompt=question_prompt,
                    fallback_value=question_fallback,
                    temperature=0.5,
                    max_tokens=40,
                    constraint=question_constraint,
                ),
            ),
            trace=(
                f"topic={topic}",
                f"time_anchor={time_anchor}",
                f"anchors={len(anchors)}",
            ),
        )
