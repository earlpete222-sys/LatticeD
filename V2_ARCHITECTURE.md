# LatticeD v2 — Architecture North Star

## Why v2

v1 puts the 1.5B model at the center: it does knowledge recall, reasoning, narration, verification, planning, and reflection. Every failure mode we've patched (fabrication, role-flip, pronoun drift, invented details, hallucinated dates, leaked tool calls) is downstream of asking a 1.5B network to do things it structurally can't do reliably.

v2 inverts the relationship. The **system** is the agent. The 1.5B model is **one component** — the narrator that puts results into words. Everything else — what's true, what's relevant, what to say, whether the output is good — is done by deterministic code, typed data structures, retrieval, and rigorously-constrained model calls.

The bet: a 1.5B model doing only what it's good at, embedded in a well-engineered system, will produce dramatically more reliable behavior than a 1.5B model trying to do everything with after-the-fact guards.

## The six layers

```
USER UTTERANCE
  ↓
1. PERCEPTION       deterministic parsers (dates, entities, intent, mood)
  ↓
2. KNOWLEDGE        typed store query (entities, events, relations, time, confidence)
  ↓
3. STRATEGY         decision table → one of ~30 response templates with slot contracts
  ↓
4. NARRATION        1.5B model fills slots, one constrained call per slot
  ↓
5. REVIEW           second model call scores factual fidelity, tone, completeness
  ↓
   TRACE            full causal chain logged for explainability + correction
  ↓
RESPONSE

(async, off-peak)
6. REFLECTION       analyze conversations, distill facts, update strategies, prepare DPO data
```

## What the 1.5B model does in v2

**Only:**
- Paraphrase 20→20 tokens (slot-filling)
- Choose between 2–3 pre-written options (verification > generation)
- Fill a single tightly-constrained slot (an open question about one named detail)
- Sentiment-tag a single sentence (perception assist)
- Generate one open question about one specific detail the system already knows about

**Never:**
- Recall facts — kstore does
- Multi-step reasoning — strategy table does
- Time math or holiday lookup — perceive does
- Decide what kind of response to give — strategy does
- Open-ended generation — slots constrain it
- Invent details — only structured data flows into slots

## Sprint sequence

Each sprint produces a working, tested artifact. v1 keeps running throughout.

| Sprint | Goal | Deliverable |
|---|---|---|
| **49 — kstore foundation** | Typed knowledge store | `latticed/v2/kstore/` — Event/Entity/Relation models, SQLite backend, query API, migration helper from v1 belief graph |
| **50 — perception layer** | Deterministic input parsing | `latticed/v2/perceive.py` — temporal parser, entity extractor, intent classifier (vector + rules), mood tagger |
| **51 — strategies + narration** | First 5 response templates + slot-filler | `latticed/v2/strategies/` — acknowledge_event, recall_from_history, decline_unknown, ask_clarification, schedule_event. `latticed/v2/narrate.py` — constrained slot-filler |
| **52 — always-on reviewer** | Verification layer | `latticed/v2/review.py` — second model call scoring proposed output against retrieved facts + strategy contract |
| **53 — v2 endpoint + A/B** | End-to-end working v2 path | `/api/v2/chat` SSE endpoint, A/B harness, comparative eval suite, decision criteria |
| **54+ — reflection + expansion** | Self-improvement loop + template growth | `latticed/v2/reflect.py` async job; new strategies as use cases surface |

## Migration criteria (v2 takes over from v1)

v2 ships as default when on the same test prompts:
- Factual fidelity ≥ 95% (no fabricated facts, dates, names, or details)
- Fabrication rate < 5% across 100 chat prompts
- Response latency within 2× of v1 (target: equal or better)
- Two-beat shape adherence > 95% (without retries)
- No regressions in the financial/recall/research paths
- Trace coverage 100% (every output explains itself)

## What v1 keeps

- The existing pipeline serves all current users until v2 wins the A/B
- Sprint 43–48 guards (graceful degradation, eval teardown, pairing, output hygiene, two-beat, plural ban) stay live for v1 traffic
- v2 inherits them as a safety net but should rarely trigger them — failures are prevented structurally, not detected after the fact

## What's intentionally NOT in v2 scope

- Multi-user / commercial layer (Sprints deferred per [LatticeD product strategy memo])
- Plugin manifest for paid add-ons (later sprint)
- Larger-model boost gateway (later sprint — the "user controls a stronger model for the hard 1%")
- Voice / camera input (separate add-on territory)

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| v2 ends up worse than v1 in unanticipated ways | Strict A/B gate; no migration until eval criteria met; v1 stays live |
| Multi-sprint scope causes loss of momentum | Each sprint produces a working artifact (kstore is useful alone, perceive layer is useful alone, etc.) |
| Build stalls mid-architecture | Keep narrate.py minimal: works with hardcoded strategies before strategy library grows |
| Strategy library exhausts engineering time | Start with 5 strategies; add only when a real conversation demands one |
| Migration leaves v1 unmaintained | Treat v1 as legacy after v2 ships — bugfixes only, no new features |

## Working principles

- **Structured data beats strings.** Whenever we're tempted to store something as natural language, ask if it could be typed instead.
- **Determinism beats inference.** When something can be computed, computed. The model is the last resort, not the first.
- **Verify, don't trust.** Every model output goes through review before reaching the user.
- **Trace everything.** Every response has a causal chain. Explainability is correctness's twin.
- **Templates beat generation.** Open generation is where hallucination lives. Slot-filling is where reliability lives.
- **Small is fine.** A 1.5B network doing one tiny thing per call is a different animal than one doing big things per call.
