"""Sprint 47 — Two-beat chat shape (creative response + question to learn more).

Earl's feedback after Sprint 46 went live on his phone: the chat-path reply
was flat ("Sounds nice.") with no question, or a bare question with no
reflection. A personal-assistant chat reply must be shaped as:

    [creative reflection on a specific detail] [question to learn more]

These tests lock that contract in:
  - the fast_mentor / life_coach system prompts have the right language
  - _is_two_beat_shape correctly classifies known good / bad outputs
  - _infer_with_echo_guard retries on shape failure when enforced
  - the retry nudge mentions the two beats explicitly
  - recall-mode answers bypass the check (they're deterministic recall)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


# ── _is_two_beat_shape classifier ────────────────────────────────────────────
def test_two_beat_accepts_good_shape():
    good = [
        "A whole day at the park sounds like the perfect reset. What was the best part?",
        "Brother time is always grounding. What did the two of you get into?",
        "Cooking your own dinner is its own small win. What did you make?",
        ("A real Father's Day conversation with your dad — that's the kind of moment "
         "that stays with you. What did you two end up talking about?"),
    ]
    for g in good:
        check(f"good shape passes: {g[:50]!r}",
              L._is_two_beat_shape(g),
              "should pass two-beat check")


def test_two_beat_rejects_flat_acknowledgment():
    flat = [
        "Nice.",
        "That sounds great.",
        "Sounds like a good time with your dad.",
        "Cool, glad to hear that.",
    ]
    for f in flat:
        check(f"flat reply fails: {f!r}",
              not L._is_two_beat_shape(f),
              "missing question — should fail")


def test_two_beat_rejects_bare_question():
    bare = [
        "What did you talk about?",
        "How was it?",
        "Tell me more?",
    ]
    for b in bare:
        check(f"bare question fails: {b!r}",
              not L._is_two_beat_shape(b),
              "missing reflection — should fail")


def test_two_beat_rejects_one_long_question_with_clause():
    # Single question that starts with a clause shouldn't count — the
    # declarative half must be its own sentence with at least 3 words.
    weak = "Hey, what did you talk about?"
    check("clause + question still fails",
          not L._is_two_beat_shape(weak),
          "leading clause is not a real reflection")


# ── System prompts updated ──────────────────────────────────────────────────
def test_fast_mentor_prompt_has_two_beat_language():
    spec = L.AgentFactoryRegistry().get_agent("fast_mentor")
    p = spec.system_prompt
    check("fast_mentor prompt mentions CREATIVE RESPONSE",
          "CREATIVE RESPONSE" in p, "language drifted")
    check("fast_mentor prompt mentions QUESTION TO LEARN MORE",
          "QUESTION TO LEARN MORE" in p)
    check("fast_mentor prompt forbids flat acknowledgment",
          "Not a flat" in p or "flat 'Nice." in p)
    check("fast_mentor example shows Father's Day shape",
          "Father's Day" in p and "What did you two" in p)
    # Sprint 47 follow-up — every exchange is a learning opportunity.
    check("fast_mentor prompt frames replies as learning opportunities",
          "OPPORTUNITY TO LEARN MORE ABOUT THE USER" in p,
          "missing learning-opportunity framing")
    check("fast_mentor prompt forbids inventing details",
          "Do NOT invent details" in p or "do NOT invent" in p)


def test_life_coach_prompt_has_two_beat_language():
    spec = L.AgentFactoryRegistry().get_agent("life_coach")
    p = spec.system_prompt
    check("life_coach prompt mentions CREATIVE RESPONSE",
          "CREATIVE RESPONSE" in p)
    check("life_coach prompt mentions QUESTION TO LEARN MORE",
          "QUESTION TO LEARN MORE" in p)
    check("life_coach prompt says both beats required",
          "Both beats are required" in p)
    check("life_coach prompt frames replies as learning opportunities",
          "opportunity to learn more about THIS user" in p
          or "opportunity to learn more" in p.lower(),
          "missing learning-opportunity framing")
    check("life_coach prompt forbids invented details",
          "never invent" in p.lower() or "do not invent" in p.lower())


# ── Echo guard retries on missing-two-beat ──────────────────────────────────
def test_echo_guard_retries_on_flat_when_enforced():
    calls = []
    responses = ["Sounds nice.", "A great Father's Day moment. What did you talk about?"]

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        return responses[len(calls) - 1]

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard(
                "fast_mentor", "base", "spoke with my dad",
                enforce_two_beat=True,
            )
        )
    check("flat reply triggered retry", len(calls) == 2,
          f"expected 2 model calls, got {len(calls)}")
    check("retry nudge mentions two beats",
          "two beats" in calls[1] or "creative reflection" in calls[1],
          "nudge missing two-beat language")
    check("returned the good second reply",
          "What did you talk about?" in out and "Father's Day" in out,
          f"got {out!r}")


def test_echo_guard_retries_on_bare_question_when_enforced():
    calls = []
    responses = [
        "What did you talk about?",
        "Time with your dad is meaningful. What part of the conversation stayed with you?",
    ]

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        return responses[len(calls) - 1]

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard(
                "fast_mentor", "base", "spoke with my dad",
                enforce_two_beat=True,
            )
        )
    check("bare-question triggered retry", len(calls) == 2)
    check("good two-beat reply returned",
          L._is_two_beat_shape(out), f"got {out!r}")


def test_echo_guard_no_retry_when_not_enforced():
    """When enforce_two_beat=False (non-chat agent), flat replies don't retry."""
    calls = []

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        return "Done."   # flat, no question — would fail if check ran

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard(
                "fact_extractor", "base", "anything",
                enforce_two_beat=False,
            )
        )
    check("non-chat agent: no shape retry", len(calls) == 1,
          f"expected 1 call, got {len(calls)}")
    check("flat reply allowed through", out == "Done.")


def test_two_beat_agents_set_lists_chat_agents():
    check("fast_mentor in _TWO_BEAT_AGENTS",
          "fast_mentor" in L._TWO_BEAT_AGENTS)
    check("life_coach in _TWO_BEAT_AGENTS",
          "life_coach" in L._TWO_BEAT_AGENTS)
    check("fact_extractor NOT in _TWO_BEAT_AGENTS",
          "fact_extractor" not in L._TWO_BEAT_AGENTS)


# ── Recall mode bypasses shape check (fast_core_node) ───────────────────────
def test_fast_core_recall_mode_bypasses_two_beat():
    """A 'what do I like to do for fun' query should return a deterministic
    recall answer with no follow-up question. The two-beat check must NOT
    fire and the flat 'You're a hiker — most Saturday mornings you're out
    on a trail.' answer should pass through unchanged."""
    calls = []
    captured = {"kwargs_seen": None}

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        # Flat, no question — would fail two-beat. Recall mode must skip check.
        return "You hike on Saturday mornings."

    # Need to intercept the kwarg to confirm enforce_two_beat=False was sent.
    real_guard = L._infer_with_echo_guard

    async def _spy_guard(agent_id, payload, user_input, *, enforce_two_beat=False):
        captured["kwargs_seen"] = enforce_two_beat
        return await real_guard(
            agent_id, payload, user_input, enforce_two_beat=enforce_two_beat
        )

    state = {
        "user_input": "What do I like to do for fun?",
        "retrieved_memory": "",
        "belief_context": "User hikes most Saturday mornings.",
    }
    with patch.object(L.runtime, "execute_registry_inference", _fake_infer), \
         patch.object(L, "_infer_with_echo_guard", _spy_guard):
        out = asyncio.new_event_loop().run_until_complete(L.fast_core_node(state))
    check("recall mode disabled two-beat check",
          captured["kwargs_seen"] is False,
          f"got enforce_two_beat={captured['kwargs_seen']}")
    check("recall mode: only 1 model call (no retry)",
          len(calls) == 1, f"got {len(calls)} calls")
    check("recall reply preserved verbatim",
          "hike" in out["fast_generation"].lower())


def test_fast_core_normal_chat_enforces_two_beat():
    captured = {"kwargs_seen": None}

    async def _fake_infer(agent_id, payload):
        return "Cooking dinner sounds satisfying. What did you make?"

    real_guard = L._infer_with_echo_guard

    async def _spy_guard(agent_id, payload, user_input, *, enforce_two_beat=False):
        captured["kwargs_seen"] = enforce_two_beat
        return await real_guard(
            agent_id, payload, user_input, enforce_two_beat=enforce_two_beat
        )

    state = {
        "user_input": "I made dinner tonight.",
        "retrieved_memory": "",
        "belief_context": "",
    }
    with patch.object(L.runtime, "execute_registry_inference", _fake_infer), \
         patch.object(L, "_infer_with_echo_guard", _spy_guard):
        asyncio.new_event_loop().run_until_complete(L.fast_core_node(state))
    check("normal chat enforces two-beat",
          captured["kwargs_seen"] is True,
          f"got enforce_two_beat={captured['kwargs_seen']}")


# ── Runner ─────────────────────────────────────────────────────────────────
TESTS = [
    test_two_beat_accepts_good_shape,
    test_two_beat_rejects_flat_acknowledgment,
    test_two_beat_rejects_bare_question,
    test_two_beat_rejects_one_long_question_with_clause,
    test_fast_mentor_prompt_has_two_beat_language,
    test_life_coach_prompt_has_two_beat_language,
    test_echo_guard_retries_on_flat_when_enforced,
    test_echo_guard_retries_on_bare_question_when_enforced,
    test_echo_guard_no_retry_when_not_enforced,
    test_two_beat_agents_set_lists_chat_agents,
    test_fast_core_recall_mode_bypasses_two_beat,
    test_fast_core_normal_chat_enforces_two_beat,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 47 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
