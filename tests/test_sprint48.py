"""Sprint 48 — Chat content fidelity: banned plural pronouns + no-invent.

After Sprint 47's two-beat shape landed, a live phone test surfaced two
content-quality failures that the shape check couldn't catch:

  Lattice: "The father we talked to had such an amazing personality.
            What did you say?"

(1) "we talked" — the assistant used first-person plural as if it had been
    present in the user's life. It wasn't.
(2) "amazing personality" — the user said "had a great conversation"
    without describing personality. The model invented the detail.

These tests lock in the fix:
  - _uses_banned_plural detector
  - echo guard retries on plural use (only for chat agents)
  - retry nudge explicitly forbids "we / us / our"
  - both system prompts contain the two hard rules + the bad/good example
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


# ── _uses_banned_plural classifier ──────────────────────────────────────────
def test_banned_plural_catches_we_us_our():
    bad = [
        "We talked about your dad.",
        "The father we talked to had such an amazing personality. What did you say?",
        "Our conversation today was meaningful. How did it feel?",
        "Sounds like us at our best. What did you enjoy most?",
        "We're glad you shared that.",
        "We've all been there.",
    ]
    for b in bad:
        check(f"banned plural caught: {b[:50]!r}",
              L._uses_banned_plural(b),
              "should detect first-person plural")


def test_banned_plural_allows_proper_singular():
    good = [
        "Your dad sounds like a meaningful presence. What did you talk about?",
        "Time with your dad is grounding. What made the conversation good?",
        "You and your dad — that's a relationship worth tending. What stood out?",
        "That moment with your dad stays. What was the best part?",
        # Edge cases that contain 'we' / 'us' as substrings but not as words
        "Were you surprised by what he said?",
        "Just because you brought it up — what made it stand out?",
        "Trust your instinct on this — what's it telling you?",
    ]
    for g in good:
        check(f"good text not flagged: {g[:50]!r}",
              not L._uses_banned_plural(g),
              "false positive on proper 'you' phrasing")


def test_users_actual_failure_caught_by_plural_guard():
    failure = "The father we talked to had such an amazing personality. What did you say?"
    check("user's live failure caught by plural guard",
          L._uses_banned_plural(failure),
          "the 'we talked' assistant output should trigger retry")


# ── Echo guard retries on banned plural (chat agents only) ─────────────────
def test_echo_guard_retries_on_banned_plural_when_enforced():
    calls = []
    responses = [
        "The father we talked to had such an amazing personality. What did you say?",
        "A Father's Day conversation with your dad — that's a moment worth keeping. What did the two of you talk about?",
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
    check("banned plural triggered retry", len(calls) == 2,
          f"expected 2 calls, got {len(calls)}")
    check("retry nudge forbids we/us/our",
          "we" in calls[1].lower() and "you were NOT there" in calls[1],
          "nudge missing pronoun-correction language")
    check("returned the clean second reply (no we/us/our)",
          not L._uses_banned_plural(out) and "your dad" in out,
          f"got {out!r}")


def test_echo_guard_does_not_check_plural_when_not_chat():
    """A non-chat agent (enforce_two_beat=False) is allowed to use 'we' —
    e.g. summarization agents emitting technical text."""
    calls = []

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        return "We extracted three facts: A, B, C."   # 'we' allowed for non-chat

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard(
                "fact_extractor", "base", "anything",
                enforce_two_beat=False,
            )
        )
    check("non-chat agent: plural allowed, no retry",
          len(calls) == 1, f"got {len(calls)} calls")
    check("plural text passed through", out.startswith("We extracted"))


def test_echo_guard_returns_plural_retry_output_if_not_role_flipped():
    """Design choice: plural alone (no role-flip, no leak) does not trigger
    the degrade fallback after retry — a slightly-wrong reply with 'we' is
    still more useful than the minimal 'I hear you' degrade. Only the
    structural failures (role-flip, prompt-leak) degrade. Confirms the
    guard doesn't loop AND that plural-after-retry is returned as-is."""
    calls = []

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        # Always plural; never role-flipped, never leaked.
        return "We talked about that. Want to share more?"

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard(
                "fast_mentor", "base", "anything",
                enforce_two_beat=True,
            )
        )
    check("guard retried once then returned (no loop)",
          len(calls) == 2, f"got {len(calls)} calls")
    check("persisted plural NOT replaced with minimal degrade",
          "I hear you" not in out,
          f"got {out!r}")


def test_echo_guard_degrades_when_role_flip_persists_even_with_plural():
    """Role-flip persistence DOES degrade — even when plural is also
    present. The guard cares about the structural failure."""
    calls = []

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        # Role-flipped (matches _ROLE_FLIP_RX which requires a quote after the colon).
        return 'You said: "We talked about your dad."'

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard(
                "fast_mentor", "base", "anything",
                enforce_two_beat=True,
            )
        )
    check("role-flip persisted → degrade",
          "I hear you" in out and "We talked" not in out,
          f"got {out!r}")


# ── System prompts updated ─────────────────────────────────────────────────
def test_fast_mentor_prompt_has_two_hard_rules():
    spec = L.AgentFactoryRegistry().get_agent("fast_mentor")
    p = spec.system_prompt
    check("fast_mentor names the 'TWO HARD RULES' header",
          "TWO HARD RULES" in p)
    check("fast_mentor forbids we/us/our explicitly",
          "NEVER use 'we', 'us', 'our'" in p)
    check("fast_mentor forbids invented details with concrete example",
          "amazing personality" in p and "you don't know" in p)
    check("fast_mentor shows the BAD/GOOD reply comparison",
          "BAD reply" in p and "GOOD reply" in p)
    check("fast_mentor's BAD example is the user's literal failure",
          "The father we talked to had such an amazing personality" in p)


def test_life_coach_prompt_has_plural_ban():
    spec = L.AgentFactoryRegistry().get_agent("life_coach")
    p = spec.system_prompt
    check("life_coach forbids we/us/our",
          "Never write 'we', 'us', or 'our'" in p)
    check("life_coach explains why (you were NOT there)",
          "NOT there" in p)


# ── Cumulative integration: retry chain still works ───────────────────────
def test_full_retry_chain_fixes_all_three_failures():
    """The live phone output had ALL of: banned plural, invented detail,
    AND a missing reflection (depending on parsing). One retry should fix
    all three when the second model output is clean."""
    calls = []
    responses = [
        # First: classic live failure
        "The father we talked to had such an amazing personality. What did you say?",
        # Second: clean two-beat with 'your dad' and no inventions
        "A Father's Day conversation with your dad is the kind of moment worth holding onto. What made it feel great?",
    ]

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        return responses[len(calls) - 1]

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard(
                "fast_mentor", "base",
                "Sunday was Father's Day I spoke with my dad had a great conversation",
                enforce_two_beat=True,
            )
        )
    check("retried exactly once", len(calls) == 2, f"got {len(calls)}")
    check("clean output: no banned plural",
          not L._uses_banned_plural(out), f"got {out!r}")
    check("clean output: two-beat shape",
          L._is_two_beat_shape(out), f"got {out!r}")
    check("clean output: not role-flipped",
          not L._is_role_flipped(out))
    check("clean output: not the invented detail",
          "amazing personality" not in out)


# ── Runner ────────────────────────────────────────────────────────────────
TESTS = [
    test_banned_plural_catches_we_us_our,
    test_banned_plural_allows_proper_singular,
    test_users_actual_failure_caught_by_plural_guard,
    test_echo_guard_retries_on_banned_plural_when_enforced,
    test_echo_guard_does_not_check_plural_when_not_chat,
    test_echo_guard_returns_plural_retry_output_if_not_role_flipped,
    test_echo_guard_degrades_when_role_flip_persists_even_with_plural,
    test_fast_mentor_prompt_has_two_hard_rules,
    test_life_coach_prompt_has_plural_ban,
    test_full_retry_chain_fixes_all_three_failures,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 48 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
