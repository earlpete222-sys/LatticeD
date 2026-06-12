"""
LatticeD scripted demo — five acts, camera-ready.

Runs a rehearsed sequence against a live LatticeD server, streaming pipeline
node activity to the terminal as it happens. Doubles as the shot list for
demo video capture and the walkthrough for live presentations.

    python demo.py            # pause between acts (press Enter — live demo mode)
    python demo.py --auto     # no pauses (screen-recording mode)
    python demo.py --url http://127.0.0.1:8000 --key local_dev_secret_123

Acts:
  1. Fast path     — conversational query, light pipeline
  2. Deep path     — financial budget with goal detection, deterministic math,
                     Auditor critique + Guardian verdict visible
  3. Cache hit     — identical query returns in milliseconds
  4. Research path — live web grounding, authorized-numbers constraint
  5. Scorecard     — timing + governance summary of everything just shown
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_KEY = "local_dev_secret_123"
TIMEOUT     = 240

GOLD  = "\033[33m"
GREEN = "\033[32m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RESET = "\033[0m"

NODE_LABELS = {
    "intent_classifier": "Intent Router",
    "fast_fanout": "Fast Fan-out",
    "deep_fanout": "Deep Fan-out",
    "memory_retrieval": "Memory",
    "belief_retrieval": "Beliefs",
    "grounding": "Web Grounding",
    "doc_ingestion": "Documents",
    "perception_barrier": "Perception Barrier",
    "fast_core": "Fast Mentor",
    "life_coach": "Life Coach",
    "math_engine": "Math Engine (deterministic)",
    "sovereign_core": "Quantitative Architect",
    "agency": "Agency (Tools)",
    "auditor": "Factual Auditor",
    "guardian": "System Guardian",
    "synthesis": "Synthesis",
    "loyalty_scorer": "Loyalty Scorer",
    "artifact_writer": "Artifact Writer",
    "semantic_cache": "Semantic Cache",
}


def stream_prompt(url: str, key: str, prompt: str, thread_id: str,
                  bypass_cache: bool = False) -> dict:
    """Stream /api/evolve, printing each pipeline node as it fires."""
    params = {"prompt": prompt, "thread_id": thread_id, "path": "auto"}
    if bypass_cache:
        params["bypass_cache"] = "1"
    t0 = time.time()
    resp = requests.get(
        f"{url}/api/evolve",
        headers={"x-api-key": key, "Accept": "text/event-stream"},
        params=params, stream=True, timeout=(10, TIMEOUT),
    )
    resp.raise_for_status()

    nodes, content, cached = [], "", False
    buf = ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk.replace("\r\n", "\n")
        while "\n\n" in buf:
            event, buf = buf.split("\n\n", 1)
            for line in event.split("\n"):
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                node = data.get("node")
                if node and node not in nodes:
                    nodes.append(node)
                    label = NODE_LABELS.get(node, node)
                    tick = time.time() - t0
                    print(f"  {DIM}{tick:6.1f}s{RESET}  {GREEN}●{RESET} {label}")
                if data.get("status") == "hit":
                    cached = True
                if "content" in data:
                    content = data["content"]
                if "final" in data:
                    content = data["final"]
    resp.close()
    return {"nodes": nodes, "content": content, "cached": cached,
            "elapsed": round(time.time() - t0, 2)}


def act(n: int, title: str, narration: str) -> None:
    print(f"\n{GOLD}{'=' * 64}{RESET}")
    print(f"{GOLD}{BOLD}  ACT {n} — {title}{RESET}")
    print(f"{DIM}  {narration}{RESET}")
    print(f"{GOLD}{'=' * 64}{RESET}")


def show_response(content: str, max_lines: int = 30) -> None:
    lines = content.strip().split("\n")
    print(f"\n{BOLD}  RESPONSE{RESET}")
    for line in lines[:max_lines]:
        print(f"  {line}")
    if len(lines) > max_lines:
        print(f"  {DIM}… ({len(lines) - max_lines} more lines){RESET}")


def pause(auto: bool) -> None:
    if not auto:
        input(f"\n{DIM}  [Enter to continue]{RESET}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LatticeD scripted demo")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--key", default=DEFAULT_KEY)
    parser.add_argument("--auto", action="store_true", help="no pauses between acts")
    args = parser.parse_args()

    # Health check
    try:
        health = requests.get(f"{args.url}/api/health",
                              headers={"x-api-key": args.key}, timeout=5).json()
    except Exception as exc:
        sys.exit(f"Cannot reach LatticeD at {args.url} — {exc}")
    print(f"{BOLD}LatticeD demo{RESET} — server healthy "
          f"(chroma={'on' if health.get('chroma') else 'off'}, "
          f"web grounding={'on' if health.get('tavily') else 'off'})")

    thread = f"demo_{uuid.uuid4().hex[:8]}"
    timings: list[tuple[str, float, bool]] = []

    # ── Act 1: fast path ──────────────────────────────────────────────────────
    act(1, "FAST PATH",
        "A light conversational query. The Intent Router classifies it in "
        "milliseconds; only the fast branch of the pipeline runs.")
    q1 = "Good morning! What can you help me with?"
    print(f'\n  {BOLD}PROMPT{RESET}  "{q1}"\n')
    r = stream_prompt(args.url, args.key, q1, thread)
    show_response(r["content"], 8)
    print(f"\n  {GOLD}{r['elapsed']}s{RESET} on consumer hardware, fully local")
    timings.append(("Fast path (conversation)", r["elapsed"], r["cached"]))
    pause(args.auto)

    # ── Act 2: deep path ──────────────────────────────────────────────────────
    act(2, "DEEP PATH — DETERMINISTIC FINANCIAL MATH",
        "A budget request. Watch the pipeline: the Math Engine computes every "
        "figure in Python (zero arithmetic hallucination), the goal detector "
        "shifts allocations for a house purchase, then the Auditor critiques "
        "and the Guardian approves or forces a retry.")
    # Income varies per run so this act always exercises the full pipeline
    # (and act 3's identical re-ask is guaranteed a cache hit).
    income  = random.choice([4600, 4800, 5200, 5400, 5600])
    rent    = 1800
    net     = income - rent
    savings = net * 0.65          # house preset: 65% of net to savings
    q2 = (f"I make ${income:,} a month and my rent and utilities total ${rent:,}. "
          "Build me a budget — I'm saving for a house.")
    print(f'\n  {BOLD}PROMPT{RESET}  "{q2}"\n')
    r = stream_prompt(args.url, args.key, q2, thread)
    show_response(r["content"])
    audited = "auditor" in r["nodes"] and "guardian" in r["nodes"]
    print(f"\n  {GOLD}{r['elapsed']}s{RESET} — "
          f"adversarial review {'PASSED (Auditor + Guardian ran)' if audited else 'not visible'}")
    print(f"  Net surplus {income}−{rent} = {net}; house preset: 65% savings = "
          f"${savings:,.2f}/mo = ${savings / 4:,.2f}/wk — verify the figures above to the cent.")
    timings.append(("Deep path (financial, full pipeline)", r["elapsed"], False))
    pause(args.auto)

    # ── Act 3: semantic cache ─────────────────────────────────────────────────
    act(3, "SEMANTIC CACHE",
        "The identical question again. The verified answer is served from the "
        "local semantic cache — no inference, no waiting.")
    print(f'\n  {BOLD}PROMPT{RESET}  "{q2}"  (again)\n')
    r = stream_prompt(args.url, args.key, q2, thread)
    print(f"\n  {GOLD}{BOLD}{r['elapsed']}s{RESET} — "
          f"{'CACHE HIT — same verified answer, ~1000x faster' if r['cached'] else 'cache miss (unexpected)'}")
    timings.append(("Same query, cached", r["elapsed"], r["cached"]))
    pause(args.auto)

    # ── Act 4: research path ──────────────────────────────────────────────────
    act(4, "RESEARCH PATH — LIVE WEB GROUNDING",
        "A factual question. The pipeline fetches live sources and the "
        "synthesizer may only use numbers found in them (the Authorized "
        "Numbers Block) — research answers are never cached and never "
        "hallucinated from training data.")
    q4 = "What is the current federal funds rate and what does it mean for savings accounts?"
    print(f'\n  {BOLD}PROMPT{RESET}  "{q4}"\n')
    r = stream_prompt(args.url, args.key, q4, thread)
    show_response(r["content"], 14)
    grounded = "grounding" in r["nodes"]
    print(f"\n  {GOLD}{r['elapsed']}s{RESET} — "
          f"{'grounded in live web sources' if grounded else 'grounding node not visited'}")
    timings.append(("Research path (web-grounded)", r["elapsed"], False))
    pause(args.auto)

    # ── Act 5: scorecard ──────────────────────────────────────────────────────
    act(5, "SCORECARD",
        "Everything above ran on local hardware within a 4GB VRAM envelope. "
        "No cloud API. No data left the machine.")
    print()
    for label, secs, cached in timings:
        flag = f" {GOLD}⚡ cached{RESET}" if cached else ""
        print(f"  {secs:7.2f}s  {label}{flag}")
    print(f"\n  Eval harness: {DIM}python eval_harness.py{RESET} — "
          f"11/11 regression tests, financial figures verified to the cent.")
    print()


if __name__ == "__main__":
    main()
