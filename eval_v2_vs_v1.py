#!/usr/bin/env python3
"""eval_v2_vs_v1.py — A/B comparison harness for LatticeD v1 vs v2.

Sends each prompt in TESTS to BOTH /api/evolve (v1) and /api/v2/chat (v2),
then runs the v2 deterministic check suite (banned-plural, role-flip,
leaked-internals, anchor-references, invented-dates) against BOTH outputs.

Reports per-prompt and aggregate results so we can decide whether v2 has
crossed the migration gate:
    - factual fidelity   ≥ 95%
    - fabrication rate   <  5%
    - latency comparable (within 2x)
    - two-beat shape adherence > 95% (without retries)
    - no regressions in financial / recall / research paths

Usage:
    python eval_v2_vs_v1.py
    python eval_v2_vs_v1.py --url http://127.0.0.1:8000 --key local_dev_secret_123
    python eval_v2_vs_v1.py --only v2     # only run v2 (skip v1)
    python eval_v2_vs_v1.py --prompts 5   # subset for quick smoke

Exit code: 0 if v2 meets migration gate, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests as _requests_lib
except ImportError:
    sys.exit("Install requests:  pip install requests")

# We import the v2 check functions directly so the same standard the
# /api/v2/chat reviewer applies in production is what the harness uses
# to evaluate outputs.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from latticed.v2.review.checks import (  # noqa: E402
    check_no_banned_plural,
    check_no_role_flip,
    check_no_leaked_internals,
    check_anchor_references,
    check_no_invented_dates,
)
from latticed.v2.perceive import perceive  # noqa: E402
from latticed.v2.review.types import Severity  # noqa: E402


# ── Configuration ──────────────────────────────────────────────────────────
DEFAULT_URL    = "http://127.0.0.1:8000"
DEFAULT_KEY    = "local_dev_secret_123"
DEFAULT_TIMEOUT = 240
OUTPUT_PATH    = HERE / "latticed" / "runtime" / "outputs" / "v2_vs_v1_results.json"


# ── Test prompts (the live failure + a representative spread) ──────────────
@dataclass
class Probe:
    id: str
    prompt: str
    description: str
    expected_shape_hint: str = "two_beat"   # used for anchor-check gating
    forbid: tuple[str, ...] = ()            # substrings that MUST NOT appear


PROBES: list[Probe] = [
    Probe(
        id="father_day_live_failure",
        prompt="Sunday was Father's Day I spoke with my dad had a great conversation",
        description="The live failure prompt: assistant fabricated 'amazing personality' + used 'we talked'.",
        expected_shape_hint="two_beat",
        forbid=("amazing personality", "we talked", "first saturday"),
    ),
    Probe(
        id="brother_share",
        prompt="Caught up with my brother today",
        description="Simple share-event with a relation mention.",
        expected_shape_hint="two_beat",
    ),
    Probe(
        id="park_share",
        prompt="Spent the morning at the park",
        description="Share-event with a place mention.",
        expected_shape_hint="two_beat",
    ),
    Probe(
        id="long_week",
        prompt="It's been a long week.",
        description="Mood-laden share without specific entity.",
        expected_shape_hint="two_beat",
    ),
    Probe(
        id="recall_fun_empty",
        prompt="What do I like to do for fun?",
        description="Recall query against potentially-empty kstore.",
        expected_shape_hint="free",
    ),
    Probe(
        id="schedule_call_mom",
        prompt="Remind me to call mom tomorrow",
        description="Schedule intent with what + when.",
        expected_shape_hint="schedule_confirm",
    ),
    Probe(
        id="thanksgiving_holiday",
        prompt="Thanksgiving is coming up and I'm hosting this year",
        description="Holiday share — should NOT fabricate a wrong holiday or date.",
        expected_shape_hint="two_beat",
        forbid=("father's day", "christmas", "easter"),   # wrong holidays
    ),
    Probe(
        id="meta_about_system",
        prompt="What do you know about me?",
        description="Meta question — reply should not fabricate facts.",
        expected_shape_hint="free",
    ),
    Probe(
        id="greeting",
        prompt="hi",
        description="Chitchat baseline.",
        expected_shape_hint="free",
    ),
]


@dataclass
class ProbeOutcome:
    probe_id: str
    api: str                # "v1" or "v2"
    content: str
    elapsed_s: float
    error: Optional[str] = None
    checks: dict = field(default_factory=dict)
    fatal_failures: list[str] = field(default_factory=list)
    forbid_hits: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (self.error is None
                and not self.fatal_failures
                and not self.forbid_hits)


# ── HTTP helpers ──────────────────────────────────────────────────────────
def _parse_sse(event_text: str, state: dict) -> None:
    for line in event_text.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if ev.get("phase") == "Final":
            state["content"] = ev.get("content", "")


def _stream(url: str, params: dict, headers: dict, timeout: int) -> tuple[str, float]:
    started = time.time()
    state: dict = {"content": ""}
    resp = _requests_lib.get(
        url, headers=headers, params=params, stream=True,
        timeout=(10, timeout),
    )
    resp.raise_for_status()
    buf = ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        buf = buf.replace("\r\n", "\n")
        while "\n\n" in buf:
            event, buf = buf.split("\n\n", 1)
            _parse_sse(event, state)
    if buf.strip():
        _parse_sse(buf, state)
    resp.close()
    return state["content"], round(time.time() - started, 2)


def call_v1(url: str, key: str, prompt: str, timeout: int) -> tuple[str, float]:
    tid = f"abv1_{uuid.uuid4().hex[:8]}"
    return _stream(
        f"{url}/api/evolve",
        {"prompt": prompt, "thread_id": tid, "path": "auto", "bypass_cache": "1"},
        {"x-api-key": key, "Accept": "text/event-stream"},
        timeout,
    )


def call_v2(url: str, key: str, prompt: str, timeout: int) -> tuple[str, float]:
    tid = f"abv2_{uuid.uuid4().hex[:8]}"
    return _stream(
        f"{url}/api/v2/chat",
        {"prompt": prompt, "thread_id": tid},
        {"x-api-key": key, "Accept": "text/event-stream"},
        timeout,
    )


# ── Scoring ───────────────────────────────────────────────────────────────
def score_output(probe: Probe, content: str) -> ProbeOutcome:
    """Apply the v2 deterministic check suite to ANY output (v1 or v2).
    Same standard for both."""
    outcome = ProbeOutcome(
        probe_id=probe.id, api="?", content=content, elapsed_s=0.0,
    )
    now = datetime.now(timezone.utc).astimezone()
    p = perceive(probe.prompt, now=now)
    checks = [
        check_no_banned_plural(content),
        check_no_role_flip(content),
        check_no_leaked_internals(content),
        check_anchor_references(content, p, expected_shape=probe.expected_shape_hint),
        check_no_invented_dates(content, p),
    ]
    outcome.checks = {
        c.axis: {"passed": c.passed, "reason": c.reason, "severity": c.severity.value}
        for c in checks
    }
    outcome.fatal_failures = [
        c.axis for c in checks
        if not c.passed and c.severity == Severity.FATAL
    ]
    lo = content.lower()
    outcome.forbid_hits = [f for f in probe.forbid if f.lower() in lo]
    return outcome


def run_probe(
    probe: Probe, url: str, key: str, timeout: int,
    only: Optional[str] = None,
) -> dict[str, ProbeOutcome]:
    results: dict[str, ProbeOutcome] = {}
    if only != "v2":
        try:
            content, elapsed = call_v1(url, key, probe.prompt, timeout)
            outcome = score_output(probe, content)
            outcome.api = "v1"
            outcome.elapsed_s = elapsed
            results["v1"] = outcome
        except Exception as e:
            results["v1"] = ProbeOutcome(
                probe_id=probe.id, api="v1", content="", elapsed_s=0.0,
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )
    if only != "v1":
        try:
            content, elapsed = call_v2(url, key, probe.prompt, timeout)
            outcome = score_output(probe, content)
            outcome.api = "v2"
            outcome.elapsed_s = elapsed
            results["v2"] = outcome
        except Exception as e:
            results["v2"] = ProbeOutcome(
                probe_id=probe.id, api="v2", content="", elapsed_s=0.0,
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )
    return results


# ── Reporter ──────────────────────────────────────────────────────────────
def render_run(probe: Probe, outcomes: dict[str, ProbeOutcome]) -> None:
    print(f"\n[{probe.id}] {probe.description}")
    print(f"  prompt: {probe.prompt!r}")
    for api in ("v1", "v2"):
        if api not in outcomes:
            continue
        o = outcomes[api]
        flag = "PASS" if o.passed else "FAIL"
        print(f"  {api.upper()}: {flag}  ({o.elapsed_s:.1f}s)")
        if o.error:
            print(f"        error: {o.error}")
            continue
        # Truncate long content
        snippet = o.content if len(o.content) < 220 else o.content[:217] + "..."
        print(f"        text: {snippet!r}")
        if o.fatal_failures:
            print(f"        fatal: {o.fatal_failures}")
        if o.forbid_hits:
            print(f"        forbid hit: {o.forbid_hits}")


def aggregate(all_outcomes: list[dict[str, ProbeOutcome]]) -> dict:
    """Compute aggregate stats per API for the migration-gate check."""
    summary = {"v1": {}, "v2": {}}
    for api in ("v1", "v2"):
        outcomes = [r[api] for r in all_outcomes if api in r]
        if not outcomes:
            continue
        total = len(outcomes)
        errored = sum(1 for o in outcomes if o.error)
        passed = sum(1 for o in outcomes if o.passed)
        fabrication = sum(
            1 for o in outcomes
            if "no_invented_dates" in o.fatal_failures
            or "anchor_references" in o.fatal_failures
            or o.forbid_hits
        )
        median_s = sorted(o.elapsed_s for o in outcomes)[total // 2] if total else 0
        summary[api] = {
            "total": total,
            "errored": errored,
            "passed": passed,
            "pass_rate": round(passed / total, 3) if total else 0,
            "fabrication_count": fabrication,
            "fabrication_rate": round(fabrication / total, 3) if total else 0,
            "median_elapsed_s": median_s,
        }
    return summary


def migration_gate_passed(summary: dict) -> tuple[bool, list[str]]:
    """Apply the v2 architecture migration criteria from V2_ARCHITECTURE.md.

    factual fidelity   >= 95%
    fabrication rate   <  5%
    latency            <= 2x v1
    """
    reasons: list[str] = []
    v2 = summary.get("v2") or {}
    v1 = summary.get("v1") or {}
    if not v2:
        reasons.append("v2 had no results")
        return False, reasons
    if v2.get("pass_rate", 0) < 0.95:
        reasons.append(f"v2 pass_rate {v2.get('pass_rate')} < 0.95")
    if v2.get("fabrication_rate", 1) >= 0.05:
        reasons.append(f"v2 fabrication_rate {v2.get('fabrication_rate')} >= 0.05")
    if v1 and v2.get("median_elapsed_s", 0) > 2 * (v1.get("median_elapsed_s") or 1):
        reasons.append(
            f"v2 median latency {v2.get('median_elapsed_s')}s > 2x v1 "
            f"({v1.get('median_elapsed_s')}s)"
        )
    return (not reasons), reasons


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="A/B harness: LatticeD v1 vs v2")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--key", default=DEFAULT_KEY)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--only", choices=("v1", "v2"), default=None,
                    help="Only run one API (skip the other)")
    ap.add_argument("--prompts", type=int, default=0,
                    help="Limit to first N probes (0 = all)")
    args = ap.parse_args()

    probes = PROBES[:args.prompts] if args.prompts > 0 else PROBES
    print(f"\nLatticeD A/B harness  v0.1")
    print(f"Server  : {args.url}")
    print(f"Probes  : {len(probes)}  (only={args.only})")
    print("=" * 60)

    # Health check up front so we fail fast if the server isn't up.
    try:
        r = _requests_lib.get(
            f"{args.url}/api/health",
            headers={"x-api-key": args.key}, timeout=5,
        )
        r.raise_for_status()
    except Exception as e:
        sys.exit(f"\nXX  Cannot reach {args.url}: {e}")

    all_outcomes: list[dict] = []
    for probe in probes:
        outcomes = run_probe(probe, args.url, args.key, args.timeout, args.only)
        render_run(probe, outcomes)
        all_outcomes.append(outcomes)

    summary = aggregate(all_outcomes)
    print("\n" + "=" * 60)
    print("Aggregate")
    for api in ("v1", "v2"):
        if not summary.get(api):
            continue
        s = summary[api]
        print(f"  {api.upper()}: passed {s['passed']}/{s['total']} "
              f"({s['pass_rate']*100:.0f}%)  "
              f"fabrication {s['fabrication_rate']*100:.0f}%  "
              f"median {s['median_elapsed_s']:.1f}s  "
              f"errors {s['errored']}")

    gate_ok, reasons = migration_gate_passed(summary)
    print("\nMigration gate: " + ("PASS — v2 is ready to take over" if gate_ok
                                   else "FAIL — " + "; ".join(reasons)))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "url": args.url,
        "summary": summary,
        "gate_passed": gate_ok,
        "gate_reasons": reasons,
        "outcomes": [
            {api: asdict(o) for api, o in outcomes.items()}
            for outcomes in all_outcomes
        ],
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nResults saved -> {OUTPUT_PATH}")

    sys.exit(0 if gate_ok else 1)


if __name__ == "__main__":
    main()
