"""Sprint 46 — Output hygiene: tool-call JSON strip, role-flip detection,
date grounding.

Unit tests for the regex + helper layer. Doesn't require Ollama or a live
server; mirrors the live regression Earl reported on his phone:

    You · 6/21/2026 · chat · fast · 60466ms
    Today is Father's Day I spoke with my dad...
    Lattice:
      {"tool": "web_fetch", "params": {"url": "/api/your-conversation"}}
      You: "I think Father's Day is always on the first Saturday of June."
      You: "As a reminder, it's also on September 10th..."

Three distinct failure modes covered: tool-call leakage, role flip,
calendar fabrication (mitigated by the new CURRENT DATE anchor).
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import patch

# Windows consoles default to cp1252 and choke on emoji / arrows. Same fix
# eval_harness.py uses.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


# ── clean_model_text strips tool-call JSON ───────────────────────────────────
def test_strips_basic_tool_call_json():
    raw = '{"tool": "web_fetch", "params": {"url": "/api/your-conversation"}}\nReal reply text here.'
    out = L.clean_model_text(raw)
    check("strips top-level tool object", "tool" not in out and "web_fetch" not in out,
          f"got {out!r}")
    check("preserves the real reply", "Real reply text here." in out)


def test_strips_tool_call_with_single_quotes():
    raw = "{'tool': 'shell', 'params': {'cmd': 'rm -rf /'}}\nNo, I won't do that."
    out = L.clean_model_text(raw)
    check("strips single-quoted JSON", "shell" not in out and "rm -rf" not in out,
          f"got {out!r}")


def test_strips_tool_call_with_args_alias():
    raw = '{"tool":"calc","args":{"x":1,"y":2}} The answer is 3.'
    out = L.clean_model_text(raw)
    check("strips args alias", "calc" not in out)
    check("preserves trailing prose", "The answer is 3." in out)


def test_strips_shell_marker():
    raw = "[SHELL: get-date]\nHere's what I found: 2026-06-21."
    out = L.clean_model_text(raw)
    check("strips [SHELL: ...] marker", "[SHELL:" not in out)
    check("preserves prose", "2026-06-21" in out)


def test_preserves_plain_text():
    raw = "Hi! That sounds like a wonderful Father's Day."
    out = L.clean_model_text(raw)
    check("plain text untouched", out == raw)


def test_handles_embedded_tool_in_paragraph():
    raw = ("Sure, let me help. {\"tool\": \"web_fetch\", \"params\": {\"url\": \"x\"}} "
           "I'll think about that for you.")
    out = L.clean_model_text(raw)
    check("embedded JSON stripped", "tool" not in out and "web_fetch" not in out)
    check("paragraph still flows",
          "Sure, let me help." in out and "I'll think about that for you." in out)


# ── Role-flip detection ─────────────────────────────────────────────────────
def test_role_flip_detects_basic_pattern():
    cases = [
        'You: "I think Father\'s Day is always on the first Saturday of June."',
        'You said: "It\'s also on September 10th."',
        'User: "what do you think?"',
        'You wrote: "this is the reply"',
        'You replied: "yes"',
    ]
    for c in cases:
        check(f"role-flip detected: {c[:30]!r}", L._is_role_flipped(c),
              f"missed in {c!r}")


def test_role_flip_ignores_natural_references():
    # These should NOT trigger — they reference the user's prior speech in a
    # natural way ("you said earlier that...") without quoting a reply.
    cases = [
        "You said earlier that you go hiking — tell me more.",
        "You mentioned your dad. What did you talk about?",
        "It sounds like you're spending time with your dad today.",
        "you and your dad had a great conversation",
    ]
    for c in cases:
        check(f"no false positive: {c[:40]!r}", not L._is_role_flipped(c),
              f"false positive on {c!r}")


# ── clean_model_text + role-flip integrate: the user's actual bad output ───
def test_users_actual_failure_output_is_cleaned():
    # Verbatim from the live phone report.
    raw = (
        '{"tool": "web_fetch", "params": {"url": "/api/your-conversation"}}\n'
        'You: "I think Father\'s Day is always on the first Saturday of June."\n'
        'You: "As a reminder, it\'s also on September 10th every year to mark '
        'the same day. Don\'t forget your dad—he makes all that happen."'
    )
    cleaned = L.clean_model_text(raw)
    check("user's failure: tool JSON stripped",
          "tool" not in cleaned and "web_fetch" not in cleaned,
          f"got {cleaned!r}")
    # Role flip remains in cleaned text (clean_model_text doesn't drop those
    # lines — the echo-guard retry is what catches them).
    check("user's failure: role-flip still detectable",
          L._is_role_flipped(cleaned),
          "echo-guard would not retry on this — bug")


# ── Date grounding in fast_core_node payload ────────────────────────────────
def _capture_fast_core_payload():
    """Drive fast_core_node with a stub registry inference so we can read
    exactly what payload it built for the model."""
    captured = {"payload": None}

    async def _fake_infer(agent_id, payload):
        captured["payload"] = payload
        return "I hear you. What did you talk about?"

    state = {
        "user_input": "Today is Father's Day, I spoke with my dad.",
        "retrieved_memory": "",
        "belief_context": "",
    }
    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        asyncio.new_event_loop().run_until_complete(L.fast_core_node(state))
    return captured["payload"]


def test_fast_core_payload_includes_current_date():
    payload = _capture_fast_core_payload()
    check("payload has CURRENT DATE section",
          "CURRENT DATE:" in (payload or ""),
          "missing date anchor")
    # Should include either the ISO date or the day-name format.
    from datetime import datetime, timezone
    today_iso = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    check("payload anchors today's ISO date",
          today_iso in (payload or ""),
          f"missing {today_iso} in payload")
    check("payload tells model to say 'I don't know'",
          "rather than guessing" in (payload or ""),
          "missing fabrication guardrail")


def test_life_coach_payload_includes_current_date():
    captured = {"payload": None}

    async def _fake_infer(agent_id, payload):
        captured["payload"] = payload
        return "Sounds meaningful."

    state = {
        "user_input": "I had a hard day.",
        "retrieved_memory": "",
        "belief_context": "",
    }
    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        asyncio.new_event_loop().run_until_complete(L.life_coach_node(state))
    check("life_coach payload has CURRENT DATE",
          "CURRENT DATE:" in (captured["payload"] or ""))


# ── Echo guard retries on role-flip ─────────────────────────────────────────
def test_echo_guard_retries_on_role_flip():
    """The retry path is the one that catches role-flipped output. First
    inference returns role-flipped, second returns a clean reply — confirm
    the guard called the model twice and returned the clean reply."""
    calls = []
    responses = [
        'You: "Father\'s Day is the first Saturday of June."',   # role-flip
        "Sounds like a great time with your dad — what stood out?",
    ]

    async def _fake_infer(agent_id, payload):
        calls.append(payload)
        return responses[len(calls) - 1]

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard("fast_mentor", "base", "spoke with my dad")
        )
    check("echo guard called the model twice", len(calls) == 2,
          f"got {len(calls)} calls")
    check("retry payload includes role-flip nudge",
          "No lines that\n                       begin with 'You:' or 'User:')." in calls[1]
          or "begin with 'You:'" in calls[1],
          "retry nudge missing role-flip language")
    check("returned the clean second reply",
          "great time with your dad" in out, f"got {out!r}")


def test_echo_guard_degrades_when_role_flip_persists():
    """If the model role-flips twice in a row, the guard degrades to a
    minimal honest reply rather than showing the broken text to the user."""
    async def _fake_infer(agent_id, payload):
        return 'You: "fabricated text"'

    with patch.object(L.runtime, "execute_registry_inference", _fake_infer):
        out = asyncio.new_event_loop().run_until_complete(
            L._infer_with_echo_guard("fast_mentor", "base", "anything")
        )
    check("persisted role-flip → minimal degrade",
          "I hear you" in out and "You:" not in out,
          f"got {out!r}")


# ── Runner ──────────────────────────────────────────────────────────────────
TESTS = [
    test_strips_basic_tool_call_json,
    test_strips_tool_call_with_single_quotes,
    test_strips_tool_call_with_args_alias,
    test_strips_shell_marker,
    test_preserves_plain_text,
    test_handles_embedded_tool_in_paragraph,
    test_role_flip_detects_basic_pattern,
    test_role_flip_ignores_natural_references,
    test_users_actual_failure_output_is_cleaned,
    test_fast_core_payload_includes_current_date,
    test_life_coach_payload_includes_current_date,
    test_echo_guard_retries_on_role_flip,
    test_echo_guard_degrades_when_role_flip_persists,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 46 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
