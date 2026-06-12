# LatticeD

**A self-correcting multi-agent AI framework that runs locally on consumer hardware.**

LatticeD coordinates 11 specialized agents across a 13-node pipeline using two
1.5 billion parameter language models — `deepseek-r1:1.5b` and
`qwen2.5-coder:1.5b` — within a 4GB VRAM envelope. The architecture includes
deterministic Python math for financial reasoning, an adversarial
Auditor-Guardian self-correction loop, three persistent memory layers, and
structural hallucination prevention on the research path through live web
grounding with authorized-numbers constraints.

The framework runs entirely on your machine. No cloud API. No recurring
inference cost. No data leaves the device.

---

## Status

- **11 / 11** automated regression tests passing
- All financial calculations verified to the cent
- Cache hits under 100ms; full pipeline runs in 60–120 seconds on consumer hardware
- 11 specialized agents, 13-node pipeline, 4GB VRAM budget

For the complete architectural rationale, build history, and roadmap, see the
[LatticeD Case Study](./docs/case_study.md).

---

## Quick Start

### Prerequisites

- Python 3.12 or later
- [Ollama](https://ollama.com) installed and running locally
- 4GB VRAM (GPU) or sufficient system RAM for CPU inference
- Windows, macOS, or Linux

### Install

```bash
# 1. Clone the repository
git clone https://github.com/earlpete222-sys/LatticeD.git
cd LatticeD

# 2. Install Python dependencies
python -m pip install -r requirements.txt

# 3. Pull the two required models via Ollama
ollama pull deepseek-r1:1.5b
ollama pull qwen2.5-coder:1.5b

# 4. (Optional) Set a Tavily API key for the research path
# Get one free at https://tavily.com
export TAVILY_API_KEY="your_tavily_key_here"          # macOS / Linux
$env:TAVILY_API_KEY = "your_tavily_key_here"          # Windows PowerShell

# 5. Launch the framework
python latticed/latticed.py
```

The HTTP API will be available at `http://127.0.0.1:8000`.
Open `latticed/ui_v2.html` in a browser for the full React interface (or visit `http://127.0.0.1:8000/` once the server is running).

### Windows Quick Launch

Two PowerShell helpers are included for Windows users:

```powershell
# One-shot launch (also stops/restarts Ollama with OLLAMA_NUM_PARALLEL=2)
.\Start-LatticeD.ps1

# Register as an auto-start scheduled task
.\Register-LatticeDTask.ps1
```

---

## Verify the Build

Run the full eval harness against the live system:

```bash
python eval_harness.py
```

Expected output: **11 / 11 passed** with cent-level financial figures verified.
The harness exercises label-aware financial parsing, multi-expense
aggregation, research routing, cache round-trip behavior, goal-aware
allocation shifting, annual-income normalization, and memory-contamination
guards.

For a guided walkthrough of the system (fast path, deep path with visible
Auditor/Guardian review, semantic cache, and live web grounding), run the
scripted demo:

```bash
python demo.py          # paced for live presentation (Enter between acts)
python demo.py --auto   # unattended, for screen recording
```

---

## Architecture at a Glance

```
User Prompt
     │
     ▼
INTENT CLASSIFICATION (3-tier: regex → vector → LLM fallback)
     │
     ├── FAST PATH ──── Fast Mentor ─────────────────────────┐
     │                                                       │
     └── DEEP PATH ─── Parallel Retrieval ──┐                │
                       ├ Memory             │                │
                       ├ Belief Graph       ├ Perception     │
                       ├ Web Grounding      │   Barrier      │
                       └ Document Ingestion ┘                │
                                            │                │
                              Math Engine (deterministic)    │
                                            │                │
                              Quantitative Architect         │
                              (parallel: conservative +      │
                                exploratory branches)        │
                                            │                │
                                    Factual Auditor          │
                                            │                │
                                    System Guardian          │
                                    /            \           │
                              APPROVED         REJECTED      │
                                  │            (loop back)   │
                                  ▼                          │
                              Synthesis ◄──────────────────-─┘
                                  │
                              Loyalty Scorer
                                  │
                              Artifact Writer
                                  │
                                  ▼
                              Final Response
```

The 11 specialized agents:

| # | Agent | Role |
|---|---|---|
| 1 | Intent Router | LLM-fallback classifier for ambiguous prompts |
| 2 | Fast Mentor | Light conversational queries |
| 3 | Life Coach | Personal and emotional queries |
| 4 | Grounding Extractor | Parses live web results into structured facts |
| 5 | Quantitative Architect (conservative) | Financial plans at low temperature |
| 6 | Quantitative Architect (exploratory) | Parallel branch at higher temperature |
| 7 | Research Synthesizer | Answers research questions from authorized facts only |
| 8 | Factual Auditor | Critiques every output |
| 9 | System Guardian | Binary APPROVE / REJECT verdict, forces retries |
| 10 | Executive Arbiter | Final response synthesis |
| 11 | Fact Extractor | Updates the persistent belief graph |

A 12th component — the **Loyalty Scorer** — runs as a deterministic scoring
node rather than a language model agent.

---

## Configuration

Override defaults via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `LATTICED_SECRET` | `local_dev_secret_123` | API key for the HTTP endpoint (**change this for any non-local use**) |
| `TAVILY_API_KEY` | (none) | Enables web grounding on the research path |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama inference endpoint |
| `LATTICED_ROOT` | `latticed/runtime` | Runtime storage root |
| `LATTICED_DOCS_DIR` | `LATTICED_ROOT/docs` | Document workspace |
| `LATTICED_MAX_PROMPT_CHARS` | `4000` | Max prompt length |
| `LATTICED_MAX_DOC_CHARS` | `12000` | Max characters per ingested document |
| `LATTICED_HOST` | `127.0.0.1` | Bind interface (set to `0.0.0.0` for LAN access) |
| `LATTICED_PORT` | `8000` | Bind port |
| `OLLAMA_NUM_PARALLEL` | `2` | Concurrent Ollama inference slots |
| `HF_HUB_OFFLINE` | `1` | Suppresses HuggingFace startup network calls |

---

## License

LatticeD is released under the **Business Source License 1.1**.

- Free for personal use, evaluation, development, and academic research
- Production use by commercial entities requires a separate commercial license
- Offering LatticeD as a hosted service to third parties requires a separate
  commercial license for each implementation
- Automatically converts to **Apache License 2.0** on **May 31, 2030**

See [LICENSE](./LICENSE) for full terms. Contact the Licensor for commercial
licensing inquiries.

---

## Security

See [SECURITY.md](./SECURITY.md) for the vulnerability disclosure policy and
production deployment guidance.

The default `LATTICED_SECRET` is intentionally public and must be changed before
exposing the service beyond `127.0.0.1`.

---

## Documentation

- [Case Study](./docs/case_study.md) — full architectural rationale, build
  history, eval results, and roadmap
- [SECURITY.md](./SECURITY.md) — security policy and deployment hardening
- [LICENSE](./LICENSE) — Business Source License 1.1 with commercial terms

---

## Contact

**Earl D. Peterkin**
Philadelphia, PA
earlpete222@gmail.com
[linkedin.com/in/earl-peterkin-HealthcarelT](https://linkedin.com/in/earl-peterkin-HealthcarelT)

For hiring inquiries, technical collaboration, or commercial licensing, please
reach out via email.
