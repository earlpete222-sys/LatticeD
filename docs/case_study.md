# LatticeD: A Self-Correcting Multi-Agent AI Framework
### Built by Earl D. Peterkin | Philadelphia, PA

---

## 1. The Insight

*"No complex problem was ever solved by a single person with a single stream of thought."*

That is the idea behind LatticeD. Everything else in this document is proof of it.

---

The human brain does not think in a straight line. It rewires itself through neuroplasticity, distributes cognitive load across specialized regions, and coordinates the results through an architecture refined over millions of years of evolution. The left hemisphere and right hemisphere do not compete — they specialize and then collaborate, passing signals through a structure designed specifically for that handoff. The power of human intelligence is not in any single neuron. It is in the connections. The synapse is where thinking actually happens.

Quantum computers figured this out long before AI did. A qubit does not choose 0 or 1. It holds both simultaneously — existing in superposition, processing multiple possibilities in parallel until a result is needed. Binary computers make a decision at every step. Quantum computers delay that commitment and use the ambiguity productively. That is not just a hardware trick. It is a fundamentally different philosophy about how information should move through a system.

The third thread came from working in structured corporate environments — research facilities, enterprise infrastructure, high-performance organizations. Dow Research Center does not run 400 scientists through a single decision-maker. It has R&D departments and regulatory teams and financial analysts and operations leads, each contributing specialized expertise, all governed by a structure that coordinates the whole — one that maintained 99.9% uptime across mission-critical lab and data workflows precisely because no single point of failure governed the whole system. That structure exists because it works. It has been tested and refined across decades of real-world complexity. The intelligence of a successful organization is not in any one person. It is in the system.

Three different fields. Three different scales. One identical pattern: distributed specialized intelligence, governed by a coordinating layer, producing better outcomes than any single unit could alone.

In 2024, most AI was doing the opposite. One enormous model. A single stream of reasoning. No adversarial pressure on its own thinking. No specialized units cross-checking each other's conclusions. Just a very large system confidently generating answers — with no internal mechanism to question whether those answers were right.

This was the gap. Not a lack of computing power. Not a lack of data. A lack of architecture.

The insight did not come from a computer science degree or an AI research lab. It came from studying health sciences, building computers from scratch, working inside complex organizations, and spending years asking questions — of textbooks, of publications, of AI systems themselves. It came from understanding how the most effective systems in nature and in business actually work, and noticing that AI had not yet learned from them.

The question that followed was simple: *What if instead of one big model trying to think harder, you built a system where small specialists argue their way to a better answer?*

I decided to find out if the Architecture was possible and to what effect. The result is a 13-node pipeline driven by 11 specialized agents — built on consumer hardware, verified by automated testing, and documented in full below.

---

---

## 2. The Problem With How AI Is Being Built

By 2024, GPT-4, Gemini, and Claude were impressive — fluent, fast, and seemingly knowledgeable. They could write code, summarize research, explain complex topics, and hold a conversation that felt almost human. And they all shared the same fundamental flaw.

You don't need a PhD to notice when a confident system is confidently wrong. A background in health sciences trains you to catch it — clinical data has zero tolerance for errors delivered with authority. A misread chart, a missed pattern, a confident wrong answer in a high-stakes environment does not just fail. It causes harm. That training made the problem impossible to ignore.

Hallucination is not a bug in the traditional sense. It is a structural consequence of how these systems are built. One model. One forward pass. No internal mechanism to challenge its own output before it reaches you. GPT-4 hallucinated. Gemini hallucinated. Claude hallucinated. Making models bigger and more capable made the problem more fluent, not less frequent. The hallucinations became harder to catch precisely because they were delivered with greater confidence.

Overconfidence is worse than ignorance. An uncertain system prompts you to verify. A confidently wrong system sends you in the wrong direction without warning — and in medicine, in finance, in law, in any domain where accuracy matters, that is not an acceptable failure mode.

The deeper problem was the absence of adversarial pressure inside the model itself. There was no internal voice asking *"wait — is that actually right?"* No auditor. No challenger. No second opinion. Just output. In every high-stakes human system — medicine, law, finance, scientific research — there is a mandatory review layer built into the process. Peer review. Second opinions. Appeals. Cross-examination. These mechanisms exist because we learned, over centuries, that single-stream thinking fails under pressure. AI had none of this built in.

The corporate parallel was equally clear. A CEO who never gets contradicted does not make better decisions — they make more confident bad ones. The best organizations actively build in challenge. Red teams. Devil's advocates. Audits. Boards. The structure of accountability is what separates institutions that last from ones that collapse under their own blind spots. The leading AI systems of 2024 had no equivalent structure.

Scaling was not going to fix this. The industry's answer to every failure mode was to train a bigger model on more data. To use the most widely understood public baseline: GPT-3 required 175 billion parameters at its 2020 release. Subsequent frontier models pushed further still, though their exact sizes are largely undisclosed. But the problem was never size — it was architecture. A single stream of reasoning, regardless of how capable the model generating it is, has no mechanism to catch its own errors. Every weakness in that model appears unchecked in the output. There is no diversity of perspective to surface the gaps. LatticeD produces complex, self-corrected reasoning using two coordinated 1.5 billion parameter models — orders of magnitude smaller than the frontier — by investing in structure rather than scale.

Not being inside the AI industry turned out to be an advantage. Three years of building custom computers, mining rigs, and studying how systems work — from Commodore 64 to cryptocurrency infrastructure — meant approaching AI the way a user approaches it: *does this actually work, and what breaks when it doesn't?* The answer, in 2024, was that the most widely used AI systems were optimized for benchmark performance, not real-world reliability under adversarial conditions. They looked good on tests. They failed quietly in practice.

The solution was already visible — in the brain, in quantum mechanics, in the structure of every effective human organization. It just had not been applied to AI yet.

LatticeD was built around three direct responses to these failures: an **Auditor agent** that critiques every output before it reaches the user, a **Guardian agent** that can reject a response and force the system to try again, and a **Fact Extractor** that pulls verified claims into a persistent belief graph — so the system remembers what it has confirmed to be true and cannot contradict itself across sessions.

The architecture to fix the problem already existed. It just needed to be built.

---

---

## 3. The Architecture: Building a Digital Brain

### 3A. The Framework Philosophy

A company does not hire one genius to do everything. It hires specialists — an R&D department, a compliance team, a financial analyst, an operations lead — and coordinates their expertise through a governing structure. The intelligence of a successful organization is not in any single employee. It is in the system. LatticeD is built on the same principle.

LatticeD fields 11 specialized agents across a 13-node pipeline, each with a defined role and operating only within that role. The Intent Router classifies what kind of thinking a prompt requires. The Quantitative Architect builds the financial or analytical plan. The Factual Auditor reviews that plan for errors, contradictions, and hallucinations. The System Guardian decides whether the output is acceptable or must be retried — enforcing a maximum of 2 retry cycles before forcing the pipeline forward, preventing infinite loops while still guaranteeing that every output faces adversarial review. The Executive Arbiter synthesizes the final response. None of these agents does another's job. The specialization is not a constraint — it is the source of the system's capability.

This is where the argument for small models becomes concrete. A 1.5 billion parameter model attempting to be everything — conversationalist, mathematician, researcher, fact-checker, synthesizer — will be mediocre at most of those things most of the time. The same 1.5 billion parameter model tasked with doing one thing precisely, inside a structure that coordinates its output with other specialists, produces something neither model could achieve alone. The architecture multiplies the capability of the model. More can be done with less — not by making the models smarter, but by making the structure smarter.

**Temperature as behavioral diversity.** Running agents at different temperature settings is not a technical detail. It is architectural intent. A lower temperature produces a conservative, precise, reliable output — the agent commits to what it knows. A higher temperature produces an exploratory, creative output — the agent reaches further, challenges assumptions, surfaces possibilities the conservative agent would not consider. LatticeD runs both simultaneously on certain tasks, comparing outputs before proceeding. The tension between the conservative and exploratory positions is where novel thinking emerges. This is emergent behavior by design: no single agent is doing something remarkable, but what they produce together consistently exceeds what any one of them would produce alone.

**The adversarial structure as the system's conscience.** When humans face complex decisions, we do not simply generate an answer. We weigh good against bad, benefit against harm, short-term gain against long-term consequence. We ask whether the end justifies the means — more precisely, whether the benefit outweighs the risk. We consider how our decisions affect the people around us. We fact-check our own reasoning. We hold competing possibilities in mind simultaneously and evaluate them against each other before committing to a course of action. This is not a feature of exceptional intelligence. It is the baseline of human cognition.

LatticeD builds this process into its architecture as a structural requirement. The Factual Auditor reviews every output as a mandatory pipeline stage — never optional. The System Guardian issues a binary verdict: approved, or rejected and retried. The critique from a rejected pass is injected directly into the next attempt, so the system improves *because* the previous output was wrong, not despite it. No response reaches the user without surviving this loop. Adversarial review is not a safeguard added after the fact. It is structural.

The Guardian also enforces non-negotiable constraints. Certain failure conditions — confidence floors, contradiction detection, output schema violations — trigger automatic rejection regardless of the response's other qualities. These constraints are encoded in the framework, not learned from training data. The system has hard boundaries it cannot argue past.

**Memory as the difference between a stateless tool and a system that learns.** A system that forgets every conversation can retrieve, summarize, and generate — but it cannot adapt or build context with the user over time. Persistent memory is what makes the output of session 10 more useful than the output of session 1. Without it, every interaction starts from zero. With it, the system accumulates a working model of the user that improves response quality on every subsequent query.

The democratization argument follows directly from the hardware reality. LatticeD runs on a consumer gaming PC with 4GB of VRAM, using two models — deepseek-r1:1.5b and qwen2.5-coder:1.5b — with no cloud API, no GPU cluster, and no recurring inference cost.

**Per-model semaphore isolation: hardware-aware inference scheduling.** Running 11 agents across a 13-node pipeline on 4GB of VRAM is not straightforward. Without resource management, multiple agents attempting simultaneous inference on the same model would compete for VRAM and either crash or serialize unpredictably. LatticeD solves this with an asymmetric semaphore system tuned specifically to its architecture.

deepseek-r1:1.5b — used for reasoning-intensive tasks including intent routing, auditing, guardian decisions, and final synthesis — runs under `reasoning_sem(1)`: a mutual exclusion lock that permits exactly one deepseek-r1 inference at a time. This reflects the model's role: these are sequential, high-stakes decisions that should not race each other.

qwen2.5-coder:1.5b — used for structural translation, financial synthesis, fact extraction, and schema-constrained output — runs under `synthesis_sem(2)`: a semaphore permitting two simultaneous inferences. This asymmetry is not arbitrary. It is specifically engineered to support parallel speculative branching in the Quantitative Architect node, where two qwen2.5-coder instances — one conservative, one exploratory — execute simultaneously without queuing against each other.

Critically, a deepseek-r1 inference and a qwen2.5-coder inference can run concurrently because they hold different semaphores. The system achieves genuine multi-model parallelism within a 4GB VRAM envelope.

**VRAM keep_alive: eliminating reload latency across the pipeline.** Each model is configured with a 2-minute VRAM residency window. Once loaded, both models stay resident in VRAM for 2 minutes after their last use — covering the full duration of a typical pipeline pass (60–120 seconds on consumer hardware). Without this, each agent invocation would trigger a model reload: an estimated 5–15 second overhead per call, compounding across 11 agent invocations in a single pipeline pass. With both models warm and the KV cache active at approximately 293MB per model (at 4,096-token context), that reload cost drops to zero for every node after the first. After 2 minutes of idle time, the model is automatically evicted — reclaiming VRAM when the system is not in use.

Each agent enforces a 240-second inference timeout, ensuring the system never hangs on a slow model response and always returns a result to the user. If complex reasoning can be achieved with this hardware through architectural design, then meaningful AI becomes accessible to individuals, small businesses, independent researchers, and healthcare providers who cannot afford enterprise infrastructure. The framework does not require expensive hardware. It requires careful thinking about how that hardware is used.

---

### 3B. The Pipeline

```
User Prompt
     │
     ▼
┌─────────────────────────────┐
│   INTENT CLASSIFICATION     │  Layer 1: Regex (0ms)
│   Three-Tier Router         │  Layer 2: Vector Encoder (5ms)
│                             │  Layer 3: LLM Router (fallback only)
└─────────────┬───────────────┘
              │
    ┌─────────┴──────────┐
    │                    │
  FAST PATH           DEEP PATH
  (conversation)      (analysis / research)
    │                    │
    ▼            ┌───────┴────────┬──────────────┬──────────────┐
  Fast Core    Memory          Belief        Grounding      Documents
  (direct)   Retrieval       Retrieval      (Tavily)      Ingestion
                    └───────┬────────┴──────────────┴──────────────┘
                            │
                            ▼
                   PERCEPTION BARRIER
                   (synchronization point)
                            │
                            ▼
                      MATH ENGINE
                   (deterministic math,
                    goal-aware allocation)
                            │
                            ▼
                  QUANTITATIVE ARCHITECT
                  (parallel: conservative
                   + exploratory branches)
                            │
                            ▼
                    FACTUAL AUDITOR
                            │
                            ▼
                   SYSTEM GUARDIAN
                    /           \
              APPROVED         REJECTED
                  │                │
                  │         (critique injected,
                  │          loop back to Architect)
                  ▼
              SYNTHESIS
                  │
                  ▼
           LOYALTY SCORER
                  │
                  ▼
          ARTIFACT WRITER
                  │
                  ▼
           Final Response
```

**The pipeline: 13 nodes, 11 agents, one coordinated pass.** Every prompt that enters LatticeD travels through a 13-node execution pipeline. Not every node activates for every prompt — the system routes each query through only the nodes its classification requires, conserving compute without sacrificing capability.

The 11 specialized agents that drive these nodes are:

| # | Agent | Role |
|---|---|---|
| 1 | **Intent Router** | Classifies prompts into execution paths (LLM fallback only) |
| 2 | **Fast Mentor** | Handles light conversational queries on the fast path |
| 3 | **Life Coach** | Handles personal and emotional queries on the coach path |
| 4 | **Grounding Extractor** | Parses live web search results into structured fact lists |
| 5 | **Quantitative Architect (conservative)** | Builds financial plans at low temperature |
| 6 | **Quantitative Architect (exploratory)** | Parallel branch at higher temperature |
| 7 | **Research Synthesizer** | Answers research questions using only authorized facts |
| 8 | **Factual Auditor** | Critiques every output for errors and contradictions |
| 9 | **System Guardian** | Issues binary APPROVE / REJECT verdict, forces retries |
| 10 | **Executive Arbiter** | Synthesizes the final response (the "Synthesis" node) |
| 11 | **Fact Extractor** | Pulls verified facts from completed sessions into the belief graph |

A 12th component — the **Loyalty Scorer** — runs as a deterministic scoring node rather than a language model agent. It evaluates every completed response across five weighted dimensions and writes the scores to a persistent ledger.

These 11 agents are not 11 separate models. They are 11 distinct *roles* — each defined by a unique combination of system prompt, temperature setting, output schema, and execution context — running on top of two underlying 1.5 billion parameter models (deepseek-r1 for reasoning-intensive roles, qwen2.5-coder for structural and synthesis roles). Specialization here is achieved at the orchestration layer, not by training new model weights. This is precisely what makes the architecture portable: anyone with the two base models and the framework can run the same 11 agents on their own hardware without any model fine-tuning.

**Intent Classification: spending intelligence only where it is needed.** Before any agent runs, LatticeD determines what kind of thinking the prompt requires — and does so in three escalating tiers. The first tier is pattern matching: financial prompts with dollar amounts, shell commands, and research topics trigger immediate routing with zero latency and zero LLM cost. The second tier is a vector encoder — a sentence embedding model that compares the prompt against known intent anchors in approximately five milliseconds, with no LLM required. Only if both tiers fail to produce a confident classification does the system invoke an LLM for routing. The result is a system that applies computational cost proportionally to actual need: simple prompts are routed instantly, ambiguous prompts receive the full classification treatment.

**Four execution paths.** Every classified prompt enters one of four paths: fast (general conversation), deep (financial analysis and research), coach (personal development and emotional support), or research (factual questions requiring live web grounding). Each path activates a different subset of the pipeline. The system does not run every node for every query — it runs exactly what the query requires, reducing latency without reducing capability where it matters.

**The Authorized Numbers Block: structural hallucination prevention for research.** When LatticeD handles a research question — IRA contribution limits, tax brackets, insurance regulations, investment rules — it does not ask the language model to recall what it learned during training. Training data has a cutoff. Regulations change. A model confidently citing a 2022 IRA limit in 2026 is not malfunctioning — it is doing exactly what it was trained to do. The problem is architectural.

LatticeD addresses this with a two-stage research synthesis pipeline. In stage one, a dedicated Grounding Extractor agent receives the raw web search results from Tavily and extracts every specific dollar amount, percentage, age threshold, and date into a structured JSON fact list. In stage two, those verified figures are assembled into an Authorized Numbers Block — a clearly demarcated section of the Research Synthesizer's prompt that lists every specific figure the model is permitted to cite, with an explicit instruction that any number not present in the block is forbidden. The model cannot substitute, round, estimate, or recall from training data. It must cite exactly what the block contains or state that the information was not found in sources.

The measurable result: before this mechanism was implemented, the system cited $23,500 for the 2024 IRA contribution limit — the 401(k) limit from training data, not the correct $7,000 IRA limit from the live web source. After implementation, the system correctly cited $7,000, sourced directly from the Tavily result. The authorized numbers block did not make the model smarter. It made the model's output structurally constrained by verified facts, eliminating an entire category of financial hallucination from the research path.

**Parallel execution and the Perception Barrier: inspired by quantum thinking.** On the deep path, four agents run simultaneously: Memory Retrieval queries the semantic store for relevant past conversations, Belief Retrieval surfaces verified facts from the belief graph, Grounding searches the live web via Tavily, and Document Ingestion reads any files the user has provided to the system. None of these agents waits for another. They execute in parallel and meet at the **Perception Barrier** — a dedicated synchronization node that holds the pipeline until all four parallel branches complete, then passes the fully aggregated context forward as a single coherent package.

The Perception Barrier is not a passive waiting mechanism. It is a structural guarantee: no downstream agent — the Math Engine, the Architect, the Auditor — ever operates on partial context. Every node after the barrier has access to the complete picture: historical memory, verified beliefs, live web data, and local documents, all simultaneously available. Without the barrier, a race condition between parallel agents could result in the Architect receiving memory but not grounding, or grounding but not beliefs — producing a response that is partially informed and fully unaware of what it is missing.

The quantified result from live system timing: all four parallel agents — memory retrieval, belief retrieval, web grounding, and document ingestion — completed within a 2.1-second window during pipeline testing (7.22 seconds to 9.13 seconds from prompt receipt on consumer hardware). Sequential execution of these four operations would have required each to wait for the previous to complete. Parallel execution compresses them into a single wait period bounded by the slowest of the four — in this case, the Tavily web search. The design intuition is borrowed from quantum computing: hold multiple possibilities simultaneously, resolve them when a result is required. The implementation is conventional async parallelism with a synchronization gate. The result is the same: multiple operations completing in the time it would take to run one.

**The Math Engine: deterministic accuracy through Python.** Language models are probabilistic text generators. When a model performs arithmetic, it is not computing — it is pattern-matching against examples of arithmetic it has seen during training. This distinction matters enormously in financial contexts where a dollar figure that is close is still wrong.

LatticeD resolves this structurally. For every financial prompt, a deterministic Python engine intercepts the calculation before any language model is involved. Python's IEEE 754 double-precision floating point arithmetic is accurate to 15–17 significant decimal digits — sufficient to produce exact results for any dollar amount up to $999 billion, with zero rounding error at the cent level. The engine parses every dollar figure in the prompt using a label-aware extractor that classifies each amount as income or expense based on the keywords surrounding it, aggregates them correctly regardless of how many line items are present, and computes net surplus and full allocation breakdowns to the cent.

The output is a locked numeric blueprint — a structured set of verified figures passed to the Quantitative Architect as authoritative input, not as a prompt to interpret. The Architect's role is to contextualize and format the plan. It cannot alter the numbers. Arithmetic hallucination on this path is structurally prevented: the numbers enter the pipeline from Python and exit in the final response unchanged. The Architect can still describe those numbers poorly in surrounding prose — narrative quality is a separate concern handled by the Auditor and Guardian — but it cannot substitute, round, or invent a single dollar figure.

The practical result: LatticeD's eval harness — a suite of automated regression tests run against the live system — passes at 100% accuracy on multi-expense financial calculations, including cases requiring aggregation of three or more labeled expense types and allocation breakdowns verified to the cent ($587.50, $822.50, $1,730.00). These are not approximations. They are exact.

**How the Math Engine interacts with the rest of the system.** The verified figures do not disappear after a single response. The Math Engine writes the computed income, expenses, net surplus, and active financial goal to the state that flows through every subsequent node in the pipeline. The Auditor checks the Architect's narrative against these numbers. The Guardian cannot approve a response that contradicts them. The Synthesis node rebuilds the final allocation table directly from the Python-computed values — not from the Architect's prose — so LLM formatting errors can never corrupt the numbers the user receives.

The Math Engine also detects financial goals stated in natural language — "I'm saving for a house," "I'm focused on paying off debt," "I need an emergency fund" — and shifts the allocation model to a goal-specific preset. A user saving for a house sees a 65% savings rate. A user paying off debt sees 60%. These shifts are written to the belief graph with a confirmed confidence score of 0.58 (versus 0.35 for unconfirmed observations), ensuring the system recalls the goal with high confidence in future sessions while subjecting it to the same exponential decay as all stored beliefs — a 45-day half-life that prevents the system from treating old goals as permanent without reinforcement.

**The latency argument, quantified.** The most common criticism of multi-agent systems is that they are slow — that the coordination overhead negates the architectural benefits. LatticeD addresses this through two mechanisms. First, parallel execution on the deep path means that memory retrieval, belief retrieval, web grounding, and document ingestion run simultaneously rather than sequentially — compressing what would be four sequential operations into a single wait period bounded by the slowest of the four. Second, the semantic cache serves verified responses to near-identical prior queries at under 100 milliseconds — a threshold requiring 0.98 cosine similarity to ensure only genuinely equivalent queries receive cached responses, not loosely related ones. The measured result from the eval harness: a cold pipeline run takes 60–120 seconds end to end on consumer hardware. A cache hit on the same query returns in under 100 milliseconds. That is a greater than 99.8% reduction in response latency for repeated queries — with no loss of accuracy, because the cached response was verified before it was stored.

**Parallel speculative branching.** The Quantitative Architect runs two instances simultaneously: a conservative branch at lower temperature that commits to what is known, and an exploratory branch at higher temperature that reaches further. Both are qwen2.5-coder:1.5b instances, both held under the `synthesis_sem(2)` semaphore — meaning neither waits for the other. They execute in true parallel, completing in the time it would take to run one. The system then evaluates both outputs and selects the superior result before passing it to the Auditor. The user receives the benefit of two independent reasoning paths at the cost of one inference window. The debate between the conservative and exploratory positions is never surfaced to the user — but its result always is.

**Three memory layers: the system that learns.** LatticeD maintains a persistent model of the user across three distinct stores, each engineered for a different type of knowledge and a different retrieval pattern.

*Semantic memory* holds full conversation history in a ChromaDB vector store, recalled by cosine similarity rather than keyword matching or recency. The system finds relevant past exchanges based on meaning — a question about retirement savings today can surface a conversation about investment risk from three months ago, if the semantic distance is close enough. Retrieval is bounded by cosine similarity scoring combined with exponential time decay using the same 45-day half-life as the belief graph, ensuring older memories surface only when they remain genuinely relevant.

*The belief graph* holds verified facts extracted from every session — confirmed numbers, stated goals, acknowledged preferences — scored for confidence and subject to exponential decay. A newly confirmed fact enters with a confidence score of 0.58. An unconfirmed observation enters at 0.35. Both decay with a 45-day half-life, dropping below the 0.20 floor and aging out of active retrieval if not reinforced. This decay mechanism is not a limitation — it is a design requirement. A system that holds outdated facts with permanent confidence is not intelligent. It is stubborn. LatticeD's belief graph self-corrects over time without explicit user instruction.

*The semantic cache* serves verified responses to near-identical prior queries at under 100 milliseconds, requiring a 0.98 cosine similarity threshold to ensure only genuinely equivalent prompts receive cached responses. The cache is **intent-aware**: financial plans are cached for 30 days — long enough to serve the same budget question across a month without recomputing, short enough to refresh when income or expenses change. General conversational responses expire after 24 hours. The differentiation reflects a deliberate design decision: the cache understands what kind of knowledge it is holding and applies the appropriate freshness window accordingly.

**Contamination-resistant cache design.** A cache is only as reliable as its rejection criteria. During development, a discovered failure mode demonstrated this precisely: when the pipeline encountered a graph-level error, the error message — not an answer — was stored in the semantic cache and served to subsequent users of the same prompt. The system had learned its own failure. LatticeD addresses this with a two-layer contamination guard. On write: the system checks whether the output begins with the internal error prefix `[GRAPH_ERROR]` before storing — if so, nothing is written. On read: the system re-checks any retrieved cache entry against the same prefix before serving it — if a contaminated entry was written before the write guard existed, it is rejected silently and the full pipeline runs instead. The system heals itself retroactively. Zero contaminated responses reach the user after the guard is active.

Because all stored information originates from the user directly, retrieval is fast, private, and relevant. There is no general-purpose database to search. The system finds what matters because everything it has stored matters to this specific user. Latency decreases. Relevance increases. Privacy is preserved structurally — not as a policy, but as a consequence of architecture.

**The Fact Extractor: closing the loop.** At the end of every session, a dedicated agent reviews the conversation and extracts verifiable facts — confirmed numbers, stated goals, acknowledged preferences — and updates the belief graph accordingly. The system learns not just from what the user says but from what can be confirmed as true. This is how LatticeD accumulates genuine, structured knowledge rather than simply logging conversation history.

**The delivery layer: scoring, auditing, and archiving every response.** After synthesis, two final nodes run before the response reaches the user — neither generates content, but both measure and preserve it.

The **Loyalty Scorer** evaluates every completed response across five weighted dimensions and produces a single composite score per response, stored in a persistent SQLite ledger keyed by thread and timestamp. The dimensions and their weights are configurable but currently set as follows:

| Dimension | Weight | What it measures |
|---|---|---|
| Family alignment | 35% | Does the response reflect commitments and preferences captured in the belief graph about people and priorities the user has named? |
| Reliability | 25% | Did the math engine, auditor, and guardian all complete cleanly without retry exhaustion or fallback paths? |
| Learning contribution | 20% | Did the Fact Extractor identify new verifiable facts to add to the belief graph? |
| Safety | 15% | Did the guardian approve on first pass, or did the response require a corrective retry? |
| Speed | 5% | Did the response complete within the expected latency envelope for its execution path? |

Each dimension scores from 0.0 to 1.0 based on the pipeline state recorded during the response. The composite is the weighted sum. The point is not the absolute number — it is the trend. If the composite score across the most recent N responses drifts downward, the system has measurable evidence of degradation before the user reports it qualitatively. This is the kind of monitoring discipline that distinguishes a tool from a product.

The **Artifact Writer** saves every completed final response as a timestamped markdown file in the system's output directory. Every pipeline completion produces a permanent, human-readable audit record — the prompt, the response, the thread ID, and the timestamp — stored locally and accessible without querying the system. This means 100% of successful pipeline passes generate a persistent audit trail, independent of database availability. If the SQLite interaction ledger fails, the markdown archive survives. The two systems provide redundant records of every interaction the system has ever completed.

**What this produces.** None of the individual components of LatticeD is doing something unprecedented. What is unprecedented is the combination: specialized agents with defined roles, adversarial pressure built into the pipeline as a requirement, parallel execution reducing latency without sacrificing context, deterministic math preventing financial hallucinations, and three memory layers that make the system more useful over time. The whole is demonstrably more capable than the sum of its parts. This is emergent complexity — achieved not by building a bigger model, but by building a better structure.

LatticeD in its current form is a proof of concept. Every node, every agent, every memory layer is a validated component of a larger architecture. The question was whether it was possible and to what effect. The answer is documented here.

---

---

## 4. Building It: Four Months of Implementation, Six Years of Preparation

LatticeD's implementation phase took four months. The thinking behind it took six years.

**2020** — Began using AI systems for self-directed study, asking questions, developing ideas, and exploring concepts across multiple domains.

**2021** — Adopted Microsoft Copilot at Dow Research Center as a one-person automation force-multiplier: writing PowerShell scripts for user migrations, IP resets, software triage, document summarization, and network diagnostics. First sustained exposure to AI as a production tool, not a curiosity.

**2023** — Began using Gemini as a personal mentor for deeper conceptual work. First sustained encounters with hallucination — rare but consequential, with every confident wrong answer causing real workflow disruption. The pattern of "correct-sounding wrong" became impossible to ignore.

**2024** — Began building Gems on Gemini, discovering the importance of persona prompting and stateful context. Established the principle that a well-defined role plus structured memory dramatically narrows the failure surface of any language model.

**2025** — Began systematic study of how AI systems are constrained by their hardware, applying years of hands-on infrastructure experience to the question. Identified the architectural opportunity: small models with hyper-focused roles, fed current factual data, can be highly capable in narrow domains. The principle inherited from years in professional kitchens: *simple is best — do not overreach when the solution is direct.*

**Early 2026** — Began the LatticeD implementation. Four iterative builds across four months. The final architecture is what this document describes.

---

The most instructive part of building LatticeD is that the process of building it proved the necessity of what was being built.

The AI systems used to construct LatticeD — Claude Code, Gemini, and Grok — exhibited every failure mode LatticeD was designed to eliminate. Concepts introduced in one session were forgotten by the next. Architectural decisions agreed upon in one conversation were contradicted in another. Critical implementation details were omitted without warning. At one point, four separate conversations had to be manually pulled apart and restructured into a single coherent direction. The experience was not just frustrating. It was data. Every instance of conversation drift, concept omission, and cross-session inconsistency was a firsthand proof case for the persistent memory architecture, the belief graph, and the adversarial review loop being designed in parallel.

The builder was living inside the problem he was solving. The Auditor, the Guardian, and the Belief node — during the build phase — were played by a single human, manually reviewing every output, challenging every structural claim, and maintaining coherence across sessions that the AI systems themselves could not sustain. The architecture was being lived before it was coded.

---

**Four builds. One direction.**

LatticeD did not emerge from a single design session. It was the product of four successive builds, each targeting a specific bottleneck, each teaching something the next iteration required.

The first builds ran larger quantized models on consumer hardware, accepting system RAM segmentation as a necessary cost — the assumption being that a larger model, even compressed, would produce better results than a smaller one. This assumption did not survive contact with the hardware. Time-to-first-token on a query as simple as *"What is my system date and time?"* stretched to 10–15 minutes. The computer was physically breaking under the load. Thermal throttling. Memory pressure. Response latency that made the system unusable.

The wall was not a failure of effort. It was a failure of assumption.

The pivot came from a background that most AI developers do not have. Years building and servicing high-density compute infrastructure — enterprise data centers, cryptocurrency mining rigs, custom gaming machines — established a specific methodology: identify what is achievable at the highest level of hardware, then back-engineer down to the available system without sacrificing the output. The question was never *"what can my hardware do?"* It was *"what is possible at the top, and how do I get there from here?"*

Applied to AI inference, this meant learning the full stack from first principles. How neural networks process information. How machine learning utilizes GPU memory. How quantization trades model size for inference speed. How context window size affects VRAM consumption — approximately 293MB of KV cache per 1.5 billion parameter model at a 4,096-token context. How model residency eliminates reload latency. How concurrency is bounded by VRAM, not just by CPU threads. This was not coursework. It was months of direct experimentation, live testing, and systematic failure.

The discovery that changed the architecture: quantization does not produce the catastrophic loss of reasoning capability that intuition suggests. A small model, when hyper-focused on a single domain and kept within that domain, produces accurate, reliable, contextually appropriate output. The loss from compression is smaller than the gain from specialization. A 1.5 billion parameter model given one job performs that job well. The same model asked to do everything performs everything poorly.

The architecture followed directly. If small specialized models were viable, the question became coordination: how do you ensure the right agents receive the appropriate tasks, how do you prevent them from conflicting with each other, and how do you make their parallel outputs cohere into a single reliable response? The answer to that question is the 13-node pipeline documented in Section 3.

**The 4GB VRAM ceiling became the design constraint.** Not a compromise to be worked around, but a forcing function to be designed for. Everything — model selection, context window size, semaphore configuration, parallel execution patterns, keep_alive windows — was framed, tested, and optimized against 4GB from the first build. The constraint produced a portable architecture. What runs on 4GB of consumer VRAM scales to enterprise hardware without redesign. The ceiling was chosen deliberately. The floor can be raised later.

---

**Three co-builders. One adversarial process.**

Claude Code, Gemini, and Grok were not passive code generators. They were active participants in the design process — and they disagreed. With each other. With prior decisions. With Earl. The debates were substantive: more than one valid architecture exists for any given problem, more than one way to write any given function, more than one structural approach to reducing latency without sacrificing complexity. The disagreements were productive precisely because no single system had the whole answer.

The process was a live implementation of the framework being built. Multiple specialized agents — each with a different perspective, a different knowledge base, a different approach — arguing toward a better solution, with a human in the loop evaluating every claim. The frustration of managing disagreement between AI systems while simultaneously trying to build a system for managing disagreement between AI systems was clarifying. It confirmed the design. It demonstrated the necessity of every node.

Some of the code produced in these debates broke existing functionality rather than extending it. A component technically correct in isolation introduced conflicts at the integration layer. The resolution was never choosing between competing approaches — it was blending them. Taking the structural insight from one system, the implementation pattern from another, and the edge-case handling from a third, then synthesizing them into something none of the three would have produced independently. This is what the Executive Arbiter does inside LatticeD on every pipeline pass. The build process was the proof of concept for the synthesis mechanism.

---

**The breakthrough.**

Progress in AI system development is easy to feel and hard to measure. The subjective sense that something is working is not evidence. The evidence is the number.

The signal that the architecture was working was time-to-first-token. Watching that metric decrease — measurably, consistently, across successive builds — was the confirmation that the design decisions were producing real results. Not better in impression. Better in measurement. The agent completing its task, the response arriving faster than the previous iteration, the pipeline processing a complex financial query and returning a structured, accurate output within the expected window — this was the "oh shit" moment. Not a dramatic revelation. A measurable result that held.

---

**What four disciplines produced in practice.**

Section 1 introduced the four-domain origin of the framework. The build phase converted each domain into specific engineering decisions.

Health Sciences became the agent topology — specialized roles coordinated by a governing layer, with the Auditor and Guardian serving as the system's structural conscience. Enterprise IT became the hardware-first methodology — the semaphore design, the keep_alive windows, the VRAM budgeting, the insistence that latency is a solvable engineering problem rather than an accepted constraint. MBA coursework became the measurement discipline — the eval harness, the confidence scoring with documented thresholds, the TTL differentiation by intent, the loyalty scorer's weighted dimensions. Quantum-inspired thinking became the parallel execution patterns — the fan-out to four retrieval agents, the speculative branching, the synchronization gate.

A computer science background optimizes for code correctness within established patterns. It does not inherently produce these cross-domain decisions. LatticeD looks different from typical AI research output because it came from outside AI research. The cross-domain perspective was the source of the architecture, not a gap to overcome.

---

**The decision to document.**

Building LatticeD without a team or institutional backing meant the work existed only in code and in conversation logs — accessible to anyone who could read the repository, but not legible to someone who was not in the room when the decisions were made. This case study is the final build artifact. It makes the architectural reasoning explicit, the design decisions traceable, and the results verifiable. The difference between having the concept and being able to show that concept is buildable is how we advance technology.

---

---

## 5. Proof It Works

Proof in AI development takes three forms: external validation from independent sources, live system behavior on real queries, and systematic testing with exact expected outputs. LatticeD has all three.

---

### 5A. Independent Convergence: The Nature Papers

On May 19, 2026, Nature published Google's Co-Scientist paper — *"Accelerating Scientific Discovery with Co-Scientist"* — first announced publicly on February 19, 2025, and peer-reviewed for 15 months before acceptance. The same week, Nature published Robin — *"A Multi-Agent System for Automating Scientific Discovery"* — submitted to arXiv on May 19, 2025 and accepted for the same issue. Two independent research teams. Two papers. One week. The same journal. The same architecture.

Co-Scientist structures its system around a supervisor agent routing tasks to specialized generation, reflection, proximity, evolution, and ranking agents. Its ranking agent hosts an automated ELO tournament: hypotheses debate each other in head-to-head matchups, winners gain points, losers lose them, and the strongest ideas rise over hundreds of iterations. This is adversarial review at institutional scale. LatticeD implements the same principle in its Auditor-Guardian loop: every output faces structured opposition before the user receives it. The mechanism is identical. The scale differs.

Robin's Finch data analysis agent launches 8 independent parallel instances to analyze the same raw experimental data simultaneously, then requires majority consensus — a minimum 50% agreement threshold — before accepting any finding as valid. This is parallel speculative execution followed by fan-in synchronization and consensus gating, operating at substantial scale within a well-resourced research environment.

LatticeD implements the same *pattern* at smaller scale: `synthesis_sem(2)` runs two parallel branches of the Quantitative Architect with different temperature settings, and the Perception Barrier provides the synchronization gate. Two branches is not eight instances, and a winner-selection mechanism is not a 50% majority vote — the implementations differ meaningfully in degree. What is shared is the underlying structural decision: hold multiple speculative outputs in flight, synchronize them at a defined point, and select the strongest. The pattern matches. The scale does not.

The relevance to LatticeD is contextual, not credentialing. Co-Scientist and Robin were built with institutional resources at substantially larger scale. LatticeD was built by one person on consumer hardware, drawing on six years of progressive AI-assisted workflow experience and on cross-domain expertise from health sciences, enterprise IT, and business analytics. The three projects differ in scale, domain, and implementation — what they share is the architectural direction: multi-agent specialization, adversarial review, parallel execution with synchronization, and persistent memory.

That convergence matters because it indicates these structural choices are not stylistic preferences. Multiple independent teams identify them as the right answer to similar problems. The Nature papers do not prove LatticeD works. They establish that the design direction LatticeD pursues is taken seriously by the field. Proof of LatticeD's specific implementation comes from the eval harness, documented in the next subsection.

---

### 5B. Live Proof: The Research Path in Action

The clearest single demonstration of LatticeD's architecture is a query type that breaks most AI systems silently: a factual financial question where the model's training data contains a plausible but wrong answer.

**The test:** What is the 2024 IRA contribution limit?

**Without the Authorized Numbers Block:** The models involved in LatticeD's pipeline were trained on data that includes $23,500 — the 2024 401(k) elective deferral limit. This is a real figure, from the right domain, at the right year. It is wrong for this question. The correct 2024 IRA contribution limit is $7,000. The model, operating from training data alone, returned $23,500 — a real number, wrong context, 236% above the correct answer. This is not a random hallucination. It is a precise, confident, financially consequential error.

**With the Authorized Numbers Block active:** Tavily fetches current content from authoritative sources. The Grounding Extractor parses the results and extracts $7,000 from the live IRS source. The Authorized Numbers Block is constructed. The Research Synthesizer receives one instruction: cite figures from this block exactly, cite nothing outside it, and if a specific figure is not present, state that it was not found in sources. The system returned $7,000. The correct answer, from the correct source, at the correct value. The architectural constraint eliminated a category of error that model capability alone cannot prevent.

**How the system stays current.** IRA contribution limits are adjusted periodically for inflation. A system that caches this answer indefinitely would become wrong the moment the limit changes — and remain confidently wrong until manually corrected. LatticeD's research intent cache expires after 24 hours. The next time the question is asked after that window, the full grounding pipeline re-runs: Tavily fetches fresh sources, the Grounding Extractor pulls the current figure, the Authorized Numbers Block reflects the updated limit. No retraining. No manual refresh. No version update. The 24-hour TTL combined with live web grounding creates a self-updating knowledge layer that maintains accuracy without human intervention. The combination of live grounding, structural number constraints, and temporal cache decay is what separates a system that is accurate today from one that remains accurate as the world changes.

---

### 5C. The Eval Harness: Systematic Proof

AI systems routinely perform well in demonstrations and fail in practice. The difference is systematic testing. Impressions are not evidence. Numbers are.

LatticeD's automated regression harness runs 7 tests against the live system. Each test sends a known prompt, receives the full pipeline response, and verifies specific behaviors against exact expected outputs. Pass or fail. No partial credit. No subjectivity.

**Why the harness was necessary.** Multi-agent pipelines fail in ways that are invisible to casual observation. A graph that silently exits after the first node and returns empty content looks, from the outside, like a slow response. A cache that stores an error message and serves it as a valid answer looks like a correct response with wrong content. A financial parser that adds income and expense figures together because a keyword bleeds across a dollar-sign boundary produces a confident, formatted, mathematically consistent answer — with entirely wrong numbers. None of these failures announce themselves. All of them require specific test cases with exact expected outputs to detect.

**What the progression documents.** The harness did not begin at 7/7. It began at 0/5 — zero percent pass rate. Every test failed. Each failure produced a diagnostic: the graph was terminating silently after the first node due to an unguarded `None` update from LangGraph's internal routing markers. That produced a specific fix. The cache contamination failure — error messages stored and served as valid responses — produced the two-layer contamination guard. The income keyword bleeding failure — `$1,900` misclassified as income because "make" from the prior sentence bled across the context window — produced the segment-bounded entity extraction algorithm. Each fix was not a guess. It was a response to a measured failure with a verifiable outcome.

The progression: **0/5 (0%) → 5/5 (100%) → 7/7 (100%).** Five to seven when goal-aware allocation tests were added and passed on the first run after implementation — confirming that the goal detection, preset selection, and belief graph persistence all functioned correctly end-to-end.

**What each test category proves independently:**

*Financial parsing (Tests 1–3):* The Math Engine produces deterministic, cent-level accurate output regardless of how expenses are labeled or ordered in natural language. Verified figures: $587.50, $822.50, $1,730.00 — exact, not approximate. Three or more labeled expense types correctly aggregated. Allocation breakdowns verified across seven independent line items in a single test pass.

*Research routing (Test 4):* The intent classifier correctly identifies a research question, routes it to the grounding pipeline, and produces a response that contains no financial allocation table — confirming that the research path and the math path do not cross-contaminate each other.

*Cache behavior (Test 5):* A cold pipeline run completes in 60–120 seconds. The same prompt, submitted immediately after, returns in under 100 milliseconds — a greater than 99.8% reduction in response latency, with identical content. The 0.98 cosine similarity threshold correctly distinguishes near-identical prompts from loosely related ones.

*Goal-aware allocation (Tests 6–7):* A user stating "I'm saving for a house" receives a 65% savings rate ($3,575 on a $5,500 net, verified to the cent) — not the default 50% ($2,750). A user stating "I'm paying off my credit card debt" receives a 60% savings rate ($2,520 on a $4,200 net) — not the default 50% ($2,100). The default allocation is never applied when a goal is detected. The shift is exact, consistent, and architecturally enforced.

**The hardware efficiency result.** All seven tests pass on a consumer gaming PC with 4GB of VRAM, running two coordinated 1.5 billion parameter models — orders of magnitude smaller than frontier systems — with no cloud API and no recurring inference cost. The 87–93% reduction in time-to-first-token across build iterations (from 600–900 seconds in early builds to 60–120 seconds in the final architecture) came entirely from architectural decisions: model specialization, parallel execution, VRAM keep_alive, and semaphore management. The hardware did not change. The structure did.

**What 7/7 means.** The harness does not test whether LatticeD sounds correct. It tests whether LatticeD is correct — to the cent, in every routing decision, in every cache behavior, on every goal detection. A system that passes this suite consistently, on consumer hardware, with 1.5B parameter models, without a cloud API, has demonstrated something that cannot be claimed without evidence. The evidence exists. It is documented, reproducible, and verifiable.

---

### 5D. Known Limitations

A case study that only describes what works is incomplete. The following limitations are explicit and form the prioritized work for the next development cycle.

**Eval harness coverage is narrow by design.** Seven tests cover the financial and research paths thoroughly. They do not yet cover conversation continuity over long sessions, adversarial prompt injection, edge cases in goal detection ("paying off debt" vs "paid off debt"), or behavior under sustained concurrent load. Each of these is a separate test category that must be built out before the framework is production-ready in any new domain.

**Cold-start latency is significant.** A first pipeline pass on consumer hardware takes 60–120 seconds. The cache mitigates this for repeated queries, but the first interaction in any new session is slow. This is the primary user-experience cost of running locally on small models. The roadmap addresses this through model warming on startup and pipeline visualization that gives the user feedback during the wait.

**The framework is single-user as built.** LatticeD currently runs as a personal AI instance — one user, one belief graph, one semantic memory store. Multi-tenancy requires additional work on isolation, authentication, and per-user database scoping. This is a roadmap item, not a current capability.

**Routing depends on regex patterns that can be evaded.** The Intent Classifier's first tier uses pattern matching for known financial, research, and shell command structures. Novel phrasings that fall outside these patterns drop through to the vector encoder and then the LLM router — both of which are more capable but also slower. Routing precision under unusual or adversarial inputs has not been formally measured.

**Hallucination prevention is path-specific.** The Authorized Numbers Block prevents financial figure hallucination on the research path. The Math Engine prevents arithmetic hallucination on the financial path. The fast path — used for general conversation — has no equivalent structural constraint. A user asking the fast path for factual claims receives a normal language model response with normal language model failure modes. Path-aware protection is not the same as system-wide protection.

**Small models have a real reasoning ceiling.** 1.5 billion parameter models, even when coordinated, cannot match the raw reasoning depth of frontier-scale models on novel multi-step problems outside the system's specialized domains. LatticeD compensates through structure on tasks within its design scope. It does not claim to compete with frontier models on open-ended reasoning challenges.

These limitations are not failures. They are the boundary of what has been built so far, which makes them the agenda for what gets built next.

---

---

## 6. What LatticeD Becomes

### 6A. The Vision: Private, Personal AI That Runs Where You Are

**The core differentiator is privacy.** LatticeD runs entirely on local hardware. Nothing leaves the device. No conversations are sent to a third-party API. No data is logged on a server you do not control. No prompts are used to train someone else's model. When working with proprietary information — financial records, healthcare details, legal documents, business strategy — privacy is not a feature preference. It is a baseline requirement that hosted services cannot structurally provide.

This is also the basis on which LatticeD genuinely differs from current frontier products. ChatGPT, Gemini, and Claude have added memory features, tool use, web search, and document upload since their initial releases — narrowing the feature-level gap considerably. What they cannot offer is local execution. A query sent to a hosted AI is processed on infrastructure the user does not own, logged in systems the user cannot audit, and governed by terms the user did not write. For many use cases this is acceptable. For others — proprietary research, regulated industries, personal medical or financial data — it is disqualifying.

LatticeD is structurally different at the deployment layer. The framework was deliberately designed to run within the 4GB VRAM envelope of consumer hardware specifically because that envelope is portable. The 4GB ceiling is well within the inference budget of current high-end smartphones — mobile deployment is a stated roadmap target, pending the engineering work to package the framework for a mobile runtime. The user owns the model, the memory, the belief graph, the cache, and the artifact archive. Nothing is rented. Nothing is monitored. Nothing is uploaded.

On top of the privacy foundation, LatticeD personalizes structurally rather than at the prompt layer. The belief graph accumulates a model of *this* user — confirmed facts, stated goals, acknowledged preferences — scored for confidence, decayed over time, and corrected by evidence. The semantic memory recalls *this* user's past conversations by meaning, not recency. The allocation presets shift to *this* user's goals. Run LatticeD for six months and the system that exists is not generic LatticeD — it is your LatticeD, distinct from anyone else's. The personalization is meaningful precisely because the data underpinning it never leaves the user's possession.

The most ambitious version of LatticeD is a **personalized AI substrate** — a framework anyone can run locally, that becomes more theirs the longer they use it, and that can be specialized into any domain by adding agent definitions and document context without retraining the underlying models.

In practical terms: a user downloads LatticeD. They use it for personal finance for three months. The belief graph learns their income, expenses, goals, risk tolerance, and behavioral patterns. They then add three new agents — a medical advisor, a legal advisor, a career coach — by writing agent specifications, which are structured JSON configurations and a system prompt. They drop relevant documents into the docs folder. The same system now coaches them across finance, health, law, and career — using the same memory, the same belief graph, the same self-correction loop, the same auditable pipeline. It is not five separate products. It is one substrate, specialized by the user.

At organizational scale, this becomes infrastructure. A financial advisory firm deploys LatticeD instances per advisor — each instance privately learning that advisor's client portfolio, compliance requirements, and workflow patterns. A healthcare clinic deploys instances per provider — each one learning that provider's patient population, treatment protocols, and documentation standards. The instances do not share user data — privacy is preserved structurally, not by policy — but they share the underlying framework, agent definitions, and architectural improvements. The organization owns the framework. The professionals own their instances.

The ambitious vision is **personal AI infrastructure**, sold the way personal computers were sold in 1985. Not a service you log into. A system you own. The product is not a chatbot. It is a substrate that learns who you are and adapts to what you need — across every domain you specialize it for.

---

### 6B. Near-Term Roadmap

The vision is ambitious. The path to it is concrete. The following seven milestones are achievable over the next 3–6 months, each one strengthening the framework as a product and the case for the architecture as a category.

**1. Public GitHub Repository.** Clean codebase, complete README, eval harness included, permissive open-source license (MIT or Apache 2.0). This is the artifact that makes the case study verifiable — pointing to working code that any developer can clone, run, and inspect. It is also the gateway for collaborators, contributors, and credibility. *Estimated effort: two weeks.*

**2. Polished Web Interface.** The current `ui.html` is functional but minimal. A modern React interface with conversation history, belief graph visualization, goal tracking, and live pipeline visualization transforms the system from a developer artifact into a product anyone can evaluate in five minutes. The pipeline visualization in particular — showing the 13 nodes executing in real time, with the parallel branches and the Auditor-Guardian loop visible — is itself a teaching tool for the architecture. *Estimated effort: one month.*

**3. PDF and Excel Ingestion.** The document ingestion node currently reads markdown files only. Extending it to handle PDFs (bank statements, tax documents, investment statements) and Excel files (budget spreadsheets, portfolio exports) means users can drop their actual financial documents into the docs folder and LatticeD reads them natively. This is the difference between a technology demonstration and a tool that produces immediate value on day one. *Estimated effort: one to two weeks.*

**4. Healthcare Domain Pack.** A second set of specialized agents — clinical guideline lookup, drug interaction checking, symptom triage with explicit referral protocols — proves LatticeD is a framework rather than a finance product. The healthcare pack is built by writing new agent specifications and adding domain-specific documents to the workspace. The pipeline, the self-correction loop, the memory layers, and the Authorized Numbers Block all carry forward unchanged. *Estimated effort: two to three weeks. Uniquely positioned given Health Sciences background.*

**5. Healthcare Eval Harness.** A second regression test suite verifying that the healthcare pack cites authoritative sources, refuses to diagnose, escalates high-risk queries to professional referral, and never substitutes training-data knowledge for current clinical guidelines. This proves the framework's generality through a measured demonstration in a domain with even less tolerance for error than financial services. *Estimated effort: one to two weeks alongside the healthcare pack build.*

**6. Demo Video.** A five-minute screen recording walking through real queries, showing the pipeline visualization, demonstrating that the financial figures are exact and the research citations are correct, and explaining the architecture in plain language. This is the asset that hiring managers, investors, and collaborators will actually watch. *Estimated effort: two days once the polished UI is complete.*

**7. Published Written Piece.** A LinkedIn article and Medium post derived from this case study, with a direct title: *"I Built a Self-Correcting AI Framework on a 4GB Gaming PC. Then Nature Published Two Papers Describing the Same Architecture."* This is the asset that builds public profile in AI engineering and attracts the right opportunities, collaborators, and conversations. *Estimated effort: one day once the case study is finalized.*

Completed in sequence over the next two quarters, these milestones convert LatticeD from a proof-of-concept into a product, a portfolio asset, and a category-defining demonstration.

---

### 6C. Where This Goes Professionally

LatticeD is not a side project disconnected from the next career step. It is the foundation.

Compliance-grade AI with auditable outputs, zero hallucination on numerical reasoning, and structural privacy preservation is one of the most pressing unsolved problems in high-stakes AI in 2026. Most firms are buying flawed solutions from vendors because the safer alternative — building internally — requires AI engineering talent the industry cannot acquire at scale. LatticeD demonstrates that the safer alternative is buildable. By one person. On consumer hardware. In four months. With measurable, reproducible results.

Healthcare follows the same logic. A clinical environment has even less tolerance for hallucinated facts, unsourced citations, or systems that cannot explain their reasoning. A Health Sciences background, direct experience translating complex behavioral data into structured documentation, and the framework's structural guarantees on factual accuracy combine into a strong fit for healthcare AI development — particularly where source auditability and refusal-to-diagnose constraints matter more than open-ended generation capability.

The professional direction is clear: applying LatticeD's architectural principles to high-stakes domains where AI accuracy is not optional — financial services, healthcare, and any domain where the consequences of confident wrong answers are too high to accept. The case study you are reading is the public record of the work. The GitHub repository will be the verifiable evidence. The roadmap above is the credible plan.

LatticeD is the foundation. What comes next is making it a viable tool through thorough, sustained testing — extending the eval harness across new domains, stress-testing the architecture under real-world load, and proving that the framework holds its guarantees not just on the seven cases that pass today, but on every case it will be asked to handle tomorrow.

---

### Contact and Next Steps

The case study you have just read describes a working system. The public GitHub repository will make every claim in this document independently verifiable — eval harness runnable in one command, full pipeline reproducible on consumer hardware, and architectural decisions documented in code.

**Repository:** *[GitHub link will be added on public release — see Roadmap item 1, Section 6B]*

**If you are a hiring manager** building AI systems in financial services, healthcare, or other high-stakes domains: I am open to conversations about full-time engineering roles where this architectural thinking is directly applicable.

**If you are a collaborator or technical reviewer:** I welcome critique, suggested test cases for the eval harness, and proposals for additional agent domains. The framework is designed to be extended.

**If you are an investor or organizational decision-maker:** I am open to discussions about deployment partnerships, domain-specific implementations, and the path from open-source framework to specialized production system.

**Contact:** earlpete222@gmail.com | [linkedin.com/in/earl-peterkin-HealthcarelT](https://linkedin.com/in/earl-peterkin-HealthcarelT)

---

---

---

## 7. Technical Appendix

*For engineers, researchers, and technical evaluators. The following documents implementation decisions that reward careful reading but would slow non-technical sections of this case study.*

---

### A. Segment-Bounded Label-Aware Entity Extraction

LatticeD's financial entity parser uses a context-window approach to classify each dollar amount as income or expense. The naive implementation — scanning a fixed 80-character window before each dollar amount for income or expense keywords — produces a systematic failure on natural language patterns like:

> *"I make $5,200 a month and have $1,900 in fixed expenses."*

In this sentence, the keyword "make" precedes `$5,200` correctly. But the 80-character window before `$1,900` reaches back far enough to include "make" — causing the parser to classify `$1,900` as income as well. Result: income = $7,100, expenses = $0. A confident, precise, completely wrong answer.

The fix is segment-bounded context windows. Instead of a fixed character lookback, each dollar amount's pre-context window starts at the end of the **previous dollar amount** — not an arbitrary character count. This ensures each amount is classified only against keywords that appear after the last amount. For `$5,200`: pre-context = "I make " → income keyword match → income. For `$1,900`: pre-context = " a month and have " (starting after `$5,200`) → no income or expense keyword match → unclassified.

When pre-context produces no classification, a secondary post-context check scans up to 60 characters **after** the amount for trailing expense labels — handling patterns like "have $1,900 **in fixed expenses**" where the classification signal follows the number rather than preceding it. The post-context check is only invoked when pre-context is inconclusive, preventing cross-contamination between amounts.

**Measurable outcome:** The `tc_simple_budget` regression test — "I make $5,200 a month and have $1,900 in fixed expenses" — failed at 0% with the fixed-window approach (income=7100, expenses=0) and passes at 100% with segment-bounded windows (income=5200, expenses=1900, net=3300 verified to cent).

---

### B. Regression-Safe Testing with bypass_cache Mode

LatticeD's semantic cache is production-grade: near-identical prompts return cached verified responses at under 100ms with a 0.98 cosine similarity threshold. This creates a testing problem. If a test run populates the cache with a correct response, every subsequent test run for the same prompt hits the cache — returning correct content but never exercising the pipeline. Node visit checks (e.g., "did math_engine run?") fail because the cache path does not invoke any pipeline nodes.

The `bypass_cache` query parameter (`?bypass_cache=1`) resolves this by skipping both the cache read and the cache write for a given request. Tests that need to verify pipeline execution use `bypass_cache=True` in the eval harness. Tests that need to verify cache behavior (the `tc_cache_hit` round-trip test) use the default. The two concerns are cleanly separated.

This design also prevents the cache from being polluted by test data. Without the write bypass, every eval harness run would store its outputs in the production cache — potentially serving test responses to real users. With the write bypass active, tests execute in complete isolation from the production cache.

**Measurable outcome:** The eval harness moved from 0/5 → 2/5 → 5/5 → 7/7 passing tests. The `bypass_cache` mechanism was the critical step that separated pipeline-correctness testing from cache-behavior testing, enabling both to be verified independently without interference.

---

### C. Stack Reference

| Component | Technology | Version / Detail |
|---|---|---|
| API server | FastAPI + Uvicorn | Python 3.12 |
| Agent orchestration | LangGraph StateGraph | AsyncSqliteSaver checkpointing |
| Local inference | Ollama | deepseek-r1:1.5b, qwen2.5-coder:1.5b |
| Vector memory | ChromaDB | Persistent, cosine similarity |
| Embedding model | all-MiniLM-L6-v2 | SentenceTransformers, shared singleton |
| Web grounding | Tavily Search API | Up to 5 sources per query |
| Structured output | Ollama JSON schema | 4 agents with constrained output |
| Persistent storage | SQLite | Belief graph, interaction ledger, hardware log |
| Hardware | Consumer PC | 4GB VRAM, CPU inference fallback |
| Interface | SSE streaming + WebSocket | FastAPI StreamingResponse |

---

### D. Eval Harness Coverage

| Test | Prompt type | Key assertions | Result |
|---|---|---|---|
| `tc_multi_expense` | 3-expense label-aware parsing | Income, 3-way sum, net, savings, groceries | ✅ PASS |
| `tc_simple_budget` | Trailing expense label | Income, expenses, net, savings | ✅ PASS |
| `tc_allocation_spot_check` | 7 independent allocations to cent | $587.50, $822.50, $940, $2,350 | ✅ PASS |
| `tc_research_routing` | Research path, no hallucination | Grounding node ran, no budget table | ✅ PASS |
| `tc_cache_hit` | Cache round-trip | Round 1 correct, Round 2 <100ms | ✅ PASS |
| `tc_goal_house` | Goal-aware allocation (65%) | Savings $3,575 not default $2,750 | ✅ PASS |
| `tc_goal_debt` | Goal-aware allocation (60%) | Savings $2,520 not default $2,100 | ✅ PASS |

All 7 tests pass. All financial figures verified to the cent. All node visits confirmed. Cache hit latency confirmed under 100ms.

---

*Case study in progress — LatticeD, 2026*
