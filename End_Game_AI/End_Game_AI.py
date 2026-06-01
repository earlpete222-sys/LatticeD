"""
END_GAME_AI - SOVEREIGN COGNITIVE LATTICE (V3.1 CORE REFINEMENT)

Integrated advanced build:
- Active Tool Agency: Architect can request [SHELL: cmd] and get real-time feedback before finalizing.
- Conditional Self-Correction Routing: Guardian forces the Architect to rewrite flawed strategies.
- Context Pruning: Nodes only receive 'Need to Know' context, reducing CPU pressure and token bloat.
- Decoupled Agent Factory Registry Pattern for dynamic model-to-skill matching.
- Hardware-aware local model split with mutual exclusion and keep_alive=0 VRAM eviction.
- Single-user local/LAN auth, WebSocket telemetry, and interaction ledgers.
"""

from __future__ import annotations

import asyncio
import hmac
import importlib.util
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Optional, TypedDict

import uvicorn
from fastapi import Depends, FastAPI, File, Header, HTTPException, Path as ApiPath, Query, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

try:
    from langchain_ollama import OllamaLLM
    OLLAMA_AVAILABLE = True
except ImportError:
    OllamaLLM = None
    OLLAMA_AVAILABLE = False

try:
    import ollama as ollama_client
    OLLAMA_DIRECT_AVAILABLE = True
except ImportError:
    ollama_client = None
    OLLAMA_DIRECT_AVAILABLE = False

try:
    from langgraph.graph import END, START, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    END = START = None
    StateGraph = None
    LANGGRAPH_AVAILABLE = False

try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    CHECKPOINTING_AVAILABLE = True
except ImportError:
    AsyncSqliteSaver = None
    CHECKPOINTING_AVAILABLE = False

CHROMA_AVAILABLE = importlib.util.find_spec("chromadb") is not None
SCRAPE_AVAILABLE = importlib.util.find_spec("requests") is not None and importlib.util.find_spec("bs4") is not None
TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_AVAILABLE = bool(TAVILY_KEY) and importlib.util.find_spec("tavily") is not None

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("EndGameAI")

# ---------------------------------------------------------------------
# Directory and Environment Layout Configuration
# ---------------------------------------------------------------------
ROOT_DIR = Path(os.getenv("EARL_ROOT", str(Path(__file__).resolve().parent / "runtime"))).resolve()
STORAGE_DIR = ROOT_DIR / "storage"
OUTPUT_DIR = ROOT_DIR / "outputs"
DOCS_DIR = Path(os.getenv("EARL_DOCS_DIR", str(ROOT_DIR / "docs"))).resolve()

APP_DB_PATH = STORAGE_DIR / "end_game.db"
CHECKPOINT_DB_PATH = STORAGE_DIR / "end_game_checkpoints.db"
CHROMA_PATH = STORAGE_DIR / "vector_memory"

DEFAULT_SECRET = "local_dev_secret_123"
ACTIVE_SECRET = os.getenv("EARL_SECRET") or os.getenv("JARVIS_SECRET") or DEFAULT_SECRET
logger.info("[auth] ACTIVE_SECRET loaded — first 4 chars: %s*** length: %d", ACTIVE_SECRET[:4], len(ACTIVE_SECRET))
INTERNAL_USER_ID = os.getenv("EARL_USER_ID", "earl_prime")

MAX_PROMPT_CHARS = int(os.getenv("EARL_MAX_PROMPT_CHARS", "4000"))
MAX_DOC_CHARS = int(os.getenv("EARL_MAX_DOC_CHARS", "12000"))
THREAD_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
DECAY_LAMBDA = math.log(2) / 45

# ── Financial Allocation — Single Source of Truth ──────────────────────────────
# Both deterministic_math_engine and synthesis_node read from here.
# Change once; both nodes stay in sync automatically.
ALLOCATION_SPLITS: Dict[str, float] = {
    "savings":       0.500,   # 50% of net surplus
    "groceries":     0.200,   # 20% of net surplus (40% of flex pool)
    "utilities":     0.125,   # 12.5% of net surplus (25% of flex pool)
    "entertainment": 0.175,   # 17.5% of net surplus (35% of flex pool)
}

# ── Goal-Aware Allocation Presets ─────────────────────────────────────────────
# When the user states a financial goal, deterministic_math_engine detects it
# and selects the matching preset.  synthesis_node reads the same preset via the
# active_goal state field so both nodes always stay in sync.
# All split values are fractions of NET surplus and must sum to 1.0.
FINANCIAL_CONFIG: Dict[str, Any] = {
    "default": {
        "splits": ALLOCATION_SPLITS,          # references the module-level dict
        "label":  "General savings plan",
    },
    "house": {
        "splits": {
            "savings":       0.650,           # 65% — aggressive down-payment build
            "groceries":     0.140,           # 14%
            "utilities":     0.090,           # 9%
            "entertainment": 0.120,           # 12%
        },
        "label": "Down payment / home purchase",
    },
    "debt": {
        "splits": {
            "savings":       0.600,           # 60% directed to debt elimination
            "groceries":     0.170,           # 17%
            "utilities":     0.100,           # 10%
            "entertainment": 0.130,           # 13%
        },
        "label": "Debt payoff",
    },
    "emergency": {
        "splits": {
            "savings":       0.550,           # 55% — building 3-6 month cushion
            "groceries":     0.180,           # 18%
            "utilities":     0.110,           # 11%
            "entertainment": 0.160,           # 16%
        },
        "label": "Emergency fund",
    },
    "retirement": {
        "splits": {
            "savings":       0.550,           # 55% — long-term compounding focus
            "groceries":     0.170,           # 17%
            "utilities":     0.110,           # 11%
            "entertainment": 0.170,           # 17%
        },
        "label": "Retirement / long-term investing",
    },
}

# ── Financial Entity Keywords ──────────────────────────────────────────────────
# Used by the label-aware parser in deterministic_math_engine.
# Word-boundary anchored so "income" doesn't match "income tax" fragment mid-word.
_INCOME_KW = re.compile(
    r"\b(?:earn|make|income|salary|take.?home|revenue|bring|wages?|pay(?:check)?|gross|net pay)\b",
    re.IGNORECASE,
)
_EXPENSE_KW = re.compile(
    r"\b(?:rent|mortgage|car|auto|expense|spend|insurance|bill|utilit(?:y|ies)|"
    r"debt|loan|payment|cost|fee|subscription|fixed|owe|due|monthly out)\b",
    re.IGNORECASE,
)

# ── Frequency Detection ────────────────────────────────────────────────────────
# Detects the cadence of a dollar figure so amounts can be normalized to monthly
# before allocation math runs.  Without this, "$56,000 per year" was being treated
# as "$56,000 per month" — a 12x error that cascaded into every downstream number.
_FREQ_ANNUAL = re.compile(
    r"\b(?:per\s+year|/\s*year|/\s*yr|annual(?:ly)?|yearly|p\.?a\.?|a\s+year|each\s+year)\b",
    re.IGNORECASE,
)
_FREQ_BIWEEKLY = re.compile(
    r"\b(?:bi[\s-]?weekly|every\s+two\s+weeks|every\s+other\s+week)\b",
    re.IGNORECASE,
)
_FREQ_WEEKLY = re.compile(
    r"\b(?:per\s+week|/\s*week|/\s*wk|weekly|a\s+week|each\s+week)\b",
    re.IGNORECASE,
)
_FREQ_MONTHLY = re.compile(
    r"\b(?:per\s+month|/\s*month|/\s*mo|monthly|a\s+month|each\s+month)\b",
    re.IGNORECASE,
)

# Normalized monthly multipliers.  Default (no frequency match) = 1.0 = monthly.
_FREQ_MULTIPLIERS: Dict[str, float] = {
    "annual":   1.0 / 12.0,    # $X/year → $X/12 per month
    "biweekly": 26.0 / 12.0,   # ~2.167 — 26 biweekly periods ÷ 12 months
    "weekly":   52.0 / 12.0,   # ~4.333 — 52 weeks ÷ 12 months
    "monthly":  1.0,
}

def _scan_frequency(context: str) -> Optional[str]:
    """
    Return the frequency label explicitly found in the context window, or None.
    Checked in order: biweekly first (so 'bi-weekly' doesn't get caught by /weekly/),
    then annual, weekly, monthly.
    """
    if _FREQ_BIWEEKLY.search(context): return "biweekly"
    if _FREQ_ANNUAL.search(context):   return "annual"
    if _FREQ_WEEKLY.search(context):   return "weekly"
    if _FREQ_MONTHLY.search(context):  return "monthly"
    return None

# ── Goal Detection ─────────────────────────────────────────────────────────────
# Ordered by specificity — first match wins in _detect_goal().
_GOAL_PATTERNS: Dict[str, re.Pattern] = {
    "house": re.compile(
        r"\b(?:buy(?:ing)?\s+(?:a\s+)?(?:house|home)|purchas\w+\s+(?:a\s+)?(?:house|home)|"
        r"down\s+payment|sav(?:e|ing)\s+(?:up\s+)?for\s+(?:a\s+)?(?:house|home)|"
        r"home\s+(?:purchase|ownership|buying|buyer))\b",
        re.IGNORECASE,
    ),
    "debt": re.compile(
        r"\b(?:pay(?:ing)?\s+(?:off|down)\s+(?:my\s+)?debt|debt[\s-](?:free|payoff|elimination|reduction)|"
        r"get(?:ting)?\s+out\s+of\s+debt|eliminat\w+\s+(?:my\s+)?debt|"
        r"credit\s+card\s+(?:debt|payoff)|pay\s+off\s+(?:my\s+)?(?:loans?|cards?))\b",
        re.IGNORECASE,
    ),
    "emergency": re.compile(
        r"\b(?:emergency\s+fund|rainy[\s-]day\s+fund|safety\s+net|"
        r"sav(?:e|ing)\s+(?:up\s+)?for\s+(?:an?\s+)?emergency|"
        r"[36]\s+months?\s+(?:of\s+)?(?:expenses?|savings?))\b",
        re.IGNORECASE,
    ),
    "retirement": re.compile(
        r"\b(?:retir(?:e|ement|ing)|sav(?:e|ing)\s+(?:up\s+)?for\s+retir\w+|"
        r"nest\s+egg|long[\s-]term\s+invest\w+|financial\s+independence)\b",
        re.IGNORECASE,
    ),
}

def _detect_goal(text: str) -> str:
    """
    Scan prompt text for explicit financial goal keywords.
    Returns a FINANCIAL_CONFIG key ("house", "debt", "emergency", "retirement")
    or "default" when no goal is detected.
    Checked in _GOAL_PATTERNS order; first match wins.
    """
    for goal, pattern in _GOAL_PATTERNS.items():
        if pattern.search(text):
            return goal
    return "default"

# ── Semantic Cache ─────────────────────────────────────────────────────────────
# Cosine similarity threshold for a cache hit (0.98 = nearly identical prompts).
SEMANTIC_CACHE_THRESHOLD = 0.98
# TTL for cached responses in seconds.  Task/financial answers are deterministic
# and can be cached long-term.  Research answers depend on live web data and must
# not be served stale — they are excluded from the cache entirely at store time.
CACHE_TTL_TASK_SECONDS    = 60 * 60 * 24 * 30   # 30 days  (deterministic math plans)
CACHE_TTL_DEFAULT_SECONDS = 60 * 60 * 24         # 24 hours (chat / fast / coach)

# ── Vector Intent Classification ───────────────────────────────────────────────
# Minimum cosine similarity for a vector classification to be trusted.
# Below this the system falls back to the LLM router.
VECTOR_INTENT_MIN_CONFIDENCE = 0.30

# Anchor phrases that define each intent category in embedding space.
INTENT_ANCHORS_TEXT: Dict[str, str] = {
    "task":     "financial plan budget savings calculation allocate money expenses income compute optimize",
    "research": "explain what is the difference between how does work compare options information lookup facts",
    "shell":    "run execute command powershell terminal system hostname process service computer",
    "personal": "feeling stressed emotional burnout relationship advice personal growth mental wellness support",
    "chat":     "general conversation casual discussion tell me about opinion thoughts ideas",
}

# Populated at startup by init_intent_encoder()
INTENT_ENCODER: Any = None
INTENT_ANCHOR_EMBEDDINGS: Dict[str, Any] = {}

# ── Shared SentenceTransformer singleton ───────────────────────────────────────
# all-MiniLM-L6-v2 is needed by BOTH the ChromaDB embedding function AND the
# vector intent encoder.  Loading it twice costs ~15s extra startup time and
# doubles VRAM for a 90MB model that never changes.  This singleton ensures the
# model is loaded exactly once; both consumers receive a reference to the same
# in-memory object.
_SHARED_ST_MODEL: Any = None

def _get_shared_st_model() -> Any:
    """
    Load all-MiniLM-L6-v2 exactly once.  Subsequent calls return the cached
    instance immediately (no file I/O, no weight deserialization).
    """
    global _SHARED_ST_MODEL
    if _SHARED_ST_MODEL is None:
        from sentence_transformers import SentenceTransformer
        _SHARED_ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Shared SentenceTransformer (all-MiniLM-L6-v2) loaded — single instance.")
    return _SHARED_ST_MODEL

# Hardware profile settings optimized for low-overhead VRAM boundaries
MODEL_REASONING = "deepseek-r1:1.5b"  # Local reasoning engine with explicit internal thinking
MODEL_SYNTHESIS = "qwen2.5-coder:1.5b" # Fast structural translation, synthesis, and execution engine
OLLAMA_KEEP_ALIVE = "2m"                # Keep model resident in VRAM across the full pipeline; evicts after 2 min idle
OLLAMA_NUM_CTX = 4096                   # ~293MB KV cache per 1.5b model; safe within 4GB VRAM with both models loaded

# ---------------------------------------------------------------------
# State Definitions and Schemas
# ---------------------------------------------------------------------
class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_CHARS)
    thread_id: str = Field("main", pattern=THREAD_ID_PATTERN)
    path: Literal["auto", "fast", "deep"] = "auto"

class WSMessage(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_CHARS)
    thread_id: str = Field("main", pattern=THREAD_ID_PATTERN)
    path: Literal["auto", "fast", "deep"] = "auto"

class SovereignState(TypedDict, total=False):
    user_input: str
    thread_id: str
    requested_path: str
    execution_path: str
    intent_category: str
    route_reason: str
    retrieved_memory: str
    belief_context: str
    grounding_context: str
    ingested_docs: str
    perception_status: str
    # New programmatic financial state slots
    monthly_income: float
    fixed_expenses: float
    net_savings_pool: float
    fast_generation: str
    core_generation: str
    strategy_plan: str
    tool_results: str
    tool_call_count: int
    audit_critique: str
    belief_conflicts: str
    guardian_decision: str
    loop_count: int
    math_blueprint: str
    active_goal: str       # goal key from FINANCIAL_CONFIG ("default", "house", "debt", …)
    final_output: str
    loyalty_scores: Dict[str, float]
    loyalty_verdict: str

def parse_ws_message(raw: str) -> WSMessage:
    if hasattr(WSMessage, "model_validate_json"):
        return WSMessage.model_validate_json(raw)
    return WSMessage.parse_raw(raw)

def json_repair_middleware(raw_output: str, fallback_key: str = "verdict") -> dict:
    cleaned = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL)
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        salvaged = match.group(0)
        open_b, close_b = salvaged.count("{"), salvaged.count("}")
        if open_b > close_b:
            salvaged += "}" * (open_b - close_b)
        try:
            return json.loads(salvaged)
        except json.JSONDecodeError:
            pass
    return {fallback_key: cleaned, "middleware_repaired": True}

# ---------------------------------------------------------------------
# Advanced Agent Factory Registry Layer
# ---------------------------------------------------------------------
@dataclass
class AgentSpec:
    agent_id: str
    display_name: str
    purpose: str
    model_name: str
    temperature: float
    max_tokens: int
    system_prompt: str
    output_schema: Optional[Dict[str, Any]] = None  # JSON Schema for constrained generation

class AgentFactoryRegistry:
    def __init__(self):
        self.registry: Dict[str, AgentSpec] = {
            "intent_router": AgentSpec(
                agent_id="intent_router",
                display_name="Intent Router",
                purpose="Classifies upcoming processing streams into exact target modes.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.0,
                max_tokens=20,
                system_prompt=(
                    "Classify the user input. "
                    "Use PERSONAL for coaching, emotional support, relationships, stress, mental wellness, "
                    "personal growth, and interpersonal topics. Use TASK for planning, calculations, and structured work. "
                    "Use RESEARCH for factual lookups. Use SHELL for system commands. Use CHAT for general conversation."
                ),
                output_schema={
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "enum": ["TASK", "RESEARCH", "SHELL", "PERSONAL", "CHAT"]}
                    },
                    "required": ["intent"]
                }
            ),
            "fast_mentor": AgentSpec(
                agent_id="fast_mentor",
                display_name="Fast Mentor",
                purpose="Handles light interactive chat utilizing interpersonal empathy and lifelong learning.",
                model_name=MODEL_REASONING,
                temperature=0.6,
                max_tokens=400,
                system_prompt=(
                    "You are Earl Prime — a trusted advisor skilled in communication, active listening, "
                    "empathy, problem-solving, critical thinking, decision making, creative problem solving, "
                    "adaptability, teamwork, leadership, time management, emotional intelligence, conflict "
                    "resolution, negotiation, cultural awareness, and lifelong learning. "
                    "Respond directly and warmly. Match your tone to what the user actually needs.\n\n"
                    "IMPORTANT: If asked for specific facts, rates, percentages, legal rules, or regulations "
                    "you are not certain about, say so clearly rather than guessing. "
                    "Never invent statistics or financial rules."
                )
            ),
            "quant_architect": AgentSpec(
                agent_id="quant_architect",
                display_name="Quantitative Architect",
                purpose="Formats pre-computed financial plans and structured analysis into clean, actionable output.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.1,
                max_tokens=500,   # Synthesis model: no think chain — formats the math blueprint directly
                system_prompt=(
                    "You are Earl Prime's Quantitative Architect and financial strategist.\n\n"
                    "The formatted budget table will be generated automatically — do NOT produce numbers, "
                    "dollar amounts, percentages, lists, bullet points, or headings.\n"
                    "Do NOT mention income, expenses, or any specific figures — the tables handle all of that.\n\n"
                    "Your entire response must be ONE short paragraph (2-3 sentences maximum) that:\n"
                    "1. Acknowledges the user's specific situation (family size, stated goals, lifestyle)\n"
                    "2. Names the single highest-priority financial action given their situation\n"
                    "3. Ends with one forward-looking recommendation\n\n"
                    "Example tone: 'With a young family and a solid monthly surplus, your most urgent move is "
                    "building a three-month emergency fund before any college contributions. Once that buffer "
                    "is in place, redirect the savings allocation into a 529 plan for maximum tax-free growth.'\n\n"
                    "Write the paragraph only. Stop immediately after it."
                ),
            ),
            "factual_auditor": AgentSpec(
                agent_id="factual_auditor",
                display_name="Factual Auditor",
                purpose="Audits draft accuracy and outputs a compact structured verdict.",
                model_name=MODEL_REASONING,
                temperature=0.05,
                max_tokens=80,   # Reduced: no reasoning field — all tokens go to the critique
                system_prompt=(
                    "You are the Factual Auditor. Review the draft against the grounding reference.\n"
                    "Set validation_status to PASSED if correct, FAILED if errors exist.\n"
                    "If FAILED, list errors in critique using this exact format: "
                    "[ERR1: description] [ERR2: description]. Max 2 errors. Be specific, not conversational."
                ),
                output_schema={
                    "type": "object",
                    "properties": {
                        "validation_status": {"type": "string", "enum": ["PASSED", "FAILED"]},
                        "critique":          {"type": "string"}
                    },
                    "required": ["validation_status", "critique"]
                }
            ),
            "life_coach": AgentSpec(
                agent_id="life_coach",
                display_name="Life Coach",
                purpose="Provides deep coaching across emotional intelligence, personal development, relationships, stress, and human growth.",
                model_name=MODEL_REASONING,
                temperature=0.55,
                max_tokens=700,
                system_prompt=(
                    "You are Earl Prime — a trusted life advisor with deep expertise in emotional intelligence, "
                    "empathy, active listening, coaching, mentoring, relationship building (personal and romantic), "
                    "conflict resolution, negotiation, stress management, personal development, decision making, "
                    "creative problem solving, adaptability, cultural awareness, interpersonal skills, and lifelong learning.\n\n"
                    "Draw on conversation history to personalize your response. Identify the core emotional or "
                    "personal need behind the request and address it directly. Be a coach and mentor — not a "
                    "generic assistant. Respond with warmth, depth, and genuine care."
                )
            ),
            "fact_extractor": AgentSpec(
                agent_id="fact_extractor",
                display_name="Fact Extractor",
                purpose="Extracts objective, verifiable facts from a response for long-term belief graph storage.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.0,
                max_tokens=150,
                system_prompt=(
                    "Extract 3-5 concise, objective facts explicitly stated in the text. "
                    "Each fact must be a short, self-contained statement."
                ),
                output_schema={
                    "type": "object",
                    "properties": {
                        "facts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 5
                        }
                    },
                    "required": ["facts"]
                }
            ),
            "quant_architect_explore": AgentSpec(
                agent_id="quant_architect_explore",
                display_name="Quantitative Architect (Exploratory)",
                purpose="Exploratory architect variant — runs in parallel with the conservative variant at higher temperature to find alternative framings.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.3,
                max_tokens=500,
                system_prompt=(
                    "You are Earl Prime's Quantitative Architect and financial strategist.\n\n"
                    "The formatted budget table will be generated automatically — do NOT produce numbers, "
                    "dollar amounts, percentages, lists, bullet points, or headings.\n"
                    "Do NOT mention income, expenses, or any specific figures — the tables handle all of that.\n\n"
                    "Your entire response must be ONE short paragraph (2-3 sentences maximum) that:\n"
                    "1. Acknowledges the user's specific situation (family size, stated goals, lifestyle)\n"
                    "2. Names the single highest-priority financial action given their situation\n"
                    "3. Ends with one forward-looking recommendation\n\n"
                    "Example tone: 'With a young family and a solid monthly surplus, your most urgent move is "
                    "building a three-month emergency fund before any college contributions. Once that buffer "
                    "is in place, redirect the savings allocation into a 529 plan for maximum tax-free growth.'\n\n"
                    "Write the paragraph only. Stop immediately after it."
                ),
            ),
            "grounding_extractor": AgentSpec(
                agent_id="grounding_extractor",
                display_name="Grounding Extractor",
                purpose="Extracts a structured outline of facts from web search results before research synthesis.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.0,
                max_tokens=500,
                system_prompt=(
                    "Extract a comprehensive outline of facts from the provided web sources.\n"
                    "Group related facts together — for example: 'Contributions', 'Taxation', "
                    "'Withdrawal Rules', 'Eligibility', 'Limits', 'Key Differences'.\n"
                    "Format each fact as: '[CATEGORY] fact statement'.\n"
                    "Include ALL specific numbers, dollar limits, age thresholds, tax rules, "
                    "percentages, and dates exactly as stated in the sources.\n"
                    "Each fact must be a short, self-contained statement.\n"
                    "Do NOT add interpretation or recommendations — extract only."
                ),
                output_schema={
                    "type": "object",
                    "properties": {
                        "facts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 5,
                            "maxItems": 15
                        }
                    },
                    "required": ["facts"]
                }
            ),
            "research_synthesizer": AgentSpec(
                agent_id="research_synthesizer",
                display_name="Research Synthesizer",
                purpose="Answers factual research questions using only pre-extracted verified facts.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.1,
                max_tokens=550,
                system_prompt=(
                    "You are Earl Prime's Research Synthesizer. Answer using ONLY the verified facts supplied.\n\n"
                    "RULES:\n"
                    "1. Your training knowledge about specific dollar limits, contribution caps, and tax rules "
                    "is OUTDATED and MUST NOT be used. Use ONLY the facts given to you.\n"
                    "2. Copy every dollar amount, percentage, age threshold, and date EXACTLY from the "
                    "AUTHORIZED NUMBERS or VERIFIED FACTS sections. Do NOT alter, round, or substitute any figure.\n"
                    "3. If a question asks for a specific number that does NOT appear in the facts, write: "
                    "'Not found in sources — verify at IRS.gov or the relevant authority.'\n"
                    "4. NEVER invent, estimate, or recall any number from training data.\n"
                    "5. Use bullet points grouped by topic. No closing summary paragraph.\n"
                    "6. Do NOT generate budgets, plans, or allocation tables.\n"
                    "7. Stop immediately after the last bullet.\n\n"
                    "EXAMPLE OF CORRECT BEHAVIOR:\n"
                    "  Facts say: '2024 IRA limit: $7,000'\n"
                    "  Correct output: '• 2024 contribution limit: $7,000'\n\n"
                    "EXAMPLE OF FORBIDDEN BEHAVIOR:\n"
                    "  Facts say: '2024 IRA limit: $7,000'\n"
                    "  WRONG output: '• The limit is $23,500' ← DO NOT DO THIS — $23,500 is not in the facts"
                )
            ),
            "system_guardian": AgentSpec(
                agent_id="system_guardian",
                display_name="System Guardian",
                purpose="Reviews auditor critique and makes a strict APPROVE or REJECT gatekeeping decision.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.0,
                max_tokens=15,
                system_prompt=(
                    "You are the System Guardian. Review the auditor critique. "
                    "APPROVE if the output is acceptable. REJECT if it has severe errors requiring a rewrite."
                ),
                output_schema={
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]}
                    },
                    "required": ["decision"]
                }
            ),
            "executive_arbiter": AgentSpec(
                agent_id="executive_arbiter",
                display_name="Executive Arbiter",
                purpose="Synthesizes the final approved technical plan into a cohesive production response.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.05,
                max_tokens=800,
                system_prompt=(
                    "You are Earl Prime's Executive Arbiter — skilled in communication, leadership, "
                    "adaptability, and coaching. Synthesize the approved strategy into a clear, "
                    "actionable artifact the user can immediately apply. Write with authority and warmth."
                )
            )
        }

    def get_agent(self, agent_id: str) -> AgentSpec:
        if agent_id not in self.registry:
            raise KeyError(f"Requested Agent ID [{agent_id}] not found in dynamic factory mapping.")
        return self.registry[agent_id]

    def manifest(self) -> list[Dict[str, Any]]:
        return [asdict(spec) for spec in self.registry.values()]

# ---------------------------------------------------------------------
# Runtime Persistence and Infrastructure Environment
# ---------------------------------------------------------------------
class EarlRuntime:
    def __init__(self) -> None:
        self.db_lock = threading.Lock()
        self.chroma_collection: Any = None
        self.semantic_cache_collection: Any = None   # dedicated collection for response caching
        self.tavily_client: Any = None
        self._chroma_embed_fn: Any = None            # shared across both chroma collections — loaded once
        # Per-model semaphores: both models live in VRAM simultaneously,
        # so a deepseek-r1 call and a qwen2.5-coder call can run in parallel.
        # synthesis_sem allows 2 concurrent calls — enables speculative branching.
        # Requires OLLAMA_NUM_PARALLEL=2 set in the Ollama server environment.
        self.reasoning_sem: Optional[asyncio.Semaphore] = None   # deepseek-r1
        self.synthesis_sem: Optional[asyncio.Semaphore] = None   # qwen2.5-coder
        self.factory = AgentFactoryRegistry()

    def validate_dependencies(self) -> None:
        missing = []
        if not LANGGRAPH_AVAILABLE: missing.append("langgraph")
        if not CHECKPOINTING_AVAILABLE: missing.append("langgraph-checkpoint-sqlite")
        if not OLLAMA_AVAILABLE: missing.append("langchain-ollama")
        if missing: raise RuntimeError("Missing operational requirements: " + ", ".join(missing))

    def validate_secret(self) -> None:
        if ACTIVE_SECRET == DEFAULT_SECRET:
            logger.warning("Default security key is active. Update EARL_SECRET prior to scaling across networks.")

    def init_storage(self) -> None:
        for folder in (ROOT_DIR, STORAGE_DIR, OUTPUT_DIR, DOCS_DIR):
            folder.mkdir(parents=True, exist_ok=True)

    def open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(APP_DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def init_db(self) -> None:
        with self.db_lock:
            with self.open_db() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS loyalty_weights (user_id TEXT PRIMARY KEY, weights TEXT NOT NULL, updated REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS belief_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT UNIQUE NOT NULL, confidence REAL DEFAULT 0.5, last_seen REAL, source TEXT);
                    CREATE TABLE IF NOT EXISTS interaction_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, thread_id TEXT, user_input TEXT, intent TEXT, path TEXT, approved INTEGER, loop_count INTEGER, latency_ms INTEGER, output_prev TEXT);
                    CREATE TABLE IF NOT EXISTS hardware_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, node TEXT, latency_ms INTEGER);
                    """
                )
                row = conn.execute("SELECT user_id FROM loyalty_weights WHERE user_id=?", (INTERNAL_USER_ID,)).fetchone()
                if not row:
                    defaults = {"family": 0.35, "reliability": 0.25, "learning": 0.20, "safety": 0.15, "speed": 0.05}
                    conn.execute("INSERT INTO loyalty_weights VALUES (?,?,?)", (INTERNAL_USER_ID, json.dumps(defaults), time.time()))
                conn.commit()

    def _get_embed_fn(self) -> Any:
        """
        Lazy-load the ChromaDB SentenceTransformerEmbeddingFunction and cache it
        for reuse across both collections.

        After creation, the underlying SentenceTransformer model (fn._model) is
        stored in the global _SHARED_ST_MODEL singleton.  This means
        init_intent_encoder(), which runs next in the lifespan, calls
        _get_shared_st_model() and receives the already-loaded model object —
        eliminating the second 'Loading weights' that previously appeared at startup.
        """
        if self._chroma_embed_fn is None:
            from chromadb.utils import embedding_functions
            fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            # Populate the global singleton so init_intent_encoder() reuses this
            # model instead of loading a second copy.
            global _SHARED_ST_MODEL
            if _SHARED_ST_MODEL is None and hasattr(fn, "_model"):
                _SHARED_ST_MODEL = fn._model
                logger.info(
                    "Shared SentenceTransformer instance extracted from ChromaDB — "
                    "intent encoder will reuse it."
                )
            self._chroma_embed_fn = fn
            logger.info("ChromaDB embedding function ready (all-MiniLM-L6-v2).")
        return self._chroma_embed_fn

    def init_chroma(self) -> None:
        if not CHROMA_AVAILABLE: return
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self.chroma_collection = client.get_or_create_collection(
                name="end_game_lattice_cosine",
                embedding_function=self._get_embed_fn(),
                metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            logger.exception("ChromaDB initialization variant failed.")

    def init_tavily(self) -> None:
        if TAVILY_AVAILABLE:
            from tavily import TavilyClient
            self.tavily_client = TavilyClient(api_key=TAVILY_KEY)

    def init_semantic_cache(self) -> None:
        """Initialize a dedicated ChromaDB collection for semantic response caching."""
        if not CHROMA_AVAILABLE:
            logger.warning("ChromaDB unavailable — semantic cache disabled.")
            return
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self.semantic_cache_collection = client.get_or_create_collection(
                name="semantic_response_cache",
                embedding_function=self._get_embed_fn(),   # reuses the already-loaded model
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(
                "Semantic cache online — %d cached responses stored.",
                self.semantic_cache_collection.count()
            )
        except Exception:
            logger.exception("Semantic cache init failed — caching disabled.")

    async def check_semantic_cache(self, prompt: str) -> Optional[str]:
        """
        Query the semantic cache for a near-identical prior prompt.
        Returns cached response string if similarity >= SEMANTIC_CACHE_THRESHOLD, else None.
        """
        if self.semantic_cache_collection is None:
            return None
        try:
            def _query():
                return self.semantic_cache_collection.query(
                    query_texts=[prompt],
                    n_results=1,
                    include=["metadatas", "distances"]
                )
            results = await asyncio.to_thread(_query)
            if not results.get("distances") or not results["distances"][0]:
                return None
            distance   = results["distances"][0][0]
            similarity = 1.0 - distance          # cosine distance → similarity
            if similarity >= SEMANTIC_CACHE_THRESHOLD:
                meta   = results["metadatas"][0][0]
                cached = meta.get("response", "")
                if not cached:
                    return None
                # Contamination guard — entries written during a graph crash start with
                # "[GRAPH_ERROR]".  Reject them so errors are never served as answers.
                if cached.startswith("[GRAPH_ERROR]"):
                    logger.warning(
                        "[semantic_cache] Purging contaminated cache entry (graph error was stored). "
                        "similarity=%.4f", similarity
                    )
                    return None
                # TTL check — evict stale entries rather than serving outdated answers.
                # stored_at defaults to 0 (Unix epoch) for legacy entries that predate the
                # cached_at field.  time.time() - 0 ≈ 1.75 billion seconds, which is always
                # greater than any TTL, so legacy entries are evicted on first access.
                stored_at = float(meta.get("cached_at", 0))
                ttl       = float(meta.get("ttl_seconds", CACHE_TTL_DEFAULT_SECONDS))
                age       = time.time() - stored_at
                if age > ttl:
                    logger.info(
                        "[semantic_cache] STALE — age=%.0fs ttl=%.0fs similarity=%.4f — bypassing.",
                        age, ttl, similarity
                    )
                    return None
                logger.info(
                    "[semantic_cache] HIT — similarity=%.4f age=%.0fs — returning cached response.",
                    similarity, age
                )
                return cached
        except Exception:
            logger.warning("[semantic_cache] Query error — falling through to full pipeline.", exc_info=True)
        return None

    def store_semantic_cache(self, prompt: str, response: str, intent: str = "") -> None:
        """
        Persist a verified (prompt, response) pair in the semantic cache.

        Research/web-grounded responses are NEVER cached — they depend on live
        Tavily data and would serve stale answers if cached.
        Task (financial math) responses get a 30-day TTL (deterministic output).
        All others get the default 24-hour TTL.
        """
        if self.semantic_cache_collection is None or not response.strip():
            return
        # Research answers are grounded in live web data — never cache them
        if intent == "research":
            logger.info("[semantic_cache] Skipping cache for research intent (live web data).")
            return
        ttl = CACHE_TTL_TASK_SECONDS if intent == "task" else CACHE_TTL_DEFAULT_SECONDS
        try:
            cache_id = f"cache_{uuid.uuid4().hex[:12]}"
            self.semantic_cache_collection.upsert(
                documents=[prompt],
                ids=[cache_id],
                metadatas=[{
                    "response":    response[:8000],
                    "intent":      intent,
                    "cached_at":   time.time(),
                    "ttl_seconds": ttl,
                }]
            )
            logger.info(
                "[semantic_cache] Stored — intent=%s ttl=%dd prompt_len=%d.",
                intent or "unknown", int(ttl / 86400), len(prompt)
            )
        except Exception:
            logger.warning("[semantic_cache] Store failed.", exc_info=True)

    async def execute_registry_inference(self, agent_id: str, context_package: str) -> str:
        """
        Routes inference to the correct per-model semaphore so that one deepseek-r1
        call and one qwen2.5-coder call can run simultaneously on the GPU.
        synthesis_sem allows 2 concurrent slots for parallel speculative branching.
        """
        if self.reasoning_sem is None:
            self.reasoning_sem = asyncio.Semaphore(1)   # one deepseek-r1 at a time
        if self.synthesis_sem is None:
            self.synthesis_sem = asyncio.Semaphore(2)   # two qwen2.5-coder in parallel

        spec = self.factory.get_agent(agent_id)
        prompt_payload = f"<system>{spec.system_prompt}</system>\n\n[Context Blueprint]:\n{context_package}"

        options = {
            "temperature": spec.temperature,
            "num_predict": spec.max_tokens,
            "num_ctx": OLLAMA_NUM_CTX,
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        llm = OllamaLLM(model=spec.model_name, options=options)

        # Route to the semaphore that matches this agent's model
        sem = self.reasoning_sem if spec.model_name == MODEL_REASONING else self.synthesis_sem

        async with sem:
            try:
                if spec.output_schema and OLLAMA_DIRECT_AVAILABLE:
                    # Schema-constrained path: direct ollama client, output guaranteed valid JSON
                    def _schema_invoke():
                        resp = ollama_client.generate(
                            model=spec.model_name,
                            prompt=prompt_payload,
                            format=spec.output_schema,
                            options={
                                "temperature": spec.temperature,
                                "num_predict": spec.max_tokens,
                                "num_ctx": OLLAMA_NUM_CTX,
                                "keep_alive": OLLAMA_KEEP_ALIVE,
                            }
                        )
                        return resp["response"]
                    raw_response = await asyncio.wait_for(
                        asyncio.to_thread(_schema_invoke),
                        timeout=240.0
                    )
                else:
                    # Free-form path: langchain wrapper for expressive text agents
                    raw_response = await asyncio.wait_for(
                        asyncio.to_thread(llm.invoke, prompt_payload),
                        timeout=240.0
                    )
                return raw_response.strip()
            except asyncio.TimeoutError:
                logger.error("[%s] Inference timed out after 240s — releasing semaphore.", agent_id)
                raise RuntimeError(f"Agent '{agent_id}' timed out.")

    def get_loyalty_weights(self) -> Dict[str, float]:
        fallback = {"family": 0.35, "reliability": 0.25, "learning": 0.20, "safety": 0.15, "speed": 0.05}
        try:
            with self.open_db() as conn:
                row = conn.execute("SELECT weights FROM loyalty_weights WHERE user_id=?", (INTERNAL_USER_ID,)).fetchone()
            return json.loads(row[0]) if row else fallback
        except Exception:
            logger.warning("[get_loyalty_weights] DB read failed — using defaults.", exc_info=True)
            return fallback

    def get_belief_context_sync(self, query: str) -> str:
        """
        Read the belief graph and apply temporal decay at read time.
        Confidence decays exponentially with age (same DECAY_LAMBDA as semantic memory).
        Facts whose effective confidence drops below 0.20 are excluded — they've aged out.
        """
        del query
        try:
            now = time.time()
            with self.open_db() as conn:
                rows = conn.execute(
                    "SELECT fact, confidence, last_seen FROM belief_graph "
                    "WHERE confidence > 0.20 ORDER BY last_seen DESC LIMIT 20"
                ).fetchall()
            if not rows:
                return ""
            # Apply decay: effective_confidence = raw * exp(-lambda * age_days)
            decayed = []
            for fact, raw_conf, last_seen in rows:
                age_days = (now - float(last_seen)) / 86400.0
                eff_conf = float(raw_conf) * math.exp(-DECAY_LAMBDA * age_days)
                if eff_conf >= 0.20:
                    decayed.append((eff_conf, fact))
            decayed.sort(key=lambda x: x[0], reverse=True)
            if not decayed:
                return ""
            return "BELIEF GRAPH:\n" + "\n".join(
                f"  [{conf:.2f}] {fact}" for conf, fact in decayed[:10]
            )
        except Exception:
            logger.warning("[get_belief_context] DB read failed.", exc_info=True)
            return ""

    def update_belief_graph_sync(self, facts: Iterable[str], confirmed: bool, source: str) -> None:
        clean_facts = [fact.strip()[:240] for fact in facts if fact and len(fact.strip()) > 20]
        if not clean_facts: return
        delta = 0.06 if confirmed else -0.10
        with self.db_lock:
            try:
                with self.open_db() as conn:
                    for fact in clean_facts[:8]:
                        row = conn.execute("SELECT id, confidence FROM belief_graph WHERE fact=?", (fact,)).fetchone()
                        if row:
                            confidence = max(0.0, min(1.0, float(row[1]) + delta))
                            conn.execute("UPDATE belief_graph SET confidence=?, last_seen=?, source=? WHERE id=?", (confidence, time.time(), source, row[0]))
                        else:
                            conn.execute("INSERT INTO belief_graph (fact, confidence, last_seen, source) VALUES (?,?,?,?)", (fact, 0.58 if confirmed else 0.35, time.time(), source))
                    conn.commit()
            except Exception:
                logger.warning("[update_belief_graph] DB write failed.", exc_info=True)

    async def semantic_recall(self, query: str, thread_id: str, limit: int = 4) -> str:
        if self.chroma_collection is None: return ""
        def _query():
            raw = self.chroma_collection.query(
                query_texts=[query], n_results=limit * 2,
                where={"$and": [{"user_id": INTERNAL_USER_ID}, {"thread_id": thread_id}]},
                include=["documents", "metadatas", "distances"]
            )
            docs, metadatas, distances = raw.get("documents", [[]])[0], raw.get("metadatas", [[]])[0], raw.get("distances", [[]])[0]
            if not docs: return ""
            scored = []
            now = time.time()
            for doc, meta, dist in zip(docs, metadatas, distances):
                score = (1.0 - float(dist)) * math.exp(-DECAY_LAMBDA * ((now - float(meta.get("created_at_epoch", now))) / 86400))
                scored.append((score, doc))
            scored.sort(key=lambda item: item[0], reverse=True)
            return "SEMANTIC MEMORY:\n" + "\n---\n".join(d for _, d in scored[:limit])
        return await asyncio.to_thread(_query)

    async def semantic_write(self, user_input: str, output: str, thread_id: str) -> None:
        if self.chroma_collection is None: return
        def _write():
            self.chroma_collection.add(
                documents=[f"User: {user_input[:400]} | Earl Prime: {output[:800]}"],
                metadatas=[{"user_id": INTERNAL_USER_ID, "thread_id": thread_id, "created_at_epoch": time.time(), "timestamp": datetime.now(timezone.utc).isoformat()}],
                ids=[str(uuid.uuid4())]
            )
        await asyncio.to_thread(_write)

    def log_interaction(self, state: SovereignState, latency_ms: int) -> None:
        with self.db_lock:
            try:
                with self.open_db() as conn:
                    conn.execute(
                        "INSERT INTO interaction_ledger (timestamp,thread_id,user_input,intent,path,approved,loop_count,latency_ms,output_prev) VALUES (?,?,?,?,?,?,?,?,?)",
                        (time.time(), state.get("thread_id", "main"), state.get("user_input", "")[:300], state.get("intent_category", ""), state.get("execution_path", ""), 1, int(state.get("loop_count", 0)), latency_ms, state.get("final_output", "")[:400])
                    )
                    conn.commit()
            except Exception:
                logger.warning("[log_interaction] Failed to write interaction ledger.", exc_info=True)

    def log_hardware(self, node: str, latency_ms: int) -> None:
        with self.db_lock:
            try:
                with self.open_db() as conn:
                    conn.execute("INSERT INTO hardware_log (timestamp,node,latency_ms) VALUES (?,?,?)", (time.time(), node, latency_ms))
                    conn.commit()
            except Exception:
                logger.warning("[log_hardware] Failed to write hardware log.", exc_info=True)

runtime = EarlRuntime()

class PerfTimer:
    def __init__(self, node: str):
        self.node = node
        self.started = time.time()
    def stop(self) -> int:
        elapsed = int((time.time() - self.started) * 1000)
        runtime.log_hardware(self.node, elapsed)
        return elapsed

# ---------------------------------------------------------------------
# Deterministic Loyalty Scorer Layers
# ---------------------------------------------------------------------
LOYALTY_KEYWORDS = {
    "family": ["family", "child", "children", "wife", "husband", "home", "personal", "balance"],
    "reliability": ["verify", "accurate", "confirm", "source", "check", "fact", "evidence", "reliable"],
    "learning": ["learn", "study", "course", "research", "analyze", "understand", "education"],
    "safety": ["safe", "secure", "privacy", "protect", "careful", "caution", "risk", "backup"],
    "speed": ["quick", "fast", "brief", "summary", "asap", "now", "urgent", "short"]
}

def score_loyalty(text: str) -> Dict[str, float]:
    text_lower = text.lower()
    weights = runtime.get_loyalty_weights()
    scores: Dict[str, float] = {}
    for key, words in LOYALTY_KEYWORDS.items():
        hits = sum(1 for w in words if w in text_lower)
        normalized = min(hits / max(len(words) * 0.3, 1), 1.0)
        scores[key] = round(normalized * float(weights.get(key, 0.1)), 4)
    return scores

def loyalty_verdict(scores: Dict[str, float]) -> str:
    if not scores: return "Score: 0.0 | Dominant: NEUTRAL | NEUTRAL"
    total = sum(scores.values())
    dominant = max(scores, key=scores.get)
    return f"Score: {round(total, 3)} | Dominant: {dominant.upper()} | {'ALIGNED' if total > 0.2 else 'NEUTRAL'}"

# ---------------------------------------------------------------------
# Native Shell Execution Agency (Active Tools)
# ---------------------------------------------------------------------
class NativeAgency:
    COMMAND_WHITELIST = {"get-process", "get-service", "get-date", "hostname", "dir", "echo", "ping"}
    FORBIDDEN_TOKENS = (";", "|", "&", ">", "<", "`", "$(", "\n", "\r")

    @classmethod
    async def run_powershell(cls, command: str) -> str:
        sanitized = command.strip()
        base_cmd = sanitized.split()[0].lower() if sanitized else ""
        if base_cmd not in cls.COMMAND_WHITELIST:
            return f"SECURITY_VIOLATION: '{base_cmd}' is not an approved routine."
        if any(token in sanitized for token in cls.FORBIDDEN_TOKENS):
            return "SECURITY_VIOLATION: Shell control characters are blocked."
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", sanitized,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode == 0:
                return stdout.decode("utf-8", errors="ignore").strip() or "Execution success."
            return f"SHELL_ERROR: {stderr.decode('utf-8', errors='ignore').strip()}"
        except asyncio.TimeoutError: return "SHELL_TIMEOUT: Target timed out."
        except Exception as e: return f"SYSTEM_ERROR: {e}"

# ---------------------------------------------------------------------
# Vector Intent Encoder — Zero-LLM Intent Classification
# ---------------------------------------------------------------------
def init_intent_encoder() -> None:
    """
    Pre-compute anchor embeddings for each intent category using the shared
    SentenceTransformer singleton.  Because _get_shared_st_model() caches the
    model after the first call, this function pays zero extra weight-loading cost
    when ChromaDB has already loaded the model (or vice-versa).
    Total cost on a warm singleton: ~150ms for anchor encoding; ~5ms per query.
    """
    global INTENT_ENCODER, INTENT_ANCHOR_EMBEDDINGS
    try:
        INTENT_ENCODER = _get_shared_st_model()
        INTENT_ANCHOR_EMBEDDINGS = {
            intent: INTENT_ENCODER.encode(text, convert_to_numpy=True)
            for intent, text in INTENT_ANCHORS_TEXT.items()
        }
        logger.info(
            "Vector intent encoder ready — %d anchors precomputed.",
            len(INTENT_ANCHOR_EMBEDDINGS)
        )
    except ImportError:
        logger.warning(
            "sentence-transformers not installed — vector intent disabled, "
            "falling back to LLM router for ambiguous prompts."
        )
    except Exception:
        logger.exception("Vector intent encoder init failed — LLM router fallback active.")

def vector_classify_intent(text: str) -> Optional[str]:
    """
    Classify user intent via cosine similarity against anchor embeddings.
    Returns the winning intent label if confidence >= VECTOR_INTENT_MIN_CONFIDENCE,
    otherwise returns None so the caller can fall back to the LLM router.
    ~5ms per call (CPU inference on a 384-dim model).
    """
    if INTENT_ENCODER is None or not INTENT_ANCHOR_EMBEDDINGS:
        return None
    try:
        import numpy as np
        embedding = INTENT_ENCODER.encode(text, convert_to_numpy=True)
        norm_e = np.linalg.norm(embedding)
        if norm_e == 0:
            return None
        scores: Dict[str, float] = {
            intent: float(np.dot(embedding, anchor) / (norm_e * np.linalg.norm(anchor)))
            for intent, anchor in INTENT_ANCHOR_EMBEDDINGS.items()
        }
        best_intent = max(scores, key=scores.__getitem__)
        best_score  = scores[best_intent]
        logger.info(
            "[vector_intent] %s → winner=%s (%.3f)  scores=%s",
            text[:60], best_intent, best_score,
            {k: f"{v:.3f}" for k, v in scores.items()}
        )
        return best_intent if best_score >= VECTOR_INTENT_MIN_CONFIDENCE else None
    except Exception:
        logger.warning("[vector_intent] Classification failed.", exc_info=True)
        return None

# ---------------------------------------------------------------------
# LangGraph Core Execution Node Algorithms (V3.1 Self-Correcting)
# ---------------------------------------------------------------------
async def intent_classifier_node(state: SovereignState) -> dict:
    timer = PerfTimer("intent_classifier")
    text = state["user_input"]
    requested_path = state.get("requested_path", "auto")

    shell_pattern = r"\b(powershell|terminal|shell|commands?|execute|executing|run|get-process|get-service|get-date|hostname)\b"
    # Financial planning pattern: dollar amounts + planning/calculation vocabulary.
    # Must take priority over the LLM router to prevent family/personal context
    # (e.g. "3 kids") from mis-routing a budget prompt to the life coach.
    financial_pattern = r"\b(plan|budget|sav(e|ings)|expenses?|income|invest|allocat|spend|afford|debt|mortgage|loan|calculat)\b"
    # Research pattern: factual financial/investment topics where the model must not
    # hallucinate rules, rates, or regulations. Routes to deep path + grounding.
    research_pattern = (
        r"\b(ira|roth|401k|403b|retirement|pension|annuity|"
        r"stock|bond|etf|mutual.?fund|dividend|capital.?gain|"
        r"tax.?bracket|inflation|portfolio|asset.?allocation|"
        r"interest.?rate|apr|apy|credit.?score|insurance|"
        r"social.?security|medicare|medicaid|deductible|"
        r"difference[s]? between|how does|what is a|what are the)\b"
    )

    if re.search(r"https?://[^\s]+", text):
        intent = "web"
    elif re.search(shell_pattern, text, re.IGNORECASE):
        intent = "shell"
    elif re.search(r"\$[\d,]+", text) and re.search(financial_pattern, text, re.IGNORECASE):
        # Dollar amounts + financial vocabulary → always TASK regardless of other context
        intent = "task"
    elif re.search(research_pattern, text, re.IGNORECASE):
        # Factual financial/investment terms → RESEARCH (deep path + grounding)
        # Prevents fast_mentor from hallucinating specific rates, rules, or regulations
        intent = "research"
    else:
        # ── Layer 1: Vector classification (~5ms, no GPU) ─────────────────────
        # Run in thread since SentenceTransformer.encode is CPU-bound.
        vector_intent = await asyncio.to_thread(vector_classify_intent, text)
        if vector_intent:
            intent = vector_intent
            logger.info("[intent_classifier] Vector route → %s", intent)
        else:
            # ── Layer 2: LLM router fallback (schema-constrained enum) ────────
            # Only fires when vector confidence is below VECTOR_INTENT_MIN_CONFIDENCE.
            raw = await runtime.execute_registry_inference("intent_router", text)
            try:
                parsed_intent = json.loads(raw).get("intent", "CHAT").upper()
            except (json.JSONDecodeError, AttributeError):
                parsed_intent = raw.upper()
            if "RESEARCH" in parsed_intent:
                intent = "research"
            elif "TASK" in parsed_intent:
                intent = "task"
            elif "SHELL" in parsed_intent:
                intent = "shell"
            elif "PERSONAL" in parsed_intent:
                intent = "personal"
            else:
                intent = "chat"

    if requested_path in ("fast", "deep"):
        execution_path = requested_path
    elif intent in ("research", "web", "shell", "task"):
        execution_path = "deep"
    elif intent == "personal":
        execution_path = "coach"
    else:
        execution_path = "fast"

    timer.stop()
    return {
        "intent_category": intent, 
        "execution_path": execution_path, 
        "route_reason": "Hardcoded Override / Router Matrix", 
        "loop_count": 0, 
        "tool_call_count": 0
    }

def fast_fanout_node(state: SovereignState) -> dict: del state; return {}
def deep_fanout_node(state: SovereignState) -> dict: del state; return {}

async def memory_retrieval_node(state: SovereignState) -> dict:
    timer = PerfTimer("memory_retrieval")
    mem = await runtime.semantic_recall(state["user_input"], state.get("thread_id", "main"))
    timer.stop()
    return {"retrieved_memory": mem}

async def belief_retrieval_node(state: SovereignState) -> dict:
    timer = PerfTimer("belief_retrieval")
    ctx = await asyncio.to_thread(runtime.get_belief_context_sync, state["user_input"])
    timer.stop()
    return {"belief_context": ctx}

async def grounding_node(state: SovereignState) -> dict:
    timer = PerfTimer("grounding")
    query = state["user_input"]
    parts = [f"CURRENT TIME: {datetime.now(timezone.utc).isoformat()}"]

    if runtime.tavily_client is not None and state.get("intent_category", "") in ("web", "research", "task"):
        try:
            res = await asyncio.to_thread(runtime.tavily_client.search, query, max_results=5)
            results = res.get("results", [])
            if results:
                # Format each source as a numbered entry with URL so the model can
                # attribute claims to specific sources and the LLM treats them as
                # authoritative rather than as background context.
                formatted_sources = []
                for i, item in enumerate(results, 1):
                    url     = item.get("url", "unknown source")
                    content = (item.get("content", "") or "").strip()
                    if content:
                        formatted_sources.append(
                            f"[SOURCE {i}] {url}\n{content}"
                        )
                if formatted_sources:
                    parts.append(
                        "VERIFIED WEB SOURCES:\n" +
                        "\n\n".join(formatted_sources)
                    )
                    logger.info("[grounding] Tavily returned %d sources.", len(formatted_sources))
        except Exception as e:
            parts.append(f"GROUNDING PATH ERROR: {e}")

    timer.stop()
    return {"grounding_context": "\n\n".join(parts)}

async def document_ingestion_node(state: SovereignState) -> dict:
    timer = PerfTimer("document_ingestion")
    def _read():
        docs = [f"--- {p.name} ---\n{p.read_text(encoding='utf-8')[:MAX_DOC_CHARS]}" for p in sorted(DOCS_DIR.glob("*.md"))]
        return "\n\n".join(docs) if docs else "[No local workspace context documents located]"
    ingested = await asyncio.to_thread(_read)
    timer.stop()
    return {"ingested_docs": ingested}

def perception_barrier_node(state: SovereignState) -> dict:
    return {"perception_status": "synchronized"}

async def fast_core_node(state: SovereignState) -> dict:
    timer = PerfTimer("fast_core")
    payload = f"History: {state.get('retrieved_memory')}\nBeliefs: {state.get('belief_context')}\nRequest: {state['user_input']}"
    raw = await runtime.execute_registry_inference("fast_mentor", payload)
    timer.stop()
    return {"fast_generation": clean_model_text(raw), "guardian_decision": "fast"}

async def life_coach_node(state: SovereignState) -> dict:
    timer = PerfTimer("life_coach")
    memory = state.get("retrieved_memory", "")
    memory_section = f"CONVERSATION HISTORY:\n{memory}\n\n" if memory else ""
    belief = state.get("belief_context", "")
    belief_section = f"WHAT I KNOW ABOUT YOU:\n{belief}\n\n" if belief else ""
    payload = (
        f"{memory_section}"
        f"{belief_section}"
        f"REQUEST: {state['user_input']}"
    )
    raw = await runtime.execute_registry_inference("life_coach", payload)
    timer.stop()
    return {"fast_generation": clean_model_text(raw), "guardian_decision": "coach"}

def _extract_financial_entities(text: str):
    """
    Label-aware dollar amount extractor.

    Strategy:
      1. Find every $amount in the text.
      2. For each, scan the 80 characters immediately before it for income/expense keywords.
      3. Accumulate: income sums matched income amounts; expenses sums ALL matched expense amounts.
      4. Unclassified amounts (no keyword context) are collected separately.
      5. Fallback: if classification produced nothing, treat first number as income and
         SUM the rest as expenses (positional), logging a warning so it's visible in logs.

    Returns: (income: float, expenses: float, unclassified: list[float], method: str)
    """
    income    = 0.0
    expenses  = 0.0
    unclassified: list[float] = []

    # Pre-collect all match positions so each amount's context window can be bounded
    # by the PREVIOUS dollar amount.  Without this, an income verb ("make", "earn")
    # that appears before the first number bleeds into the pre-context of every
    # subsequent number — incorrectly classifying all amounts as income.
    amount_matches = list(re.finditer(r"\$\s*(\d[\d,]*(?:\.\d+)?)", text, re.IGNORECASE))

    for i, m in enumerate(amount_matches):
        amount = float(m.group(1).replace(",", ""))

        # --- pre-context: from end of previous dollar amount (or 80 chars) ---
        if i > 0:
            prev_end     = amount_matches[i - 1].end()
            window_start = max(prev_end, m.start() - 80)
        else:
            window_start = max(0, m.start() - 80)
        pre_context = text[window_start : m.start()]

        is_income  = bool(_INCOME_KW.search(pre_context))
        is_expense = bool(_EXPENSE_KW.search(pre_context))

        # Always compute a post-context window — used for both label fallback
        # (when pre-context didn't classify) AND for frequency detection.
        post_end = min(len(text), m.end() + 60)
        if i < len(amount_matches) - 1:
            post_end = min(post_end, amount_matches[i + 1].start())
        post_context = text[m.end() : post_end]

        # --- post-context fallback for expense label following the amount ---
        # Handles patterns like "have $1,900 in fixed expenses" where the label
        # follows the amount rather than preceding it.
        if not is_income and not is_expense:
            if _EXPENSE_KW.search(post_context):
                is_expense = True

        # --- frequency normalization: convert annual/weekly/biweekly to monthly ---
        # Frequency markers cluster very tightly to their amount in natural English.
        # The label window (80 chars, segment-bounded) is too wide for frequency —
        # it lets "$60,000 per year ... $1,500" leak "per year" into $1,500's window.
        # Use a TIGHT post-window (30 chars, dominant English form: "$X per year"),
        # and only fall back to a very small pre-window (15 chars) if post is empty.
        FREQ_POST_RADIUS = 30
        FREQ_PRE_RADIUS  = 15

        next_start    = amount_matches[i + 1].start() if i < len(amount_matches) - 1 else len(text)
        freq_post_end = min(len(text), m.end() + FREQ_POST_RADIUS, next_start)
        freq_post_win = text[m.end() : freq_post_end]

        prev_end_safe  = amount_matches[i - 1].end() if i > 0 else 0
        freq_pre_start = max(prev_end_safe, m.start() - FREQ_PRE_RADIUS)
        freq_pre_win   = text[freq_pre_start : m.start()]

        # Post first (most common form), then pre as fallback, default monthly
        frequency  = _scan_frequency(freq_post_win) or _scan_frequency(freq_pre_win) or "monthly"
        multiplier = _FREQ_MULTIPLIERS[frequency]
        normalized = amount * multiplier
        if frequency != "monthly":
            logger.info(
                "[math_engine] Frequency normalized — $%.2f %s → $%.2f/month (×%.3f).",
                amount, frequency, normalized, multiplier,
            )

        if is_income and not is_expense:
            income += normalized
        elif is_expense:
            expenses += normalized
        else:
            unclassified.append(normalized)

    if income > 0 or expenses > 0:
        # Absorb any unclassified amounts: if we have income but no expenses yet,
        # treat the first unclassified as expenses; otherwise treat as extra expenses.
        if expenses == 0.0 and unclassified:
            expenses = unclassified.pop(0)
        elif unclassified:
            expenses += sum(unclassified)
            unclassified = []
        return income, expenses, unclassified, "label_aware"

    # Fallback: no keywords found — try positional on any amounts >= 100
    fallback_nums = [
        float(n.replace(",", ""))
        for n in re.findall(r"\b\d[\d,]*\b", text)
        if float(n.replace(",", "")) >= 100
    ]
    if len(fallback_nums) >= 2:
        logger.warning(
            "[math_engine] No income/expense keywords found — using positional fallback "
            "(first=income, rest summed as expenses). Prompt: %.80s", text
        )
        return fallback_nums[0], sum(fallback_nums[1:]), [], "positional_fallback"

    return 0.0, 0.0, [], "insufficient_data"


async def deterministic_math_engine(state: SovereignState) -> dict:
    """
    Label-aware financial math pre-processor.

    Replaces fragile positional indexing (numbers[0]/numbers[1]) with
    keyword-context classification so multi-expense prompts like
    "I earn $4,500, rent is $1,500, car insurance is $250" correctly
    sum $1,500 + $250 as total expenses instead of dropping $250.

    All allocation percentages are read from ALLOCATION_SPLITS — the single
    source of truth shared with synthesis_node.
    """
    timer = PerfTimer("deterministic_math")
    text = state["user_input"]

    income, expenses, unclassified, method = _extract_financial_entities(text)

    if income == 0.0 and expenses == 0.0:
        # Not a financial calculation request — skip math engine
        timer.stop()
        return {"math_blueprint": ""}

    if income == 0.0:
        # Only expenses detected — not enough to build a plan
        logger.warning("[math_engine] Expenses found (%.2f) but no income — skipping.", expenses)
        timer.stop()
        return {"math_blueprint": ""}

    logger.info(
        "[math_engine] Parsed via %s — income: $%.2f  expenses: $%.2f  unclassified: %s",
        method, income, expenses, [f"${x:,.2f}" for x in unclassified],
    )

    net_pool = income - expenses

    # ── Goal detection → pick the matching allocation preset ─────────────────
    goal   = _detect_goal(text)
    config = FINANCIAL_CONFIG.get(goal, FINANCIAL_CONFIG["default"])
    splits = config["splits"]

    logger.info(
        "[math_engine] Goal detected: '%s' (%s) — splits: savings=%.0f%% "
        "groceries=%.0f%% utilities=%.1f%% entertainment=%.1f%%",
        goal, config["label"],
        splits["savings"] * 100, splits["groceries"] * 100,
        splits["utilities"] * 100, splits["entertainment"] * 100,
    )

    savings       = net_pool * splits["savings"]
    groceries     = net_pool * splits["groceries"]
    utilities     = net_pool * splits["utilities"]
    entertainment = net_pool * splits["entertainment"]

    w_sav = savings       / 4
    w_gro = groceries     / 4
    w_uti = utilities     / 4
    w_ent = entertainment / 4

    # Include goal header so the LLM knows why splits may differ from default
    goal_header = (
        f"FINANCIAL GOAL: {config['label']}\n"
        f"ALLOCATION PRESET: '{goal}' (savings rate {splits['savings']*100:.0f}%)\n\n"
        if goal != "default" else ""
    )

    math_blueprint = (
        f"{goal_header}"
        f"1. TOTAL MONTHLY INCOME: ${income:,.2f}\n"
        f"2. FIXED MONTHLY EXPENSES: ${expenses:,.2f}\n"
        f"3. NET AVAILABLE SURPLUS: ${net_pool:,.2f}\n\n"
        f"MONTHLY ALLOCATION BREAKDOWN (Must match your table exactly):\n"
        f"- Retained Savings Target: ${savings:,.2f} per month\n"
        f"- Groceries Allocation: ${groceries:,.2f} per month\n"
        f"- Utilities/Buffer Allocation: ${utilities:,.2f} per month\n"
        f"- Entertainment Allocation: ${entertainment:,.2f} per month\n\n"
        f"WEEKLY MILESTONE TARGETS:\n"
        f"- Week Savings Goal: Save ${w_sav:,.2f} each week\n"
        f"- Week Groceries Limit: Spend no more than ${w_gro:,.2f} each week\n"
        f"- Week Utilities Limit: Allocate ${w_uti:,.2f} each week\n"
        f"- Week Entertainment Limit: Spend no more than ${w_ent:,.2f} each week\n"
    )

    # ── Persist goal to belief graph (non-default goals only) ────────────────
    if goal != "default":
        goal_fact = f"User financial goal: {config['label']} (allocation preset: {goal})"
        await asyncio.to_thread(
            runtime.update_belief_graph_sync, [goal_fact], True, "math_engine_goal"
        )
        logger.info("[math_engine] Goal '%s' written to belief graph.", goal)

    timer.stop()
    return {
        "monthly_income":   income,
        "fixed_expenses":   expenses,
        "net_savings_pool": net_pool,
        "math_blueprint":   math_blueprint,
        "active_goal":      goal,
    }

async def sovereign_core_node(state: SovereignState) -> dict:
    """
    Architect node. Routes to the correct specialist agent based on query type:
    - math_blueprint present  → quant_architect (parallel speculative branching)
    - math_blueprint absent   → research_synthesizer (factual Q&A, no contamination)
    """
    timer = PerfTimer("sovereign_core")
    loop = int(state.get("loop_count", 0)) + 1
    math_blueprint = state.get("math_blueprint", "")

    critique_injection = ""
    if state.get("audit_critique"):
        critique_injection = f"\n[REWRITE REQUIRED] Fix these errors before responding:\n{state['audit_critique']}\n"

    # ── Research / Non-Financial Path ────────────────────────────────────────
    # When there is no math blueprint, the query is a factual/research question.
    # Use the research_synthesizer with a clean, uncontaminated context.
    # Deliberately exclude retrieved_memory to prevent prior financial session data
    # from polluting the research answer.
    if not math_blueprint:
        ground = (state.get("grounding_context", "") or "")[:3000]
        # NOTE: belief_context is intentionally excluded from the research payload.
        # Belief graph entries may contain outdated figures (old contribution limits,
        # deprecated rules) that would contaminate the live Tavily facts.  Research
        # answers must be sourced exclusively from the current web grounding.

        # ── Stage 1: Extract structured facts from raw web sources ────────────
        # The grounding_extractor is schema-constrained (JSON array of facts).
        # Clean bullet facts prevent the research_synthesizer from drifting into
        # training-data hallucinations when working from raw 3000-char web content.
        facts: list[str] = []
        facts_section = ""
        if ground and "VERIFIED WEB SOURCES" in ground:
            try:
                extraction_payload = (
                    f"Extract all specific facts, numbers, limits, and rules from these sources:\n\n"
                    f"{ground[:2500]}"
                )
                raw_extraction = await runtime.execute_registry_inference(
                    "grounding_extractor", extraction_payload
                )
                parsed_extraction = json.loads(raw_extraction)
                facts = parsed_extraction.get("facts", [])
                if facts:
                    facts_section = (
                        "VERIFIED FACTS (extracted from live web sources):\n" +
                        "\n".join(f"• {f}" for f in facts)
                    )
                    logger.info("[sovereign_core] Extracted %d facts from grounding.", len(facts))
                    for i, f in enumerate(facts[:5], 1):
                        logger.info("[sovereign_core]   fact %d: %s", i, f)
                else:
                    # Extractor returned empty list — fall back to raw grounding rather
                    # than silently hitting the NO WEB SOURCES branch below.
                    logger.warning("[sovereign_core] Extractor returned 0 facts — using raw grounding context.")
                    facts_section = ground
            except Exception:
                logger.warning("[sovereign_core] Fact extraction failed — falling back to raw grounding.")
                facts_section = ground
        else:
            facts_section = ground  # No Tavily sources — use whatever context exists

        # ── Stage 2: Build an AUTHORIZED NUMBERS block ───────────────────────
        # Small models (1.5B) frequently fall back to training-data figures even
        # when told not to.  Pulling every dollar/percent value out of the facts and
        # listing them verbatim at the very top of the prompt gives the model a
        # concrete, easy-to-copy reference that directly competes with training memory.
        number_highlights: list[str] = [
            f for f in facts
            if re.search(r"\$[\d,]+|[\d,]+%|\b\d+,\d{3}\b", f)
        ]
        authorized_block = ""
        if number_highlights:
            authorized_block = (
                "⚠️  AUTHORIZED NUMBERS — copy these EXACTLY, do not change or invent any figure:\n" +
                "\n".join(f"  ✓ {f}" for f in number_highlights) +
                "\n\n"
            )
            logger.info("[sovereign_core] Authorized-numbers block: %d entries.", len(number_highlights))

        # ── Stage 3: Synthesize answer from clean facts ───────────────────────
        if facts_section:
            payload = (
                f"{authorized_block}"
                f"{facts_section}\n\n"
                f"FORBIDDEN: citing any dollar amount, percentage, or limit not listed above.\n\n"
                f"{critique_injection}"
                f"Answer using ONLY the verified facts above:\n{state['user_input']}"
            )
        else:
            payload = (
                f"NO WEB SOURCES AVAILABLE — flag any specific numbers or rules as unverified.\n\n"
                f"{critique_injection}"
                f"Question: {state['user_input']}"
            )

        raw = await runtime.execute_registry_inference("research_synthesizer", payload)
        raw = clean_model_text(raw)
        timer.stop()
        return {"core_generation": raw, "strategy_plan": raw, "loop_count": loop}

    # ── Financial Planning Path ──────────────────────────────────────────────
    # Token budget: OLLAMA_NUM_CTX=4096 tokens ≈ 16 384 chars at ~4 chars/token.
    # Reserve ~2 000 chars for the system prompt + architect max_tokens=500 output.
    # Remaining ~14 000 chars split across all payload sections below.
    # Each section is hard-capped so overflow in one cannot silently crowd out another.
    _BUDGET_MATH    = 1200   # blueprint is ~700 chars; leave headroom
    _BUDGET_MEMORY  =  500
    _BUDGET_BELIEF  =  600
    _BUDGET_GROUND  =  800
    _BUDGET_TOOL    =  600
    _BUDGET_USER    =  500   # user prompt (already validated at API boundary)

    tool_injection = ""
    if state.get("tool_results"):
        tool_raw = str(state["tool_results"])[:_BUDGET_TOOL]
        tool_injection = f"\n⚠️ REAL SYSTEM TOOL OUTPUT:\n{tool_raw}\n"

    math_section = (
        f"### MANDATORY MATHEMATICAL METRICS (DO NOT ALTER THESE FIGURES):\n"
        f"{math_blueprint[:_BUDGET_MATH]}\n"
        f"CRITICAL RULE: Copy the figures above exactly. Do not perform your own division or math operations.\n\n"
    )

    memory = state.get("retrieved_memory", "")
    belief  = (state.get("belief_context",   "") or "")[:_BUDGET_BELIEF]
    ground  = (state.get("grounding_context","") or "")[:_BUDGET_GROUND]
    user_q  = state["user_input"][:_BUDGET_USER]
    memory_section = f"CONVERSATION HISTORY:\n{memory[:_BUDGET_MEMORY]}\n\n" if memory else ""

    payload = (
        f"### CURRENT TARGET OBJECTIVE:\n{user_q}\n\n"
        f"{math_section}"
        f"{memory_section}"
        f"{tool_injection}"
        f"{critique_injection}"
        f"CONTEXT:\n{belief}\n\n"
        f"LIVE GROUNDING DATA:\n{ground}\n"
    )

    total_chars = len(payload)
    if total_chars > 13_000:
        logger.warning(
            "[sovereign_core] Payload %d chars exceeds soft budget of 13 000 — "
            "context may be truncated by Ollama.", total_chars
        )

    # ── Parallel Speculative Branching ──────────────────────────────────────
    # Fire both architect variants simultaneously (quantum superposition analog).
    # quant_architect      → conservative planner (temp=0.1, exploitation)
    # quant_architect_explore → creative planner  (temp=0.3, exploration)
    # Both qwen2.5-coder models; synthesis_sem=Semaphore(2) allows true parallelism.
    # Winner = variant whose output contains more mandatory blueprint figures.
    branch_results = await asyncio.gather(
        runtime.execute_registry_inference("quant_architect", payload),
        runtime.execute_registry_inference("quant_architect_explore", payload),
        return_exceptions=True,
    )

    def _strip_instruction_artifacts(text: str) -> str:
        """Remove prompt instruction lines that the architect copied verbatim into its output."""
        text = re.sub(r"#+\s*CRITICAL RULE[^\n]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"CRITICAL RULE[^\n]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"#+\s*MANDATORY MATHEMATICAL METRICS[^\n]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[Context Blueprint\][^\n]*", "", text, flags=re.IGNORECASE)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    plans: list[str] = [
        _strip_instruction_artifacts(clean_model_text(r))
        for r in branch_results
        if isinstance(r, str) and r.strip()
    ]

    if not plans:
        # Both branches failed — surface the first exception message as fallback
        first_exc = next((r for r in branch_results if isinstance(r, Exception)), None)
        err_msg = str(first_exc) if first_exc else "Both architect branches returned empty."
        logger.error("sovereign_core parallel branches both failed: %s", err_msg)
        timer.stop()
        return {"core_generation": err_msg, "strategy_plan": err_msg, "loop_count": loop}

    if len(plans) == 1:
        raw = plans[0]
        logger.info("sovereign_core: one branch succeeded, using it directly.")
    else:
        # Score each plan by how many mandatory math blueprint figures it contains.
        # A plan that faithfully copies all pre-computed figures wins outright.
        figures = re.findall(r"\$[\d,]+(?:\.\d+)?", state.get("math_blueprint", ""))
        if figures:
            scores = [sum(1 for fig in figures if fig in plan) for plan in plans]
            best_idx = scores.index(max(scores))
            logger.info(
                "sovereign_core speculative branch scores — conservative:%d explore:%d → winner: %s",
                scores[0], scores[1],
                "conservative" if best_idx == 0 else "explore",
            )
        else:
            # No blueprint figures to score on — prefer the longer, more detailed plan
            scores = [len(plan) for plan in plans]
            best_idx = scores.index(max(scores))
            logger.info(
                "sovereign_core: no blueprint figures; selected longer plan (lens %s), winner idx=%d",
                scores, best_idx,
            )
        raw = plans[best_idx]

    timer.stop()
    return {
        "core_generation": raw,
        "strategy_plan": raw,
        "loop_count": loop
    }

async def agency_node(state: SovereignState) -> dict:
    """Active Tool Agency: Extracts [SHELL:] and runs immediately."""
    timer = PerfTimer("agency")
    plan = state.get("strategy_plan", "")
    call_count = int(state.get("tool_call_count", 0)) + 1
    
    shell_match = None
    if "[SHELL:" in plan:
        try:
            cmd = plan.split("[SHELL:")[1].split("]")[0].strip()
            shell_match = cmd
        except IndexError:
            pass

    if not shell_match:
        timer.stop()
        return {"tool_results": "No tool actions requested.", "tool_call_count": call_count}
    
    result = await NativeAgency.run_powershell(shell_match)
    timer.stop()
    # Strip the shell call from the plan so it doesn't loop infinitely
    cleaned_plan = plan.replace(f"[SHELL: {shell_match}]", "[SHELL_EXECUTED]")
    return {"tool_results": f"Executed [{shell_match}]:\n{result}", "strategy_plan": cleaned_plan, "tool_call_count": call_count}

async def auditor_node(state: SovereignState) -> dict:
    """
    Verification gate. Currently a pass-through on all live paths:
      - Financial:  figures are deterministic (Python); no LLM audit needed.
      - Research:   research_synthesizer enforces source-only rules in its prompt.
      - Shell:      reserved for future code-execution validation (roadmap #7).

    The factual_auditor agent and guardian_router remain wired in the graph so
    the loop can be activated without a graph rebuild — just remove the early
    return below and implement the verification logic for the target path.
    """
    timer = PerfTimer("auditor")
    logger.info(
        "[auditor] Pass-through — path=%s math=%s",
        state.get("execution_path", "?"),
        "yes" if state.get("math_blueprint") else "no",
    )
    timer.stop()
    return {"audit_critique": "", "belief_conflicts": ""}

async def guardian_node(state: SovereignState) -> dict:
    """Determines if the Architect needs to self-correct."""
    timer = PerfTimer("guardian")
    critique = state.get("audit_critique", "")
    if not critique:
        timer.stop()
        return {"guardian_decision": "approve"}
    raw = await runtime.execute_registry_inference("system_guardian", f"Critique list:\n{critique}")
    try:
        decision_val = json.loads(raw).get("decision", "APPROVE").upper()
    except (json.JSONDecodeError, AttributeError):
        decision_val = "REJECT" if "REJECT" in raw.upper() else "APPROVE"
    decision = "reject" if decision_val == "REJECT" else "approve"
    timer.stop()
    return {"guardian_decision": decision}

async def synthesis_node(state: SovereignState) -> dict:
    """Executive Arbiter: Synthesizes final response to user."""
    timer = PerfTimer("synthesis")
    # fast and coach paths both produce a complete response — bypass the arbiter
    if state.get("execution_path") in ("fast", "coach"):
        timer.stop()
        return {"final_output": state.get("fast_generation", "")}

    # Financial/math plans: rebuild the number sections directly from pre-computed state
    # floats so LLM table-formatting corruption can never reach the final output.
    # The architect's contextual intro (text before first ### heading) is preserved.
    if state.get("math_blueprint"):
        income   = float(state.get("monthly_income",   0.0))
        expenses = float(state.get("fixed_expenses",   0.0))
        net      = float(state.get("net_savings_pool", 0.0))

        # Splits sourced from the same FINANCIAL_CONFIG preset math_engine chose.
        # active_goal flows through state so both nodes always stay in sync.
        _goal   = state.get("active_goal", "default")
        _splits = FINANCIAL_CONFIG.get(_goal, FINANCIAL_CONFIG["default"])["splits"]
        savings       = net * _splits["savings"]
        groceries     = net * _splits["groceries"]
        utilities     = net * _splits["utilities"]
        entertainment = net * _splits["entertainment"]

        w_sav = savings       / 4
        w_gro = groceries     / 4
        w_uti = utilities     / 4
        w_ent = entertainment / 4

        # Pull only the architect's first paragraph as the contextual intro.
        # Stop at the first double-newline, numbered list, bullet list, or ### heading
        # so a verbose architect output doesn't duplicate the Python-formatted sections.
        strategy   = state.get("strategy_plan", "") or ""
        intro_raw  = re.split(r"\n\n|\n\d+\.|\n[-*]|\n###", strategy, maxsplit=1)[0].strip()
        # Hard cap at 500 chars — trim cleanly at word boundary
        if len(intro_raw) > 500:
            intro_raw = intro_raw[:500].rsplit(" ", 1)[0].rstrip(".,;:") + "."
        # Strip trailing list lead-ins left by the split (e.g. "...as follows:" → ".")
        intro_raw = re.sub(r"\s*(as follows|as outlined below|below)[^.]*:?\s*$", ".", intro_raw, flags=re.IGNORECASE)
        intro_raw = re.sub(r":\s*$", ".", intro_raw)
        # Scrub any dollar figures the architect hallucinated (e.g. wrong numbers from
        # retrieved_memory of a prior session). The Python-formatted tables below are
        # the authoritative source of truth — the intro must be purely qualitative.
        # Step 1: remove "of/at/around $X,XXX" — takes the preposition with the amount
        #         so "surplus of $2,770" → "surplus" not "surplus of"
        intro_raw = re.sub(r"\s+(?:of|at|around|approximately|about)\s+\$\s*[\d,]+(?:\.\d+)?", "", intro_raw, flags=re.IGNORECASE)
        # Step 2: remove any remaining bare dollar amounts
        intro_raw = re.sub(r"\$\s*[\d,]+(?:\.\d+)?", "", intro_raw)
        # Step 3: remove standalone number+unit phrases ("1,730 monthly", "$350 per month")
        intro_raw = re.sub(r"\b[\d,]+(?:\.\d+)?\s*(?:dollars?|monthly|a month|per month)\b", "", intro_raw, flags=re.IGNORECASE)
        # Step 4: collapse any double spaces left by the removals
        intro_raw = re.sub(r" {2,}", " ", intro_raw).strip()
        intro_section = f"{intro_raw}\n\n" if intro_raw else ""

        final_output = (
            f"{intro_section}"
            f"### INCOME & EXPENSE SUMMARY\n"
            f"- Monthly Income:      ${income:>10,.2f}\n"
            f"- Fixed Expenses:      ${expenses:>10,.2f}\n"
            f"- Net Available Surplus: ${net:>8,.2f}\n\n"
            f"### ALLOCATION MATRIX\n"
            f"- Retained Savings:  ${savings:>10,.2f}/month  (${w_sav:>8,.2f}/week)\n"
            f"- Groceries:         ${groceries:>10,.2f}/month  (${w_gro:>8,.2f}/week)\n"
            f"- Utilities/Buffer:  ${utilities:>10,.2f}/month  (${w_uti:>8,.2f}/week)\n"
            f"- Entertainment:     ${entertainment:>10,.2f}/month  (${w_ent:>8,.2f}/week)\n\n"
            f"### WEEKLY TARGETS\n"
            f"- Savings Goal:          Save ${w_sav:,.2f} each week\n"
            f"- Groceries Limit:       Spend no more than ${w_gro:,.2f} each week\n"
            f"- Utilities/Buffer:      Allocate ${w_uti:,.2f} each week\n"
            f"- Entertainment Limit:   Spend no more than ${w_ent:,.2f} each week\n"
        )
        timer.stop()
        return {"final_output": final_output}

    # Research/deep path without math blueprint: the research_synthesizer already
    # produced the complete answer. Running it through the executive_arbiter adds
    # latency and risks safety refusals from the synthesis model seeing confusing context.
    if state.get("execution_path") == "deep" and not state.get("math_blueprint"):
        strategy = state.get("strategy_plan", "") or ""
        timer.stop()
        logger.info("[synthesis] Research path — returning research_synthesizer output directly.")
        return {"final_output": strategy}

    memory = state.get("retrieved_memory", "")
    memory_section = f"CONVERSATION HISTORY:\n{memory}\n\n" if memory else ""

    # Cap strategy_plan to prevent context overflow in the arbiter's 4096-token budget
    strategy = (state.get("strategy_plan", "") or "")[:2500]

    payload = (
        f"ORIGINAL REQUEST: {state['user_input']}\n\n"
        f"{memory_section}"
        f"APPROVED TECHNICAL STRATEGY:\n{strategy}"
    )
    try:
        final = await runtime.execute_registry_inference("executive_arbiter", payload)
        timer.stop()
        return {"final_output": final.strip()}
    except Exception:
        logger.exception("synthesis_node arbiter call failed — returning strategy_plan directly.")
        timer.stop()
        return {"final_output": strategy}

def loyalty_scorer_node(state: SovereignState) -> dict:
    text = state.get("user_input", "") + "\n" + state.get("final_output", "")
    scores = score_loyalty(text)
    return {"loyalty_scores": scores, "loyalty_verdict": loyalty_verdict(scores)}

async def artifact_writer_node(state: SovereignState) -> dict:
    timer = PerfTimer("artifact_writer")
    output = state.get("final_output", "")
    thread_id = state.get("thread_id", "main")
    
    def _write():
        (OUTPUT_DIR / "latest_brief.md").write_text(output, encoding="utf-8")
        (OUTPUT_DIR / f"{thread_id}_{int(time.time())}.md").write_text(output, encoding="utf-8")
    try:
        await asyncio.to_thread(_write)
    except Exception:
        logger.warning("[artifact_writer] File write failed.", exc_info=True)

    if output:
        await runtime.semantic_write(state.get("user_input", ""), output, thread_id)
        extraction_context = (
            f"USER REQUEST: {state.get('user_input', '')[:300]}\n\n"
            f"ASSISTANT RESPONSE: {output[:800]}"
        )
        raw_facts = await runtime.execute_registry_inference("fact_extractor", extraction_context)
        try:
            # Schema guarantees {"facts": [...]} — no repair middleware needed
            parsed_facts = json.loads(raw_facts)
            fact_list = parsed_facts.get("facts", []) if isinstance(parsed_facts, dict) else parsed_facts
            facts = [str(f).strip() for f in fact_list if isinstance(f, str) and f.strip()][:5]
        except (json.JSONDecodeError, Exception):
            facts = []
        if facts:
            await asyncio.to_thread(runtime.update_belief_graph_sync, facts, True, "fact_extractor")
    timer.stop()
    return {}

def clean_model_text(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

# ---------------------------------------------------------------------
# Graph Conditional Routing Functions (V3.1 Logic)
# ---------------------------------------------------------------------
def route_start(state: SovereignState) -> str: return "fast" if state.get("execution_path") == "fast" else "deep"
def route_after_barrier(state: SovereignState) -> str:
    path = state.get("execution_path", "")
    if path == "fast":
        return "fast"
    if path == "coach":
        return "coach"
    return "deep"

def core_router(state: SovereignState) -> str:
    """Active Agency Routing: Check if Architect requested a shell tool."""
    plan = state.get("strategy_plan", "")
    call_count = int(state.get("tool_call_count", 0))
    # Prevent infinite loop of shell queries
    if "[SHELL:" in plan and call_count < 2:
        return "agency"
    return "auditor"

def agency_router(state: SovereignState) -> str:
    """Always loop back to core after grabbing tool data."""
    return "sovereign_core"

def guardian_router(state: SovereignState) -> str:
    """Self-Correction Routing: Reject triggers a loop back to the Architect."""
    decision = state.get("guardian_decision", "")
    loops = int(state.get("loop_count", 0))
    if decision == "reject" and loops < 3: 
        return "sovereign_core"
    return "synthesis"

NODE_AGENT_MAP = {
    "intent_classifier": "intent_router",
    "fast_core": "fast_mentor",
    "life_coach": "life_coach",
    "sovereign_core": "quant_architect",
    "agency": "tool_agency",
    "auditor": "factual_auditor",
    "guardian": "system_guardian",
    "synthesis": "executive_arbiter"
}

def build_graph(checkpointer: Any):
    graph = StateGraph(SovereignState)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("fast_fanout", fast_fanout_node)
    graph.add_node("deep_fanout", deep_fanout_node)
    graph.add_node("memory_retrieval", memory_retrieval_node)
    graph.add_node("belief_retrieval", belief_retrieval_node)
    graph.add_node("grounding", grounding_node)
    graph.add_node("document_ingestion", document_ingestion_node)
    graph.add_node("perception_barrier", perception_barrier_node)
    
    graph.add_node("fast_core", fast_core_node)
    graph.add_node("life_coach", life_coach_node)
    graph.add_node("math_engine", deterministic_math_engine)
    graph.add_node("sovereign_core", sovereign_core_node)
    graph.add_node("agency", agency_node)
    graph.add_node("auditor", auditor_node)
    graph.add_node("guardian", guardian_node)
    graph.add_node("synthesis", synthesis_node)
    graph.add_node("loyalty_scorer", loyalty_scorer_node)
    graph.add_node("artifact_writer", artifact_writer_node)

    # 1. Routing Intent
    graph.add_edge(START, "intent_classifier")
    graph.add_conditional_edges("intent_classifier", route_start, {"fast": "fast_fanout", "deep": "deep_fanout"})

    # 2. Parallel Perception
    graph.add_edge("fast_fanout", "memory_retrieval")
    graph.add_edge("fast_fanout", "belief_retrieval")

    graph.add_edge("deep_fanout", "memory_retrieval")
    graph.add_edge("deep_fanout", "belief_retrieval")
    graph.add_edge("deep_fanout", "grounding")
    graph.add_edge("deep_fanout", "document_ingestion")

    graph.add_edge("memory_retrieval", "perception_barrier")
    graph.add_edge("belief_retrieval", "perception_barrier")
    graph.add_edge("grounding", "perception_barrier")
    graph.add_edge("document_ingestion", "perception_barrier")

    # 3. Core Processing
    graph.add_conditional_edges("perception_barrier", route_after_barrier, {"fast": "fast_core", "coach": "life_coach", "deep": "math_engine"})
    graph.add_edge("life_coach", "synthesis")
    graph.add_edge("math_engine", "sovereign_core")
    graph.add_edge("fast_core", "synthesis")

    # 4. V3.1 ACTIVE TOOL LOOP & SELF-CORRECTION
    graph.add_conditional_edges("sovereign_core", core_router, {"agency": "agency", "auditor": "auditor"})
    graph.add_conditional_edges("agency", agency_router, {"sovereign_core": "sovereign_core"})
    
    graph.add_edge("auditor", "guardian")
    graph.add_conditional_edges("guardian", guardian_router, {"sovereign_core": "sovereign_core", "synthesis": "synthesis"})

    # 5. Delivery
    graph.add_edge("synthesis", "loyalty_scorer")
    graph.add_edge("loyalty_scorer", "artifact_writer")
    graph.add_edge("artifact_writer", END)

    return graph.compile(checkpointer=checkpointer)

# ---------------------------------------------------------------------
# Auth and API Handlers
# ---------------------------------------------------------------------
def get_authenticated_user(x_api_key: str = Header(...)) -> str:
    if not hmac.compare_digest(x_api_key, ACTIVE_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key credentials.")
    return INTERNAL_USER_ID

def make_initial_state(req: ChatRequest | WSMessage) -> SovereignState:
    return {
        "user_input": req.prompt, "thread_id": req.thread_id, "requested_path": req.path,
        "execution_path": "", "intent_category": "", "route_reason": "", "retrieved_memory": "",
        "belief_context": "", "grounding_context": "", "ingested_docs": "", "perception_status": "",
        "fast_generation": "", "core_generation": "", "strategy_plan": "", "tool_results": "", "tool_call_count": 0,
        "audit_critique": "", "belief_conflicts": "", "guardian_decision": "", "loop_count": 0,
        "math_blueprint": "", "active_goal": "default", "final_output": "", "loyalty_scores": {}, "loyalty_verdict": ""
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.validate_dependencies()
    runtime.validate_secret()
    runtime.init_storage()
    runtime.init_db()
    runtime.init_chroma()
    runtime.init_tavily()
    runtime.init_semantic_cache()
    # Vector intent encoder runs in a thread so it doesn't block the event loop
    await asyncio.to_thread(init_intent_encoder)
    
    with sqlite3.connect(CHECKPOINT_DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        
    checkpoint_cm = AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH))
    checkpointer = await checkpoint_cm.__aenter__()
    try:
        app.state.graph = build_graph(checkpointer)
        logger.info("End Game AI V3.1 Cognitive System Online.")
        yield
    finally:
        await checkpoint_cm.__aexit__(None, None, None)

app = FastAPI(title="End_Game_AI", lifespan=lifespan)

@app.get("/api/health")
async def health(user_id: str = Depends(get_authenticated_user)):
    del user_id
    return {"status": "ok", "chroma": runtime.chroma_collection is not None, "tavily": runtime.tavily_client is not None}

@app.get("/api/agents")
async def get_agents(user_id: str = Depends(get_authenticated_user)):
    del user_id
    return {"agents": runtime.factory.manifest(), "node_agent_map": NODE_AGENT_MAP}

@app.get("/api/evolve")
async def evolve(
    prompt: str = Query(..., min_length=1, max_length=MAX_PROMPT_CHARS),
    thread_id: str = Query("main", pattern=THREAD_ID_PATTERN),
    path: Literal["auto", "fast", "deep"] = Query("auto"),
    bypass_cache: bool = Query(False, description="Skip cache read AND write — forces full pipeline. Used by eval harness."),
    user_id: str = Depends(get_authenticated_user)
):
    del user_id
    req = ChatRequest(prompt=prompt, thread_id=thread_id, path=path)
    state = make_initial_state(req)
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    async def gen():
        started = time.time()

        # ── Semantic Cache Check ───────────────────────────────────────────────
        # Skipped when bypass_cache=True (eval harness, debugging).
        cached = None if bypass_cache else await runtime.check_semantic_cache(req.prompt)
        if cached:
            yield "data: " + json.dumps({"node": "semantic_cache", "agent": "cache", "status": "hit"}) + "\n\n"
            yield "data: " + json.dumps({"phase": "Final", "content": cached, "is_final": True, "cached": True}) + "\n\n"
            return

        accumulated = {}
        _graph_error: str = ""
        try:
            async for chunk in app.state.graph.astream(state, config):
                for node, update in chunk.items():
                    # LangGraph may yield None updates for routing markers / __end__
                    # events. Guard here (WebSocket handler already has if not update: continue).
                    if update is None:
                        continue
                    accumulated.update(update)
                    yield "data: " + json.dumps({"node": node, "agent": NODE_AGENT_MAP.get(node, node), "status": "running"}) + "\n\n"
        except Exception as _exc:
            import traceback as _tb
            _graph_error = f"[GRAPH_ERROR] {type(_exc).__name__}: {_exc}\n{_tb.format_exc()}"
            logger.exception("SSE graph stream error — returning partial accumulated state.")
        final_state = {**state, **accumulated}
        runtime.log_interaction(final_state, int((time.time() - started) * 1000))
        output = final_state.get("final_output") or final_state.get("strategy_plan", "") or _graph_error
        yield "data: " + json.dumps({"phase": "Final", "content": output, "is_final": True}) + "\n\n"

        # ── Store verified response in semantic cache ──────────────────────────
        # Guards: (1) never cache graph errors; (2) skip when bypass_cache=True
        # so eval-harness runs don't pollute the cache with test results.
        if output and not output.startswith("[GRAPH_ERROR]") and not bypass_cache:
            intent = final_state.get("intent_category", "")
            await asyncio.to_thread(runtime.store_semantic_cache, req.prompt, output, intent)

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    api_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key") or ""
    logger.info("[ws-auth] received key — first 4: %s*** len: %d | expected len: %d",
                str(api_key)[:4], len(str(api_key)), len(ACTIVE_SECRET))
    if not hmac.compare_digest(str(api_key), ACTIVE_SECRET):
        logger.warning("[ws-auth] Key mismatch — rejecting connection.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    try:
        while True:
            try: raw = await websocket.receive_text()
            except WebSocketDisconnect: break
            try: req = parse_ws_message(raw)
            except Exception: continue

            started = time.time()
            state = make_initial_state(req)
            config = {"configurable": {"thread_id": req.thread_id, "checkpoint_ns": ""}}

            # ── Semantic Cache Check ───────────────────────────────────────────
            cached = await runtime.check_semantic_cache(req.prompt)
            if cached:
                await websocket.send_json({"node": "semantic_cache", "agent": "cache", "status": "complete"})
                runtime.log_interaction(state, 0)
                await websocket.send_json({"phase": "Final", "content": cached, "is_final": True, "cached": True})
                continue

            accumulated = {}
            try:
                async for chunk in app.state.graph.astream(state, config):
                    for node, update in chunk.items():
                        if not update: continue
                        accumulated.update(update)
                        await websocket.send_json({"node": node, "agent": NODE_AGENT_MAP.get(node, node), "status": "complete"})
            except Exception:
                logger.exception("WebSocket graph stream error — sending partial final state.")

            final_state = {**state, **accumulated}
            runtime.log_interaction(final_state, int((time.time() - started) * 1000))
            output = final_state.get("final_output") or final_state.get("strategy_plan", "")
            await websocket.send_json({"phase": "Final", "content": output, "is_final": True})

            # ── Store verified response in semantic cache ──────────────────────
            if output:
                intent = final_state.get("intent_category", "")
                await asyncio.to_thread(runtime.store_semantic_cache, req.prompt, output, intent)
    finally: logger.info("Session disconnected safely.")

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serves the modern React UI (ui_v2.html) at the root path."""
    ui_path = Path(__file__).parent / "ui_v2.html"
    if ui_path.exists():
        return HTMLResponse(ui_path.read_text(encoding="utf-8"))
    # Fallback to legacy UI if v2 is missing
    legacy = Path(__file__).parent / "ui.html"
    if legacy.exists():
        return HTMLResponse(legacy.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>LatticeD - System Online</h1>"
        "<p>Error: neither <b>ui_v2.html</b> nor <b>ui.html</b> was found.</p>"
    )

@app.get("/legacy", response_class=HTMLResponse)
async def serve_legacy_ui():
    """Serves the original WebSocket UI (ui.html) at /legacy for fallback testing."""
    legacy = Path(__file__).parent / "ui.html"
    if legacy.exists():
        return HTMLResponse(legacy.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Legacy UI not found.</h1>")
@app.get("/api/stats")
async def get_runtime_stats(user_id: str = Depends(get_authenticated_user)):
    """Exposes interaction history and hardware performance logs to the UI."""
    del user_id
    try:
        with runtime.open_db() as conn:
            # Fetch the last 5 hardware latency records
            hardware = conn.execute(
                "SELECT node, latency_ms, timestamp FROM hardware_log ORDER BY id DESC LIMIT 5"
            ).fetchall()
            
            # Fetch the last interaction details
            interaction = conn.execute(
                "SELECT intent, path, loop_count, latency_ms FROM interaction_ledger ORDER BY id DESC LIMIT 1"
            ).fetchone()
            
        return {
            "last_interaction": {
                "intent": interaction[0],
                "path": interaction[1],
                "loop_count": interaction[2],
                "total_latency_ms": interaction[3]
            } if interaction else None,
            "hardware_latency_log": [
                {"node": row[0], "latency_ms": row[1], "epoch": row[2]} for row in hardware
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

# ---------------------------------------------------------------------
# UI Support Endpoints — added for ui_v2.html
# ---------------------------------------------------------------------
@app.get("/api/threads")
async def list_threads(
    limit: int = Query(50, ge=1, le=500),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Return a summary list of every thread that has interaction history.
    Used by the UI's Threads view to populate the conversation list.
    """
    del user_id
    try:
        with runtime.open_db() as conn:
            rows = conn.execute(
                """
                SELECT thread_id,
                       COUNT(*) AS message_count,
                       MAX(timestamp) AS last_ts,
                       (SELECT user_input FROM interaction_ledger AS i2
                          WHERE i2.thread_id = i1.thread_id
                          ORDER BY timestamp DESC LIMIT 1) AS last_prompt,
                       (SELECT intent FROM interaction_ledger AS i3
                          WHERE i3.thread_id = i1.thread_id
                          ORDER BY timestamp DESC LIMIT 1) AS last_intent
                  FROM interaction_ledger AS i1
                 GROUP BY thread_id
                 ORDER BY last_ts DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {
            "threads": [
                {
                    "thread_id":     row[0],
                    "message_count": int(row[1]),
                    "last_epoch":    float(row[2]) if row[2] else 0.0,
                    "last_prompt":   row[3] or "",
                    "last_intent":   row[4] or "",
                }
                for row in rows
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Thread list failed: {e}")

@app.delete("/api/threads")
async def forget_all_threads(
    confirm: bool = Query(False, description="Must be true to actually delete. Safety guard."),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Bulk-delete every conversation thread — both the structured ledger entries
    AND the corresponding semantic memory vectors. Use for clean-slate dev
    workflows (recording demos, regression testing on a known state).

    Requires explicit ?confirm=true. Cache and beliefs are NOT touched —
    use the matching /api/beliefs DELETE to wipe those separately.
    """
    del user_id
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Bulk thread delete requires ?confirm=true to execute.",
        )
    try:
        # Count + delete ledger rows
        with runtime.db_lock:
            with runtime.open_db() as conn:
                ledger_count = conn.execute("SELECT COUNT(*) FROM interaction_ledger").fetchone()[0]
                conn.execute("DELETE FROM interaction_ledger")
                conn.commit()

        # Delete all conversation vectors for this user from ChromaDB
        vector_count = 0
        if runtime.chroma_collection is not None:
            def _purge_vectors():
                # Count before deleting (Chroma's delete API doesn't return a count)
                try:
                    existing = runtime.chroma_collection.get(
                        where={"user_id": INTERNAL_USER_ID},
                        include=[],
                    )
                    n = len(existing.get("ids", []))
                except Exception:
                    n = 0
                runtime.chroma_collection.delete(where={"user_id": INTERNAL_USER_ID})
                return n
            vector_count = await asyncio.to_thread(_purge_vectors)

        logger.warning(
            "[forget_all_threads] Purged ALL threads — %d ledger rows, %d memory vectors.",
            ledger_count, vector_count,
        )
        return {
            "ok": True,
            "ledger_rows_deleted": int(ledger_count),
            "memory_vectors_deleted": int(vector_count),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk thread forget failed: {e}")

@app.delete("/api/threads/{thread_id}")
async def forget_thread(
    thread_id: str,
    user_id: str = Depends(get_authenticated_user),
):
    """
    Delete a single conversation thread completely — removes the interaction
    ledger rows AND the corresponding semantic memory vectors. After this call,
    no part of the conversation can be recalled by future queries.
    """
    del user_id
    if not re.match(THREAD_ID_PATTERN, thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread_id format.")
    try:
        with runtime.db_lock:
            with runtime.open_db() as conn:
                ledger_count = conn.execute(
                    "SELECT COUNT(*) FROM interaction_ledger WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()[0]
                if ledger_count == 0:
                    # Don't 404 — vectors might still exist; continue to purge them.
                    logger.info("[forget_thread] No ledger rows for %s; checking vectors.", thread_id)
                conn.execute(
                    "DELETE FROM interaction_ledger WHERE thread_id = ?",
                    (thread_id,),
                )
                conn.commit()

        vector_count = 0
        if runtime.chroma_collection is not None:
            def _purge_vectors():
                try:
                    existing = runtime.chroma_collection.get(
                        where={"$and": [
                            {"user_id":   INTERNAL_USER_ID},
                            {"thread_id": thread_id},
                        ]},
                        include=[],
                    )
                    n = len(existing.get("ids", []))
                except Exception:
                    n = 0
                runtime.chroma_collection.delete(where={"$and": [
                    {"user_id":   INTERNAL_USER_ID},
                    {"thread_id": thread_id},
                ]})
                return n
            vector_count = await asyncio.to_thread(_purge_vectors)

        logger.info(
            "[forget_thread] Purged thread %s — %d ledger rows, %d memory vectors.",
            thread_id, ledger_count, vector_count,
        )
        return {
            "ok": True,
            "thread_id": thread_id,
            "ledger_rows_deleted": int(ledger_count),
            "memory_vectors_deleted": int(vector_count),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Thread forget failed: {e}")

@app.get("/api/threads/{thread_id}/history")
async def get_thread_history(
    thread_id: str,
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(get_authenticated_user),
):
    """Return the full interaction history for a specific thread, oldest first."""
    del user_id
    if not re.match(THREAD_ID_PATTERN, thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread_id format.")
    try:
        with runtime.open_db() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, user_input, intent, path, latency_ms, output_prev
                  FROM interaction_ledger
                 WHERE thread_id = ?
                 ORDER BY timestamp ASC
                 LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        return {
            "thread_id": thread_id,
            "messages": [
                {
                    "epoch":      float(row[0]),
                    "user_input": row[1] or "",
                    "intent":     row[2] or "",
                    "path":       row[3] or "",
                    "latency_ms": int(row[4]) if row[4] is not None else 0,
                    "response":   row[5] or "",
                }
                for row in rows
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Thread history failed: {e}")

@app.get("/api/beliefs")
async def list_beliefs(
    limit: int = Query(50, ge=1, le=500),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Return belief graph entries with raw and effective (decay-adjusted) confidence.
    Effective confidence uses the same DECAY_LAMBDA as the live retrieval logic.
    """
    del user_id
    try:
        with runtime.open_db() as conn:
            rows = conn.execute(
                """
                SELECT id, fact, confidence, last_seen, source
                  FROM belief_graph
                 WHERE confidence > 0.20
                 ORDER BY last_seen DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        now = time.time()
        beliefs = []
        for bid, fact, raw_conf, last_seen, source in rows:
            age_days = (now - float(last_seen)) / 86400.0
            eff_conf = float(raw_conf) * math.exp(-DECAY_LAMBDA * age_days)
            beliefs.append({
                "id":                 int(bid),
                "fact":               fact,
                "raw_confidence":     round(float(raw_conf), 3),
                "effective_confidence": round(eff_conf, 3),
                "age_days":           round(age_days, 1),
                "last_seen_epoch":    float(last_seen),
                "source":             source or "",
            })
        beliefs.sort(key=lambda b: b["effective_confidence"], reverse=True)
        return {"beliefs": beliefs, "decay_half_life_days": 45}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Belief query failed: {e}")

@app.delete("/api/beliefs")
async def forget_all_beliefs(
    confirm: bool = Query(False, description="Must be true to actually delete. Safety guard."),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Bulk-delete every entry in the belief graph. Intended for dev/test workflows
    where the user needs a clean slate (e.g. before recording a demo or running
    the eval harness on a contaminated database).

    Requires explicit ?confirm=true to execute — a single accidental DELETE
    request returns a clear error instead of wiping the graph.
    """
    del user_id
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Bulk delete requires ?confirm=true to execute.",
        )
    try:
        with runtime.db_lock:
            with runtime.open_db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM belief_graph").fetchone()[0]
                conn.execute("DELETE FROM belief_graph")
                conn.commit()
        logger.warning("[forget_all_beliefs] Purged ALL belief graph entries: %d rows deleted.", count)
        return {"ok": True, "deleted_count": int(count)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk forget failed: {e}")

@app.delete("/api/beliefs/{belief_id}")
async def forget_belief(
    belief_id: int = ApiPath(..., ge=1),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Hard-delete a single belief by ID. Used by the UI's 'Forget' button to purge
    contamination — beliefs the Fact Extractor stored that turned out to be wrong,
    or facts that are no longer relevant. The Fact Extractor will re-add the fact
    on a future session if it sees it confirmed again.
    """
    del user_id
    try:
        with runtime.db_lock:
            with runtime.open_db() as conn:
                # Capture the fact text before delete for logging
                row = conn.execute(
                    "SELECT fact FROM belief_graph WHERE id = ?", (belief_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail=f"Belief {belief_id} not found.")
                fact_preview = (row[0] or "")[:120]
                conn.execute("DELETE FROM belief_graph WHERE id = ?", (belief_id,))
                conn.commit()
        logger.info("[forget_belief] Purged id=%d — '%s'", belief_id, fact_preview)
        return {"ok": True, "deleted_id": belief_id, "fact_preview": fact_preview}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forget failed: {e}")

@app.post("/api/docs/upload")
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Accept a single document and save it into the runtime/docs/ folder so the
    document_ingestion_node can pick it up on the next deep-path query.
    Only .md files are accepted to match the existing ingestion logic.
    """
    del user_id
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    # Reject anything that isn't markdown — keeps the ingestion pipeline simple
    if not file.filename.lower().endswith(".md"):
        raise HTTPException(
            status_code=415,
            detail="Only .md (Markdown) files are accepted. Convert other formats first.",
        )

    # Sanitise the filename — keep only safe characters, prevent path traversal
    safe_name = re.sub(r"[^A-Za-z0-9._\-]", "_", Path(file.filename).name)
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    target = DOCS_DIR / safe_name
    try:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        contents = await file.read()
        # Cap individual document size at MAX_DOC_CHARS (in bytes — approximate cap)
        if len(contents) > MAX_DOC_CHARS * 4:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max {MAX_DOC_CHARS * 4} bytes per upload.",
            )
        target.write_bytes(contents)
        logger.info("[upload] Document saved: %s (%d bytes)", safe_name, len(contents))
        return {
            "ok":       True,
            "filename": safe_name,
            "bytes":    len(contents),
            "path":     str(target.relative_to(ROOT_DIR)),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

@app.get("/api/docs")
async def list_documents(user_id: str = Depends(get_authenticated_user)):
    """List the documents currently sitting in runtime/docs/ awaiting ingestion."""
    del user_id
    try:
        files = []
        if DOCS_DIR.exists():
            for p in sorted(DOCS_DIR.glob("*.md")):
                stat = p.stat()
                files.append({
                    "filename":      p.name,
                    "bytes":         stat.st_size,
                    "modified_epoch": stat.st_mtime,
                })
        return {"documents": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document listing failed: {e}")

# ---------------------------------------------------------------------
# Application Execution Entry Point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    # Launch the ASGI production server locally on port 8000
    logger.info("Initializing Uvicorn production engine...")
    uvicorn.run(
        "End_Game_AI:app", 
        host="127.0.0.1", 
        port=8000, 
        reload=False, 
        log_level="info"
    )
