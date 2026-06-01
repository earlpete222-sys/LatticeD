#!/usr/bin/env python3
"""
eval_harness.py — Earl Prime Regression Test Suite v1.0

Sends known-good prompts to the running Earl Prime server and verifies:
  - Financial math (income parsing, expense summing, allocation splits)
  - Research routing (never cached, grounding node runs)
  - Semantic cache round-trip (HIT on repeated prompt, returns fast)
  - No training-data hallucinations (e.g. $23,500 401k limit in IRA answer)

Usage:
    python eval_harness.py
    python eval_harness.py --url http://127.0.0.1:8000 --key local_dev_secret_123

Output:
    Console: pass/fail per test with per-check detail
    File:    End_Game_AI/runtime/outputs/eval_results.json

Requirements: httpx  (already a transitive dep; or: pip install httpx)
Exit codes: 0 = all passed, 1 = one or more failed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

try:
    import requests as _requests_lib
    _USE_REQUESTS = True
except ImportError:
    _USE_REQUESTS = False

try:
    import httpx
except ImportError:
    if not _USE_REQUESTS:
        sys.exit("Install either httpx or requests:  pip install httpx")

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_URL      = "http://127.0.0.1:8000"
DEFAULT_KEY      = "local_dev_secret_123"
PIPELINE_TIMEOUT = 240   # seconds — allows for Ollama cold-start + full inference
CACHE_TIMEOUT    = 12    # seconds — a cache HIT must return within this

OUTPUT_PATH = (
    Path(__file__).parent
    / "End_Game_AI" / "runtime" / "outputs" / "eval_results.json"
)


# ── Data structures ───────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class TestResult:
    test_id: str
    description: str
    prompt: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    nodes_visited: list[str] = field(default_factory=list)
    is_cached: bool = False
    elapsed_s: float = 0.0
    error: Optional[str] = None


# ── SSE stream helper ─────────────────────────────────────────────────────────
def _parse_sse_event(event_text: str, nodes: list, content_ref: list, cached_ref: list) -> None:
    """Parse one complete SSE event (text between blank lines) and update state."""
    for line in event_text.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except json.JSONDecodeError:
            continue

        if "node" in ev:
            nodes.append(ev["node"])
            if ev.get("status") == "hit":
                cached_ref[0] = True

        if ev.get("phase") == "Final":
            content_ref[0] = ev.get("content", "")
            if ev.get("cached"):
                cached_ref[0] = True


def run_prompt(
    url: str,
    key: str,
    prompt: str,
    timeout: int = PIPELINE_TIMEOUT,
    bypass_cache: bool = False,
) -> tuple[list[str], str, bool, float]:
    """
    Call /api/evolve and drain the SSE stream.
    Returns (nodes_visited, final_content, is_cached, elapsed_s).

    bypass_cache=True passes ?bypass_cache=1 to the server, which skips both
    cache read and write.  Use for tests that verify node execution paths so
    they always run the full pipeline regardless of prior cached results.

    Uses requests.get(stream=True) with manual SSE byte-buffer parsing.
    httpx.iter_lines() can silently drop events on text/event-stream responses
    when chunk boundaries don't align with newlines; the byte-buffer approach
    is spec-correct regardless of chunk size.
    """
    thread_id = f"eval_{uuid.uuid4().hex[:8]}"
    headers   = {"x-api-key": key, "Accept": "text/event-stream"}
    params    = {"prompt": prompt, "thread_id": thread_id, "path": "auto"}
    if bypass_cache:
        params["bypass_cache"] = "1"

    nodes: list[str] = []
    content_ref: list[str]  = [""]   # mutable single-element so inner fn can write
    cached_ref:  list[bool] = [False]
    t0 = time.time()

    resp = _requests_lib.get(
        f"{url}/api/evolve",
        headers=headers,
        params=params,
        stream=True,
        timeout=(10, timeout),   # (connect_timeout, read_timeout per chunk)
    )
    resp.raise_for_status()

    buf = ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        # SSE event delimiter is a blank line (\n\n or \r\n\r\n)
        buf = buf.replace("\r\n", "\n")
        while "\n\n" in buf:
            event, buf = buf.split("\n\n", 1)
            _parse_sse_event(event, nodes, content_ref, cached_ref)

    # flush any trailing partial event (servers sometimes omit final \n\n)
    if buf.strip():
        _parse_sse_event(buf, nodes, content_ref, cached_ref)

    resp.close()
    return nodes, content_ref[0], cached_ref[0], round(time.time() - t0, 2)


# ── Assertion helpers ─────────────────────────────────────────────────────────
def _clean(s: str) -> str:
    """Strip whitespace and commas so '$  1,650.00' matches '1650'."""
    return re.sub(r"[\s,]", "", s)


def chk_contains(content: str, pattern: str, label: str) -> CheckResult:
    ok = _clean(pattern) in _clean(content)
    return CheckResult(label, ok, f"'{pattern}' {'found ✓' if ok else 'NOT FOUND ✗'}")


def chk_not_contains(content: str, pattern: str, label: str) -> CheckResult:
    ok = _clean(pattern) not in _clean(content)
    return CheckResult(label, ok, f"Forbidden '{pattern}' {'absent ✓' if ok else 'PRESENT ✗'}")


def chk_node_visited(nodes: list[str], node: str, label: str) -> CheckResult:
    ok = node in nodes
    return CheckResult(label, ok, f"Node '{node}' {'visited ✓' if ok else 'NOT visited ✗'}")


def chk_not_cached(is_cached: bool, label: str = "pipeline ran (not cached)") -> CheckResult:
    ok = not is_cached
    return CheckResult(label, ok, "Full pipeline ran ✓" if ok else "Served from cache ✗")


def chk_cached(is_cached: bool, label: str = "served from cache") -> CheckResult:
    return CheckResult(label, is_cached, "Cache HIT ✓" if is_cached else "Cache MISS ✗")


def chk_fast(elapsed: float, limit: float, label: str) -> CheckResult:
    ok = elapsed <= limit
    return CheckResult(label, ok, f"{elapsed:.1f}s (limit {limit}s) {'✓' if ok else '✗'}")


# ── Test cases ────────────────────────────────────────────────────────────────

def tc_multi_expense(url: str, key: str) -> TestResult:
    """
    Label-aware parser with three distinct expense types.
    Verifies that rent + car + insurance are all summed into fixed expenses,
    not dropped the way the old positional parser did.

    income=$4,500  expenses=$1,730(1200+350+180)  net=$2,770
    savings=$1,385  groceries=$554.00  utilities=$346.25  entertainment=$484.75
    """
    prompt = (
        "I earn $4,500 a month. "
        "My rent is $1,200, my car payment is $350, and my insurance is $180. "
        "Build me a budget plan."
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt, bypass_cache=True)
    checks = [
        chk_contains(content, "4,500",   "income present"),
        chk_contains(content, "1,730",   "expenses summed (1200+350+180=1730)"),
        chk_contains(content, "2,770",   "net surplus correct (4500-1730=2770)"),
        chk_contains(content, "1,385",   "savings 50% of net"),
        chk_contains(content, "554",     "groceries 20% of net"),
        chk_not_contains(content, "$23,500", "no 401k hallucination"),
        chk_node_visited(nodes, "math_engine", "math_engine ran"),
    ]
    return TestResult(
        "multi_expense", "Multi-expense label-aware parser", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


def tc_simple_budget(url: str, key: str) -> TestResult:
    """
    Two-number budget: total income vs total fixed expenses.

    income=$5,200  expenses=$1,900  net=$3,300  savings=$1,650
    """
    prompt = (
        "I make $5,200 a month and have $1,900 in fixed expenses. "
        "What is my savings plan?"
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt, bypass_cache=True)
    checks = [
        chk_contains(content, "5,200", "income present"),
        chk_contains(content, "1,900", "expenses present"),
        chk_contains(content, "3,300", "net surplus correct (5200-1900=3300)"),
        chk_contains(content, "1,650", "savings 50% of net"),
        chk_node_visited(nodes, "math_engine", "math_engine ran"),
    ]
    return TestResult(
        "simple_budget", "Simple two-number budget", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


def tc_allocation_spot_check(url: str, key: str) -> TestResult:
    """
    Independent numbers to catch allocation drift or rounding errors.

    income=$6,800  expenses=$2,100  net=$4,700
    savings=$2,350  groceries=$940  utilities=$587.50  entertainment=$822.50
    """
    prompt = (
        "I bring home $6,800 a month. "
        "My fixed bills are $2,100. "
        "Create a savings plan."
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt, bypass_cache=True)
    checks = [
        chk_contains(content, "6,800",    "income present"),
        chk_contains(content, "2,100",    "expenses present"),
        chk_contains(content, "4,700",    "net surplus correct (6800-2100=4700)"),
        chk_contains(content, "2,350",    "savings 50% of net"),
        chk_contains(content, "940",      "groceries 20% of net"),
        chk_contains(content, "587.50",   "utilities 12.5% of net"),
        chk_contains(content, "822.50",   "entertainment 17.5% of net"),
        chk_node_visited(nodes, "math_engine", "math_engine ran"),
    ]
    return TestResult(
        "allocation_spot_check", "Allocation spot-check ($6,800 income)", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


def tc_research_routing(url: str, key: str) -> TestResult:
    """
    Research question — must route to research path, must NOT be cached,
    and must NOT produce a financial allocation table.
    Uses a fresh topic (term vs whole life insurance) unlikely to be in cache.
    """
    prompt = (
        "What is the difference between term life and whole life insurance, "
        "and which is generally recommended for a 35-year-old?"
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt)
    checks = [
        chk_not_cached(cached,                                    "pipeline ran (research never cached)"),
        chk_node_visited(nodes, "grounding",                      "grounding node ran"),
        chk_not_contains(content, "ALLOCATION MATRIX",            "no budget table in research answer"),
        chk_not_contains(content, "Net Available Surplus",        "no financial summary in research answer"),
    ]
    return TestResult(
        "research_routing", "Research routing + cache exclusion", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


def tc_cache_hit(url: str, key: str) -> TestResult:
    """
    Semantic cache round-trip.
    Round 1: cold run — populates cache.
    Round 2: same prompt — must be a HIT returning in < CACHE_TIMEOUT seconds.

    Uses amounts not covered by other tests to avoid collision.
    income=$7,500  expenses=$2,800  net=$4,700  savings=$2,350
    """
    prompt = (
        "My take-home pay is $7,500 a month. "
        "My fixed expenses total $2,800. "
        "Build a savings plan."
    )

    print("    Round 1 (cold)...", end=" ", flush=True)
    nodes1, content1, _, elapsed1 = run_prompt(url, key, prompt)
    print(f"{elapsed1:.1f}s")

    print("    Round 2 (warm)...", end=" ", flush=True)
    nodes2, content2, cached2, elapsed2 = run_prompt(url, key, prompt)
    print(f"{elapsed2:.1f}s")

    # net = 7500-2800 = 4700  savings = 4700*0.5 = 2350
    checks = [
        chk_contains    (content1, "4,700",  "round-1 net surplus correct (7500-2800=4700)"),
        chk_contains    (content1, "2,350",  "round-1 savings 50% of net"),
        chk_cached      (cached2,             "round-2 served from cache"),
        chk_fast        (elapsed2, CACHE_TIMEOUT, f"round-2 returned in < {CACHE_TIMEOUT}s"),
    ]
    return TestResult(
        "cache_hit", "Semantic cache HIT round-trip", prompt,
        all(c.passed for c in checks), checks, nodes2, cached2, elapsed2,
    )


def tc_annual_income(url: str, key: str) -> TestResult:
    """
    Annual income with monthly expense — system must normalize $60,000/year to
    $5,000/month before allocation math runs. Catches the bug where annual
    figures were silently treated as monthly (12x error).

    annual income = $60,000/yr → $5,000/mo  expenses = $1,500/mo  net = $3,500/mo
    default savings 50% of net → $1,750/mo
    """
    prompt = (
        "I earn $60,000 per year and my rent is $1,500 a month. "
        "Build me a budget plan."
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt, bypass_cache=True)
    # 60000/12 = 5000   5000-1500 = 3500   3500*0.50 = 1750
    checks = [
        chk_contains(content, "5,000",     "annual normalized to monthly ($60k/yr → $5k/mo)"),
        chk_contains(content, "1,500",     "monthly expense present"),
        chk_contains(content, "3,500",     "net surplus correct (5000-1500=3500)"),
        chk_contains(content, "1,750",     "savings 50% of net"),
        chk_not_contains(content, "30,000", "raw annual NOT used as net (60000-1500*12=42000 would imply mishandling)"),
        chk_node_visited(nodes, "math_engine", "math_engine ran"),
    ]
    return TestResult(
        "annual_income", "Annual income normalized to monthly ($60k/yr → $5k/mo)", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


def tc_annual_income_with_house_goal(url: str, key: str) -> TestResult:
    """
    The exact user-reported bug scenario: annual income + monthly rent + house goal.
    Verifies the 12x error fix AND the house preset (65% savings) both work together.

    $56,000/year → $4,666.67/mo   rent $1,300/mo   net = $3,366.67/mo
    house preset 65% → savings = $2,188.33/mo
    """
    prompt = (
        "If I make $56,000 per year and spend $1,300 a month on rent, "
        "how should I budget the rest of my money to save for a down payment "
        "on a house in 12 months?"
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt, bypass_cache=True)
    # 56000/12 = 4666.67   4666.67-1300 = 3366.67   3366.67*0.65 = 2188.33
    checks = [
        chk_contains(content, "4,666",     "annual $56k/yr normalized to monthly $4,666"),
        chk_contains(content, "3,366",     "net surplus correct (4666.67-1300=3366.67)"),
        chk_contains(content, "2,188",     "savings 65% of net (house preset)"),
        chk_not_contains(content, "56,000", "raw annual figure NOT shown as monthly income"),
        chk_not_contains(content, "54,700", "the buggy net (56000-1300) NOT present"),
        chk_not_contains(content, "35,555", "the buggy savings (54700*0.65) NOT present"),
        chk_node_visited(nodes, "math_engine", "math_engine ran"),
    ]
    return TestResult(
        "annual_income_house",
        "Annual income + house goal (the user-reported bug scenario)", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


def tc_goal_house(url: str, key: str) -> TestResult:
    """
    Goal-aware allocation: saving for a house shifts savings to 65% of net.

    income=$8,000  expenses=$2,500  net=$5,500
    house preset:  savings=65% → $3,575   groceries=14% → $770
    """
    prompt = (
        "I earn $8,000 a month and my fixed expenses are $2,500. "
        "I'm saving for a house and want a down payment plan."
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt, bypass_cache=True)
    # net = 8000 - 2500 = 5500
    # savings = 5500 * 0.65 = 3575
    # groceries = 5500 * 0.14 = 770
    checks = [
        chk_contains(content, "8,000",  "income present"),
        chk_contains(content, "2,500",  "expenses present"),
        chk_contains(content, "5,500",  "net surplus correct (8000-2500=5500)"),
        chk_contains(content, "3,575",  "savings 65% of net (house preset)"),
        chk_contains(content, "770",    "groceries 14% of net (house preset)"),
        chk_not_contains(content, "2,750", "default 50% savings NOT used"),
        chk_node_visited(nodes, "math_engine", "math_engine ran"),
    ]
    return TestResult(
        "goal_house", "Goal-aware allocation: house / down payment (65% savings)", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


def tc_goal_debt(url: str, key: str) -> TestResult:
    """
    Goal-aware allocation: paying off debt shifts savings to 60% of net.

    income=$6,000  expenses=$1,800  net=$4,200
    debt preset:  savings=60% → $2,520   entertainment=13% → $546
    """
    prompt = (
        "My monthly income is $6,000 and my bills are $1,800. "
        "I'm focused on paying off my credit card debt. Build me a plan."
    )
    nodes, content, cached, elapsed = run_prompt(url, key, prompt, bypass_cache=True)
    # net = 6000 - 1800 = 4200
    # savings = 4200 * 0.60 = 2520
    # entertainment = 4200 * 0.13 = 546
    checks = [
        chk_contains(content, "6,000",  "income present"),
        chk_contains(content, "1,800",  "expenses present"),
        chk_contains(content, "4,200",  "net surplus correct (6000-1800=4200)"),
        chk_contains(content, "2,520",  "savings 60% of net (debt preset)"),
        chk_contains(content, "546",    "entertainment 13% of net (debt preset)"),
        chk_not_contains(content, "2,100", "default 50% savings NOT used"),
        chk_node_visited(nodes, "math_engine", "math_engine ran"),
    ]
    return TestResult(
        "goal_debt", "Goal-aware allocation: debt payoff (60% savings)", prompt,
        all(c.passed for c in checks), checks, nodes, cached, elapsed,
    )


# ── Test registry ─────────────────────────────────────────────────────────────
TESTS = [
    tc_multi_expense,
    tc_simple_budget,
    tc_allocation_spot_check,
    tc_research_routing,
    tc_cache_hit,
    tc_goal_house,
    tc_goal_debt,
    tc_annual_income,
    tc_annual_income_with_house_goal,
]


# ── Runner ────────────────────────────────────────────────────────────────────
def run_all(url: str, key: str) -> list[TestResult]:
    print(f"\nEarl Prime Eval Harness  v1.0\n{'=' * 60}")
    print(f"Server : {url}")
    print(f"Tests  : {len(TESTS)}")
    print()

    results: list[TestResult] = []
    for i, fn in enumerate(TESTS, 1):
        desc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else fn.__name__
        print(f"[{i}/{len(TESTS)}] {desc}")
        try:
            result = fn(url, key)
        except Exception as exc:
            result = TestResult(
                fn.__name__, desc, "", False,
                [CheckResult("execution", False, str(exc))],
                [], False, 0.0, str(exc),
            )

        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        badge  = "✅" if result.passed else "❌"
        print(f"  {badge} {status}  ({result.elapsed_s:.1f}s)")
        for c in result.checks:
            mark = "    ✓" if c.passed else "    ✗"
            print(f"{mark}  {c.name}: {c.detail}")
        print()

    return results


def save_results(results: list[TestResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    data = {
        "run_at":  run_ts,
        "total":   len(results),
        "passed":  sum(1 for r in results if r.passed),
        "failed":  sum(1 for r in results if not r.passed),
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Results saved → {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Earl Prime regression test harness")
    parser.add_argument("--url", default=DEFAULT_URL,  help="Base URL of running Earl Prime")
    parser.add_argument("--key", default=DEFAULT_KEY,  help="x-api-key value")
    args = parser.parse_args()

    # ── Health check ──────────────────────────────────────────────────────────
    try:
        resp = _requests_lib.get(
            f"{args.url}/api/health",
            headers={"x-api-key": args.key},
            timeout=5,
        )
        resp.raise_for_status()
        health = resp.json()
        chroma = "✓" if health.get("chroma") else "✗"
        tav    = "✓" if health.get("tavily") else "✗"
        print(f"Server healthy  chroma={chroma}  tavily={tav}")
    except Exception as exc:
        sys.exit(
            f"\n✗ Cannot reach Earl Prime at {args.url}\n"
            f"  Error: {exc}\n"
            f"  Is the server running?  .\\Start-EarlPrime.ps1\n"
        )

    # ── Run all tests ─────────────────────────────────────────────────────────
    results = run_all(args.url, args.key)

    # ── Summary ───────────────────────────────────────────────────────────────
    total  = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    print("=" * 60)
    print(f"RESULT: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        print("\nFailed tests:")
        for r in results:
            if not r.passed:
                bad = [c.name for c in r.checks if not c.passed]
                print(f"  ✗ {r.test_id}: {bad}")
    else:
        print("  — all green ✅")

    save_results(results, OUTPUT_PATH)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
