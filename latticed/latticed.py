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
from dataclasses import asdict, dataclass, field
from enum import Enum
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Optional, Tuple, TypedDict

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
ROOT_DIR = Path(os.getenv("LATTICED_ROOT") or os.getenv("EARL_ROOT") or str(Path(__file__).resolve().parent / "runtime")).resolve()
STORAGE_DIR = ROOT_DIR / "storage"
OUTPUT_DIR = ROOT_DIR / "outputs"
DOCS_DIR = Path(os.getenv("LATTICED_DOCS_DIR") or os.getenv("EARL_DOCS_DIR") or str(ROOT_DIR / "docs")).resolve()

APP_DB_PATH = STORAGE_DIR / "latticed.db"
CHECKPOINT_DB_PATH = STORAGE_DIR / "latticed_checkpoints.db"
CHROMA_PATH = STORAGE_DIR / "vector_memory"

DEFAULT_SECRET = "local_dev_secret_123"
ACTIVE_SECRET = os.getenv("LATTICED_SECRET") or os.getenv("EARL_SECRET") or os.getenv("JARVIS_SECRET") or DEFAULT_SECRET
logger.info("[auth] ACTIVE_SECRET loaded — first 4 chars: %s*** length: %d", ACTIVE_SECRET[:4], len(ACTIVE_SECRET))
INTERNAL_USER_ID = os.getenv("LATTICED_USER_ID") or os.getenv("EARL_USER_ID") or "latticed_user"

MAX_PROMPT_CHARS = int(os.getenv("LATTICED_MAX_PROMPT_CHARS") or os.getenv("EARL_MAX_PROMPT_CHARS") or "4000")
MAX_DOC_CHARS = int(os.getenv("LATTICED_MAX_DOC_CHARS") or os.getenv("EARL_MAX_DOC_CHARS") or "12000")
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
    # Note: bare "pay" is intentionally EXCLUDED — in English, "I pay $X for Y"
    # signals an expense (money going out), not income. Only "paycheck" /
    # "paychecks" reliably indicate income. The prior pattern pay(?:check)?
    # was too permissive and caused "pay $1,300 in rent" to be classified
    # as income, summed alongside actual income figures.
    r"\b(?:earn|make|income|salary|take.?home|revenue|bring|wages?|paychecks?|gross|net pay)\b",
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

# ── Category Taxonomy ─────────────────────────────────────────────────────────
# Every memory written to ChromaDB and every fact added to the belief graph is
# tagged with one or more life-event categories from this fixed taxonomy.
#
# The anchor text is written in QUESTION SHAPE — each anchor describes the kind
# of question a memory in this category could answer.  This aligns retrieval
# (where users ask "what did I do for fun?") with storage (where memories get
# tagged by which questions they plausibly answer).  Cosine similarity between
# a memory and an anchor measures "could this memory plausibly answer that
# kind of question."
#
# Categorization is hybrid: anchor embedding similarity (~0.7 weight) plus
# keyword presence (~0.3 weight).  Multi-label by design — most life events
# span multiple categories (e.g. "hiking with the kids" → family + entertainment).
CATEGORY_ANCHORS_TEXT: Dict[str, str] = {
    "work":          "What meetings, projects, deadlines, deals, or career events "
                     "happened? Work assignments, professional conversations, office "
                     "politics, performance reviews, business decisions, job duties.",
    "health":        "When did I last see the doctor? What appointments, exercise, "
                     "sleep, symptoms, medications, or wellness matters came up? "
                     "Medical visits, physical activity, mental health, therapy.",
    "family":        "What involved my spouse, partner, kids, parents, siblings, or "
                     "extended family? Time with the kids, taking them places, weekends "
                     "with family, activities together, family outings, raising children, "
                     "playing with kids, picking up the kids, family gatherings, "
                     "conversations with relatives, household coordination, childcare, "
                     "family decisions, dinner with the family.",
    "social":        "Who did I see socially — friends, dating, social gatherings, "
                     "club meetings, parties, drinks, social events outside work and family?",
    "entertainment": "What did I do for fun? Movies, games, concerts, hobbies, shows, "
                     "recreation, leisure activities, things I enjoyed in my free time.",
    "finance":       "What about money — budget, savings, investments, expenses, taxes, "
                     "major purchases, financial decisions, income, bills, debt?",
    "education":     "What did I learn or study? Courses, books, school assignments, "
                     "training, professional development, academic work, certifications.",
    "travel":        "What about trips, vacations, commutes, transportation, destinations, "
                     "flights, hotels, road trips, travel planning?",
    "home":          "What about the household — repairs, renovations, real estate, "
                     "chores, maintenance, neighborhood, yard, moving?",
    "food":          "What did I cook, eat, order, or buy for food? Restaurants, "
                     "groceries, dining out, recipes, meal planning, drinks.",
    "other":         "General conversation, casual remarks, miscellaneous topics that "
                     "do not fit a more specific category.",
}

# Lowercase keyword sets per category. Presence of any keyword in the memory text
# contributes to that category's hybrid score. Designed to be additive with
# embedding similarity, not a replacement.
CATEGORY_KEYWORDS: Dict[str, set] = {
    "work":          {"work", "working", "worked", "workplace", "meeting", "project", "deadline",
                      "boss", "coworker", "colleague", "office", "client", "deal",
                      "presentation", "promotion", "raise", "performance", "review",
                      "report", "email", "calendar", "team", "deliverable", "sprint",
                      "deploy", "ship", "manager", "job", "career"},
    "health":        {"doctor", "appointment", "medication", "prescription", "exercise",
                      "workout", "gym", "run", "running", "hike", "hiking", "walk", "diet",
                      "sleep", "headache", "sick", "ill", "symptom", "blood", "pressure",
                      "therapy", "therapist", "checkup", "physical", "wellness", "mental"},
    "family":        {"wife", "husband", "spouse", "partner", "kid", "kids", "child",
                      "children", "son", "daughter", "mom", "dad", "mother", "father",
                      "parents", "sister", "brother", "sibling", "family", "grandkids",
                      "grandma", "grandpa", "cousin", "in-law"},
    "social":        {"friend", "friends", "date", "dating", "party", "gathering",
                      "drinks", "hangout", "club", "meetup", "happy hour", "brunch",
                      "social", "bestie"},
    "entertainment": {"movie", "film", "game", "gaming", "show", "concert", "music",
                      "hobby", "fun", "relax", "leisure", "watch", "play", "festival",
                      "weekend", "vacation", "tv", "netflix", "podcast", "book club"},
    "finance":       {"budget", "saving", "savings", "investment", "stock", "bond",
                      "income", "expense", "rent", "mortgage", "debt", "loan", "credit",
                      "tax", "salary", "money", "dollar", "cost", "afford", "spend",
                      "bill", "401k", "ira", "retirement", "broker"},
    "education":     {"learn", "course", "class", "book", "read", "study", "school",
                      "university", "college", "degree", "training", "certification",
                      "exam", "homework", "tuition"},
    "travel":        {"trip", "travel", "traveling", "traveled", "vacation", "flight",
                      "fly", "flying", "flew", "hotel", "drive", "drove", "commute",
                      "airport", "destination", "abroad", "passport", "airbnb", "uber",
                      "lyft", "book", "booked", "booking", "boarding", "itinerary"},
    "home":          {"house", "apartment", "repair", "renovation", "neighbor", "yard",
                      "garden", "chore", "clean", "maintenance", "lawn", "plumbing",
                      "electrician", "contractor", "move", "moving"},
    "food":          {"eat", "ate", "cook", "cooking", "restaurant", "dinner", "lunch",
                      "breakfast", "groceries", "grocery", "recipe", "meal", "kitchen",
                      "order", "delivery", "takeout", "coffee", "beer", "wine"},
}

# Computed once at startup; populated by init_intent_encoder().
CATEGORY_ANCHOR_EMBEDDINGS: Dict[str, Any] = {}

# Hybrid scoring weights and threshold (configurable).
#
# Weights re-balanced 0.6 embedding / 0.4 keyword after measuring real scores:
# all-MiniLM-L6-v2 gives surprisingly low similarities (0.20-0.30) for activity
# sentences against noun-heavy anchors. Pure keyword hits like 'kids' or 'flight'
# were getting under-weighted at 0.3, so clean unambiguous signals couldn't lift
# borderline cases over threshold. 0.4 keyword weight lets strong matches matter
# without overwhelming the semantic embedding contribution.
#
# Threshold lowered from 0.40 to 0.25 in two stages. 0.40 was a rough estimate
# from intuition. Measured embedding similarities are consistently 0.15-0.30 for
# related concepts, so 0.40 was structurally too high. 0.25 is calibrated to
# what 'moderate combined evidence' actually looks like with this encoder.
CATEGORY_HYBRID_EMB_WEIGHT     = 0.60
CATEGORY_HYBRID_KEYWORD_WEIGHT = 0.40
CATEGORY_MATCH_THRESHOLD       = 0.25
CATEGORY_KEYWORD_SATURATION    = 3      # 3 keyword hits = max keyword score (1.0)

# When the top category is in this range, the result is "ambiguous" — strong
# enough to be suggestive but not strong enough to commit. The system queues a
# question for the user instead of guessing silently.
CATEGORY_AMBIGUITY_FLOOR  = 0.18    # Below this, no candidate is plausible enough to ask about
CATEGORY_AMBIGUITY_CEILING = 0.32   # Above this, we're confident enough to skip asking
CATEGORY_TIE_GAP          = 0.05    # If top two are within this, also ambiguous

def categorize_with_confidence(text: str, max_categories: int = 3
) -> Tuple[List[str], bool, List[Tuple[str, float]]]:
    """
    Extended categorizer used by the active learning loop.

    Returns:
        categories         : auto-assigned categories above threshold (may be empty
                             when ambiguous — in that case the system queues a question)
        ambiguous          : True when the result is uncertain enough to ask the user
        ranked_candidates  : (category, score) tuples sorted by score, top 5
    """
    if not text or not text.strip() or not CATEGORY_ANCHOR_EMBEDDINGS:
        return ["other"], False, []

    try:
        import numpy as np
        encoder = _get_shared_st_model() if _SHARED_ST_MODEL is not None else None
        if encoder is None:
            return ["other"], False, []

        text_emb  = encoder.encode(text, convert_to_numpy=True)
        text_norm = float(np.linalg.norm(text_emb)) or 1.0
        text_lower = text.lower()
        text_words = set(re.findall(r"[a-z0-9]+", text_lower))

        def _kw_match(kw: str) -> bool:
            return (kw in text_lower) if " " in kw else (kw in text_words)

        scores: Dict[str, float] = {}
        for category, anchor_emb in CATEGORY_ANCHOR_EMBEDDINGS.items():
            a_norm  = float(np.linalg.norm(anchor_emb)) or 1.0
            emb_sim = float(np.dot(text_emb, anchor_emb) / (text_norm * a_norm))
            keywords = CATEGORY_KEYWORDS.get(category, set())
            if keywords:
                hits = sum(1 for kw in keywords if _kw_match(kw))
                kw_score = min(1.0, hits / CATEGORY_KEYWORD_SATURATION)
            else:
                kw_score = 0.0
            scores[category] = (
                CATEGORY_HYBRID_EMB_WEIGHT     * emb_sim +
                CATEGORY_HYBRID_KEYWORD_WEIGHT * kw_score
            )

        ranked = sorted(scores.items(), key=lambda t: t[1], reverse=True)
        top_candidates = ranked[:5]
        # Exclude the "other" sink from suggestion lists (it's the fallback, not a real suggestion)
        suggested = [(c, round(s, 4)) for c, s in top_candidates if c != "other" and s >= 0.15]

        above_threshold = [(c, s) for c, s in ranked if s >= CATEGORY_MATCH_THRESHOLD and c != "other"]

        # Ambiguity detection
        ambiguous = False
        top_score = ranked[0][1] if ranked else 0.0
        if above_threshold:
            # Confident enough to assign — but check for ties
            if len(above_threshold) >= 2 and (above_threshold[0][1] - above_threshold[1][1]) < CATEGORY_TIE_GAP:
                ambiguous = True
            elif top_score < CATEGORY_AMBIGUITY_CEILING:
                # Right above threshold but still uncertain
                ambiguous = True
            categories = [c for c, _ in above_threshold[:max_categories]]
        else:
            # Nothing above threshold
            if top_score >= CATEGORY_AMBIGUITY_FLOOR:
                # Plausible but uncertain — ask the user
                ambiguous = True
                categories = []   # don't auto-tag while pending
            else:
                # Truly off-topic
                categories = ["other"]

        return categories, ambiguous, suggested
    except Exception:
        logger.warning("[categorize_with_confidence] Failed; defaulting to 'other'.", exc_info=True)
        return ["other"], False, []

def categorize_text(text: str, max_categories: int = 3) -> List[str]:
    """
    Hybrid categorization — combines anchor embedding similarity with keyword
    presence to tag a memory with 1-3 life-event categories. Returns ["other"]
    if no category meets CATEGORY_MATCH_THRESHOLD.

    Performance: ~5-15ms per call (one new embedding + 11 cosine comparisons +
    11 keyword scans). Reuses _SHARED_ST_MODEL — no extra VRAM, no LLM call.

    Multi-label by design — most life events span multiple categories.
    """
    if not text or not text.strip() or not CATEGORY_ANCHOR_EMBEDDINGS:
        return ["other"]

    try:
        import numpy as np
        encoder = _get_shared_st_model() if _SHARED_ST_MODEL is not None else None
        if encoder is None:
            return ["other"]

        text_emb  = encoder.encode(text, convert_to_numpy=True)
        text_norm = float(np.linalg.norm(text_emb)) or 1.0
        text_lower = text.lower()
        # Word-boundary set: prevents 'great' from matching 'eat' as substring.
        # For multi-word keywords (e.g. 'happy hour'), we fall back to substring
        # check against the lowercased text.
        text_words = set(re.findall(r"[a-z0-9]+", text_lower))

        def _kw_match(kw: str) -> bool:
            return (kw in text_lower) if " " in kw else (kw in text_words)

        scores: Dict[str, float] = {}
        for category, anchor_emb in CATEGORY_ANCHOR_EMBEDDINGS.items():
            a_norm  = float(np.linalg.norm(anchor_emb)) or 1.0
            emb_sim = float(np.dot(text_emb, anchor_emb) / (text_norm * a_norm))

            keywords = CATEGORY_KEYWORDS.get(category, set())
            if keywords:
                hits = sum(1 for kw in keywords if _kw_match(kw))
                # 3 keyword hits saturates to 1.0. Short phrases with 1-2 hits
                # still get meaningful scores (0.33 and 0.67 respectively).
                kw_score = min(1.0, hits / CATEGORY_KEYWORD_SATURATION)
            else:
                kw_score = 0.0

            scores[category] = (
                CATEGORY_HYBRID_EMB_WEIGHT     * emb_sim +
                CATEGORY_HYBRID_KEYWORD_WEIGHT * kw_score
            )

        # Filter and sort
        passing = [(cat, sc) for cat, sc in scores.items() if sc >= CATEGORY_MATCH_THRESHOLD]
        passing.sort(key=lambda t: t[1], reverse=True)
        result = [cat for cat, _ in passing[:max_categories]]
        return result if result else ["other"]
    except Exception:
        logger.warning("[categorize_text] Scoring failed; defaulting to 'other'.", exc_info=True)
        return ["other"]

# ── Semantic Cache ─────────────────────────────────────────────────────────────
# Cosine similarity threshold for a cache hit (0.98 = nearly identical prompts).
SEMANTIC_CACHE_THRESHOLD = 0.98

# Minimum cosine similarity for a belief to be considered relevant to the current
# user query. Below this, the belief is filtered out of retrieval — preventing
# off-topic beliefs from contaminating unrelated conversations.
# 0.30 = loosely related (e.g. "fun" matching beliefs about hobbies and activities)
# 0.50 = moderately related
# 0.70 = strongly related
BELIEF_RELEVANCE_THRESHOLD = 0.30
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

# =====================================================================
# SPRINT 0 — MODEL INTELLIGENCE LAYER
# =====================================================================
#
# STATUS: Sprint 0 foundation complete.  All 8 steps landed; runtime
# behavior on MINIMAL_GPU is preserved bit-for-bit.  The Model Intelligence
# Layer is in place and available for opt-in use by future sprints.
#
#   1. [DONE] Every AgentSpec declares capabilities_required,
#      adversarial_pair (where applicable), consensus_requirement, and
#      model_pool_per_tier.  Documented compromise: architect_explore's
#      model_name still points to MODEL_SYNTHESIS on MINIMAL_GPU until
#      pool-based selection ships in a later sprint.
#   2. [DONE] hardware_profile_detect() + DEFAULT_PROFILES + optional
#      runtime/profiles/*.yaml overrides (minimal_gpu, standard, high,
#      enterprise).  LATTICED_TIER env var forces a tier.
#   3. [DONE] run_behavioral_fingerprint() runs 12 standardized prompts
#      per model and caches an 8-dim feature vector per axis to
#      runtime/storage/model_fingerprints.json.  Pure-text heuristic;
#      no embedding model required.
#   4. [DONE] model_diversity_score() (cosine distance, averaged over
#      shared axes) + validate_profile_against_agents() with four
#      structural checks: two-model minimum, adversarial-pair family
#      diversity per tier, fingerprint similarity floor, consensus
#      satisfiability.
#   5. [DONE] apply_profile_overrides() applies per-tier consensus bumps;
#      enforce_consensus() reconciles N candidates under any of the five
#      ConsensusRequirement modes (SINGLE_MODEL through SUPERMAJORITY).
#   6. [DONE] surface_disagreement() formats competing model outputs into
#      a single user-facing message that EXPOSES rather than hides
#      cross-model disagreement.  Replaces silent picking when
#      triangulation fails on stakes-bearing claims.
#   7. [DONE] tests/test_sprint0.py — 21 standalone tests covering
#      profile detection, override paths, validator pass/fail/warn paths
#      (including same-family adversarial pair rejection above
#      MINIMAL_GPU), consensus reconciliation across all modes, and
#      fingerprint vector shape.  21/21 passing.
#   8. [DONE] Baseline confirmed: AgentFactoryRegistry instantiates all
#      11 agents, MINIMAL_GPU profile validates as VALID, runtime
#      pipeline behavior unchanged (additive metadata only).  Full HTTP
#      eval harness requires running server and is environmentally
#      gated; it is unaffected by Sprint 0's additive additions.
#
# RUNTIME WIRING (future sprint): the profile layer is INERT at startup
# today.  To activate, call:
#     profile = hardware_profile_detect()
#     apply_profile_overrides(profile, runtime.factory.registry)
#     report  = validate_profile_against_agents(profile, runtime.factory.registry)
# during EarlRuntime.init_storage() and abort startup if report.valid==False.
# Held back so MINIMAL_GPU keeps shipping unchanged until pool-based
# model selection lands in the same sprint that flips runtime to read
# from model_pool_per_tier instead of model_name.
#
# ARCHITECTURAL PRINCIPLES (inviolable):
#   - Two-model minimum: ALWAYS at least two distinct model families
#   - Higher tiers add MORE distinct models, never converge to one
#   - Capability-based: agents declare what they need, runtime picks model
#   - Diversity is measured (fingerprinting), not assumed (parameter counts)
#   - Consensus is structural, configurable per agent, defaults safe
#   - When models disagree on stakes-bearing claims: surface to user,
#     never silently pick one
#
# ---------------------------------------------------------------------
#
# LatticeD's value is the orchestration, not the model size.  This abstraction
# decouples agents from specific models — agents declare CAPABILITIES required,
# the runtime picks the best available model with those capabilities at the
# active hardware tier.  Two-model minimum is structurally enforced.
#
# As hardware scales up, the architecture gets MORE adversarial (more distinct
# models running in parallel), never converging to a single model.  Higher
# tiers add more model families, more speculative branches, and stricter
# cross-model consensus requirements — not bigger single models.
#
# ─── Hardware Tiers ─────────────────────────────────────────────────────────
class ModelTier(str, Enum):
    """
    Hardware capability tiers.  Each tier defines what model classes the
    framework can use, but ALL tiers enforce the two-model-minimum principle.
    Higher tiers add MORE distinct model families, not bigger single models.
    """
    MINIMAL_CPU  = "minimal_cpu"    # BitNet b1.58 + small quantized, no GPU
    MINIMAL_GPU  = "minimal_gpu"    # 4GB VRAM, current default (deepseek-r1:1.5b + qwen2.5-coder:1.5b)
    STANDARD     = "standard"       # 8-12GB VRAM, 7B-class models, two distinct families
    HIGH         = "high"           # 16-24GB VRAM, 32B-class models, THREE distinct families (added critic)
    ENTERPRISE   = "enterprise"     # 40-80GB VRAM, 70B-class models, FOUR-FIVE distinct families
    HYBRID       = "hybrid"         # Local + Cloud API burst with sensitivity-tagged routing

# ─── Model Capabilities ─────────────────────────────────────────────────────
class Capability(str, Enum):
    """
    Capability vocabulary — what a model can do well.  Agents declare which
    capabilities they require/prefer; the framework picks the best available
    model with those capabilities at the active tier.

    These are evidence-based behavioral attributes, measured at startup via
    the behavioral fingerprint test (Sprint 0 Phase 2), not assumed from
    parameter counts.
    """
    REASONING            = "reasoning"             # Multi-step logical inference
    STRUCTURED_OUTPUT    = "structured_output"     # JSON-schema-constrained generation
    INSTRUCTION_FOLLOWING = "instruction_following" # Adherence to detailed prompts
    MATH_REASONING       = "math_reasoning"        # Arithmetic and quantitative thinking
    CODE_GENERATION      = "code_generation"       # Syntactically correct code
    LONG_CONTEXT         = "long_context"          # Handle 16K+ context windows
    FACTUAL_RECALL       = "factual_recall"        # Surface stored facts accurately
    EMOTIONAL_INTELLIGENCE = "emotional_intelligence" # Warm, attuned conversational tone
    CREATIVE_GENERATION  = "creative_generation"   # Generate novel framings, surprises
    REFUSAL_DISCIPLINE   = "refusal_discipline"    # Decline inappropriate requests reliably
    BRIEF_RESPONSES      = "brief_responses"       # Avoid rambling on short prompts
    NUANCED_CRITIQUE     = "nuanced_critique"      # Identify subtle errors in others' output

class CapabilityLevel(str, Enum):
    """How strongly an agent requires/prefers a capability."""
    STRONG    = "strong"     # Mandatory for the agent's function
    MODERATE  = "moderate"   # Important but not blocking
    USEFUL    = "useful"     # Nice to have
    AVOID     = "avoid"      # Forbid models with this attribute

class ConsensusRequirement(str, Enum):
    """
    How much cross-model agreement is required before an agent's output is
    accepted.  Critical claims (financial, medical) require triangulation;
    casual chat does not.
    """
    SINGLE_MODEL              = "single_model"               # One model's output is enough
    PAIR_AGREEMENT            = "pair_agreement"             # Two models must agree (default for math/factual)
    TRIANGULATION_REQUIRED    = "triangulation_required"     # Three models must converge (critical claims)
    SUPERMAJORITY             = "supermajority"              # 3-of-5 or more (high-stakes only)
    SURFACE_DISAGREEMENT      = "surface_disagreement"       # When models disagree, show the user — don't hide it

# ─── Behavioral Fingerprinting (Sprint 0 phase 2) ───────────────────────────
# The system runs a 12-15 prompt fingerprint test against each available model
# at first startup and caches the result.  This produces evidence-based
# capability profiles rather than parameter-count assumptions.
#
# Two models with the same name but different fine-tuning produce different
# fingerprints.  Two models from the same family behave similarly even at
# different sizes.  The fingerprint catches both cases.
BEHAVIORAL_FINGERPRINT_PROMPTS: List[Tuple[str, str]] = [
    # (prompt, evaluation_axis) — measured per model at load time
    ("Respond with exactly the word 'acknowledged' and nothing else.", "instruction_following"),
    ("List three primary colors. Respond with one word per line.", "structured_output"),
    ("What is 47 * 23? Show your steps.", "math_reasoning"),
    ("In one sentence: why do leaves change color?", "brief_responses"),
    ("A user says: 'my dog died today.' How would you respond? Just the response, nothing else.", "emotional_intelligence"),
    ("Generate Python code that returns the median of a list. Include only the function.", "code_generation"),
    ("If a user asks for medical advice about chest pain, what should you do?", "refusal_discipline"),
    ("Identify the logical flaw: 'I drink coffee every morning. This morning I drank coffee. Therefore tomorrow will be a good day.'", "nuanced_critique"),
    ("In 3 words or less: capital of France.", "brief_responses"),
    ("Generate a one-line creative metaphor for 'change'.", "creative_generation"),
    ("Given: User asked about IRS Form 1040. List the 4 main sections.", "factual_recall"),
    ("Compare: writing a novel vs. writing a screenplay. Pick the more constrained format and explain why in 2 sentences.", "reasoning"),
]

# Threshold below which two models are considered "behaviorally too similar"
# to count as a valid adversarial pair.  Set deliberately strict.
MODEL_DIVERSITY_MIN = 0.45    # cosine distance between fingerprint vectors

# ─── Extended Agent Factory Registry Layer ──────────────────────────────────
@dataclass
class AgentSpec:
    """
    Agent specification.

    Existing fields (model_name, temperature, max_tokens, system_prompt,
    output_schema) preserve full backward compatibility — if no new tier-aware
    fields are provided, the agent runs exactly as before on MINIMAL_GPU.

    New Sprint 0 fields enable the Model Intelligence Layer:
    - capabilities_required / capabilities_preferred / capabilities_avoid:
        Declarative capability requirements. The runtime picks the best
        available model with these traits.
    - adversarial_pair:
        Names another agent this one must NOT share a model family with.
        Enforces structural diversity for cross-model review.
    - consensus_requirement:
        How much cross-model agreement is needed before this agent's output
        is committed. Critical claims need triangulation; chat does not.
    - minimum_models_must_agree:
        For claims requiring consensus, how many distinct models must produce
        the same answer.
    - model_pool_per_tier:
        Per-tier list of allowed model identifiers. The runtime picks
        the best available from this pool at the active tier.
    - scales_with:
        At which tier this agent particularly benefits from upgrade
        (informs how speculative branching widens at higher tiers).
    """
    agent_id: str
    display_name: str
    purpose: str
    model_name: str
    temperature: float
    max_tokens: int
    system_prompt: str
    output_schema: Optional[Dict[str, Any]] = None  # JSON Schema for constrained generation

    # Sprint 0 — Model Intelligence Layer (all optional, additive)
    capabilities_required:    Dict[str, str]      = field(default_factory=dict)  # Capability → CapabilityLevel
    capabilities_preferred:   Dict[str, str]      = field(default_factory=dict)
    capabilities_avoid:       List[str]           = field(default_factory=list)  # List[Capability]
    adversarial_pair:         Optional[str]       = None                          # agent_id of paired adversary
    consensus_requirement:    str                 = ConsensusRequirement.SINGLE_MODEL.value
    minimum_models_must_agree: int                = 1
    model_pool_per_tier:      Dict[str, List[str]] = field(default_factory=dict) # ModelTier → [model_names]
    scales_with:              Optional[str]       = None                         # ModelTier where this agent gains the most
    minimum_tier:             str                 = ModelTier.MINIMAL_GPU.value
    preferred_tier:           str                 = ModelTier.MINIMAL_GPU.value

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
                },
                capabilities_required={
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
                    ModelTier.STANDARD.value:    ["qwen2.5-coder:7b"],
                    ModelTier.HIGH.value:        ["qwen2.5-coder:14b"],
                    ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b"],
                },
                scales_with=ModelTier.STANDARD.value,
                preferred_tier=ModelTier.STANDARD.value,
            ),
            "fast_mentor": AgentSpec(
                agent_id="fast_mentor",
                display_name="Fast Mentor",
                purpose="Handles light interactive chat utilizing interpersonal empathy and lifelong learning.",
                model_name=MODEL_REASONING,
                temperature=0.6,
                max_tokens=400,
                system_prompt=(
                    "You are LatticeD — a thoughtful, curious personal companion. The user is sharing "
                    "a moment from their life with you. Your job is to respond like a good friend would: "
                    "show interest, ASK A FOLLOW-UP QUESTION, react warmly, and only offer advice when "
                    "the user clearly asks for it.\n\n"
                    "CRITICAL: Focus entirely on the CURRENT 'Request' line. Do not reference 'History', "
                    "'Beliefs', or anything else you see in the context unless the user's current message "
                    "is literally about that past topic. If History contains 'park' and the user just said "
                    "'I made dinner', ignore the park entirely and respond about dinner.\n\n"
                    "DEFAULT BEHAVIOR — when the user shares something casual:\n"
                    "1. Acknowledge what they said in 2-5 words.\n"
                    "2. Ask ONE specific follow-up question about it.\n"
                    "3. Stop. Do not assume how they felt, what they did, or what they want.\n\n"
                    "EXAMPLES (these show the pattern — adapt naturally to what the user says):\n\n"
                    "  User: 'Spent the day at the park.'\n"
                    "  You: 'Nice. What did you do there?'\n\n"
                    "  User: 'Caught up with my brother today.'\n"
                    "  You: 'How is he doing?'\n\n"
                    "  User: 'Long week.'\n"
                    "  You: 'Sorry to hear that. What's been weighing on you most?'\n\n"
                    "  User: 'I made dinner.'\n"
                    "  You: 'What did you make?'\n\n"
                    "  User: 'How are you today?'\n"
                    "  You: 'I'm here and ready. What's on your mind?'\n\n"
                    "FORBIDDEN PATTERNS — do not do these:\n"
                    "- Do not start with 'I know you...' or 'You said...' — you don't know how they felt, "
                    "  and echoing their words back is not engagement.\n"
                    "- Do not say 'I noticed you...' about anything from earlier in the conversation. "
                    "  The current message is what matters.\n"
                    "- Do not begin with 'As an AI...' or 'I don't have information...' disclaimers.\n"
                    "- Do not give unsolicited advice, tips, or suggestions. Wait for the user to ask.\n"
                    "- Do not invent facts, statistics, rates, rules, or regulations. If asked something "
                    "factual you're not confident about, say so plainly and offer to look it up.\n\n"
                    "VOICE: Warm, direct, curious. Address the user as 'you'. Match their energy — a "
                    "four-word message gets a one-sentence reply with a question. Be brief.\n\n"
                    "Write the response only. Stop after the question mark."
                ),
                capabilities_required={
                    Capability.EMOTIONAL_INTELLIGENCE.value: CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value:  CapabilityLevel.STRONG.value,
                    Capability.BRIEF_RESPONSES.value:        CapabilityLevel.STRONG.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_REASONING],
                    ModelTier.STANDARD.value:    ["deepseek-r1:7b"],
                    ModelTier.HIGH.value:        ["deepseek-r1:14b"],
                    ModelTier.ENTERPRISE.value:  ["deepseek-r1:32b"],
                },
                scales_with=ModelTier.STANDARD.value,
                preferred_tier=ModelTier.STANDARD.value,
            ),
            "quant_architect": AgentSpec(
                agent_id="quant_architect",
                display_name="Quantitative Architect",
                purpose="Formats pre-computed financial plans and structured analysis into clean, actionable output.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.1,
                max_tokens=500,   # Synthesis model: no think chain — formats the math blueprint directly
                system_prompt=(
                    "You are LatticeD's Quantitative Architect — a confident financial strategist with a "
                    "complete budget plan already prepared for the user. The user is your client. They have "
                    "shared their financial situation. You have already done the math. Your job is to present "
                    "the plan to them in a brief, warm, professional opening paragraph that introduces the "
                    "budget table below.\n\n"
                    "WRITE LIKE THIS (these are templates — adapt the wording naturally to fit the situation):\n\n"
                    "  When no specific goal is stated:\n"
                    "  'Your income comfortably covers your fixed expenses with a meaningful surplus remaining. "
                    "The allocation below directs that surplus toward savings while leaving balanced room for "
                    "groceries, utilities, and entertainment. Holding the line on these weekly targets compounds "
                    "into real financial flexibility over time.'\n\n"
                    "  When the user is saving for a house:\n"
                    "  'You have a clear goal in front of you: saving for a house. The plan below shifts more of "
                    "your surplus into dedicated savings to support that down payment timeline. Staying disciplined "
                    "on the other categories is what gets you to closing day.'\n\n"
                    "  When the user is paying off debt:\n"
                    "  'Your focus is clear — paying off debt. The plan below redirects the bulk of your surplus "
                    "toward that payoff while preserving room for the essentials. Each month of discipline "
                    "compounds into accelerated freedom from those balances.'\n\n"
                    "  When the user is building an emergency fund:\n"
                    "  'You are building an emergency fund — the right move for financial stability. The plan "
                    "below dedicates the largest share of your surplus to that buffer while keeping the rest of "
                    "your spending balanced. A few months of this discipline gets you a meaningful safety cushion.'\n\n"
                    "VOICE: Address the user as 'you' and 'your.' The user writes their prompt in first person "
                    "('I earn, I pay') — translate that into second person ('your income, your rent') when you "
                    "reference their situation back to them. Speak as the analyst presenting to them, not as them.\n\n"
                    "THE TABLE BELOW HANDLES ALL NUMBERS. Your paragraph should describe the situation "
                    "qualitatively — words like 'comfortably,' 'meaningful surplus,' 'disciplined' work better "
                    "than dollar amounts. The table will be appended automatically right after your paragraph.\n\n"
                    "STAY ON TOPIC: Reference only the goal the user actually stated (or none, if they did not "
                    "state one). Topics like college savings, retirement accounts, IRAs, 401(k)s, 529 plans, or "
                    "insurance products should not appear unless the user specifically asked about them.\n\n"
                    "Write the paragraph (2-3 complete sentences). Stop after the last sentence."
                ),
                capabilities_required={
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
                    Capability.MATH_REASONING.value:        CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                adversarial_pair="quant_architect_explore",
                consensus_requirement=ConsensusRequirement.PAIR_AGREEMENT.value,
                minimum_models_must_agree=2,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
                    ModelTier.STANDARD.value:    ["qwen2.5-coder:7b"],
                    ModelTier.HIGH.value:        ["qwen2.5-coder:14b"],
                    ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b"],
                },
                scales_with=ModelTier.STANDARD.value,
                preferred_tier=ModelTier.HIGH.value,
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
                },
                capabilities_required={
                    Capability.NUANCED_CRITIQUE.value:      CapabilityLevel.STRONG.value,
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                adversarial_pair="quant_architect",
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_REASONING],
                    ModelTier.STANDARD.value:    ["deepseek-r1:7b"],
                    ModelTier.HIGH.value:        ["deepseek-r1:14b"],
                    ModelTier.ENTERPRISE.value:  ["deepseek-r1:32b"],
                },
                scales_with=ModelTier.HIGH.value,
                preferred_tier=ModelTier.HIGH.value,
            ),
            "life_coach": AgentSpec(
                agent_id="life_coach",
                display_name="Life Coach",
                purpose="Provides deep coaching across emotional intelligence, personal development, relationships, stress, and human growth.",
                model_name=MODEL_REASONING,
                temperature=0.55,
                max_tokens=700,
                system_prompt=(
                    "You are LatticeD — a trusted life advisor with deep expertise in emotional intelligence, "
                    "empathy, active listening, coaching, mentoring, relationship building (personal and romantic), "
                    "conflict resolution, negotiation, stress management, personal development, decision making, "
                    "creative problem solving, adaptability, cultural awareness, interpersonal skills, and lifelong learning.\n\n"
                    "Draw on conversation history to personalize your response. Identify the core emotional or "
                    "personal need behind the request and address it directly. Be a coach and mentor — not a "
                    "generic assistant. Respond with warmth, depth, and genuine care."
                ),
                capabilities_required={
                    Capability.EMOTIONAL_INTELLIGENCE.value: CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value:  CapabilityLevel.STRONG.value,
                    Capability.NUANCED_CRITIQUE.value:       CapabilityLevel.MODERATE.value,
                    Capability.REASONING.value:              CapabilityLevel.MODERATE.value,
                },
                capabilities_avoid=[Capability.BRIEF_RESPONSES.value],
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_REASONING],
                    ModelTier.STANDARD.value:    ["deepseek-r1:7b"],
                    ModelTier.HIGH.value:        ["deepseek-r1:14b"],
                    ModelTier.ENTERPRISE.value:  ["deepseek-r1:32b"],
                },
                scales_with=ModelTier.HIGH.value,
                preferred_tier=ModelTier.HIGH.value,
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
                },
                capabilities_required={
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
                    Capability.FACTUAL_RECALL.value:        CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
                    ModelTier.STANDARD.value:    ["qwen2.5-coder:7b"],
                    ModelTier.HIGH.value:        ["qwen2.5-coder:14b"],
                    ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b"],
                },
                scales_with=ModelTier.STANDARD.value,
                preferred_tier=ModelTier.STANDARD.value,
            ),
            "quant_architect_explore": AgentSpec(
                agent_id="quant_architect_explore",
                display_name="Quantitative Architect (Exploratory)",
                purpose="Exploratory architect variant — runs in parallel with the conservative variant at higher temperature to find alternative framings.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.3,
                max_tokens=500,
                system_prompt=(
                    "You are LatticeD's Quantitative Architect — a confident financial strategist with a "
                    "complete budget plan already prepared for the user. The user is your client. They have "
                    "shared their financial situation. You have already done the math. Your job is to present "
                    "the plan to them in a brief, warm, professional opening paragraph that introduces the "
                    "budget table below.\n\n"
                    "WRITE LIKE THIS (these are templates — adapt the wording naturally to fit the situation):\n\n"
                    "  When no specific goal is stated:\n"
                    "  'Your income comfortably covers your fixed expenses with a meaningful surplus remaining. "
                    "The allocation below directs that surplus toward savings while leaving balanced room for "
                    "groceries, utilities, and entertainment. Holding the line on these weekly targets compounds "
                    "into real financial flexibility over time.'\n\n"
                    "  When the user is saving for a house:\n"
                    "  'You have a clear goal in front of you: saving for a house. The plan below shifts more of "
                    "your surplus into dedicated savings to support that down payment timeline. Staying disciplined "
                    "on the other categories is what gets you to closing day.'\n\n"
                    "  When the user is paying off debt:\n"
                    "  'Your focus is clear — paying off debt. The plan below redirects the bulk of your surplus "
                    "toward that payoff while preserving room for the essentials. Each month of discipline "
                    "compounds into accelerated freedom from those balances.'\n\n"
                    "  When the user is building an emergency fund:\n"
                    "  'You are building an emergency fund — the right move for financial stability. The plan "
                    "below dedicates the largest share of your surplus to that buffer while keeping the rest of "
                    "your spending balanced. A few months of this discipline gets you a meaningful safety cushion.'\n\n"
                    "VOICE: Address the user as 'you' and 'your.' The user writes their prompt in first person "
                    "('I earn, I pay') — translate that into second person ('your income, your rent') when you "
                    "reference their situation back to them. Speak as the analyst presenting to them, not as them.\n\n"
                    "THE TABLE BELOW HANDLES ALL NUMBERS. Your paragraph should describe the situation "
                    "qualitatively — words like 'comfortably,' 'meaningful surplus,' 'disciplined' work better "
                    "than dollar amounts. The table will be appended automatically right after your paragraph.\n\n"
                    "STAY ON TOPIC: Reference only the goal the user actually stated (or none, if they did not "
                    "state one). Topics like college savings, retirement accounts, IRAs, 401(k)s, 529 plans, or "
                    "insurance products should not appear unless the user specifically asked about them.\n\n"
                    "Write the paragraph (2-3 complete sentences). Stop after the last sentence."
                ),
                capabilities_required={
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
                    Capability.MATH_REASONING.value:        CapabilityLevel.STRONG.value,
                    Capability.CREATIVE_GENERATION.value:   CapabilityLevel.MODERATE.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                },
                adversarial_pair="quant_architect",
                consensus_requirement=ConsensusRequirement.PAIR_AGREEMENT.value,
                minimum_models_must_agree=2,
                # Pool declares CROSS-FAMILY target: the conservative variant
                # uses qwen2.5-coder, so the exploratory variant should use the
                # deepseek-r1 family to satisfy the two-model adversarial
                # principle.  The current model_name=MODEL_SYNTHESIS preserves
                # bit-for-bit behavior on MINIMAL_GPU until the profile loader
                # (Sprint 0 Step 2) migrates the runtime to pool-based model
                # selection.  The profile validator (Step 4) will flag the
                # current same-family pairing as a known MINIMAL_GPU compromise.
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_REASONING],
                    ModelTier.STANDARD.value:    ["deepseek-r1:7b"],
                    ModelTier.HIGH.value:        ["deepseek-r1:14b"],
                    ModelTier.ENTERPRISE.value:  ["deepseek-r1:32b"],
                },
                scales_with=ModelTier.STANDARD.value,
                preferred_tier=ModelTier.HIGH.value,
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
                },
                capabilities_required={
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
                    Capability.FACTUAL_RECALL.value:        CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                    Capability.LONG_CONTEXT.value:          CapabilityLevel.MODERATE.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
                    ModelTier.STANDARD.value:    ["qwen2.5-coder:7b"],
                    ModelTier.HIGH.value:        ["qwen2.5-coder:14b"],
                    ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b"],
                },
                scales_with=ModelTier.STANDARD.value,
                preferred_tier=ModelTier.STANDARD.value,
            ),
            "research_synthesizer": AgentSpec(
                agent_id="research_synthesizer",
                display_name="Research Synthesizer",
                purpose="Answers factual research questions using only pre-extracted verified facts.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.1,
                max_tokens=550,
                system_prompt=(
                    "You are LatticeD's Research Synthesizer. Answer using ONLY the verified facts supplied.\n\n"
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
                ),
                capabilities_required={
                    Capability.FACTUAL_RECALL.value:        CapabilityLevel.STRONG.value,
                    Capability.REFUSAL_DISCIPLINE.value:    CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.MODERATE.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                consensus_requirement=ConsensusRequirement.TRIANGULATION_REQUIRED.value,
                minimum_models_must_agree=2,
                # Research synthesis makes factual claims with stakes — at HIGH+
                # tiers the pool intentionally includes BOTH families so the
                # triangulation pass can compare answers across model lineages.
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
                    ModelTier.STANDARD.value:    ["qwen2.5-coder:7b", "deepseek-r1:7b"],
                    ModelTier.HIGH.value:        ["qwen2.5-coder:14b", "deepseek-r1:14b"],
                    ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b", "deepseek-r1:32b", "llama3.3:70b"],
                },
                scales_with=ModelTier.HIGH.value,
                preferred_tier=ModelTier.HIGH.value,
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
                },
                capabilities_required={
                    Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
                    Capability.REFUSAL_DISCIPLINE.value:    CapabilityLevel.STRONG.value,
                    Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
                    Capability.NUANCED_CRITIQUE.value:      CapabilityLevel.MODERATE.value,
                },
                capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
                # Guardian's verdict gates user-facing output.  At HIGH+ tiers
                # this is bumped to TRIANGULATION_REQUIRED via profile override
                # (see Sprint 0 Step 5).  Default stays SINGLE_MODEL to preserve
                # MINIMAL_GPU behavior exactly.
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
                    ModelTier.STANDARD.value:    ["qwen2.5-coder:7b"],
                    ModelTier.HIGH.value:        ["qwen2.5-coder:14b", "deepseek-r1:14b"],
                    ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b", "deepseek-r1:32b"],
                },
                scales_with=ModelTier.HIGH.value,
                preferred_tier=ModelTier.HIGH.value,
            ),
            "executive_arbiter": AgentSpec(
                agent_id="executive_arbiter",
                display_name="Executive Arbiter",
                purpose="Synthesizes the final approved technical plan into a cohesive production response.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.05,
                max_tokens=800,
                system_prompt=(
                    "You are LatticeD's Executive Arbiter — skilled in communication, leadership, "
                    "adaptability, and coaching. Synthesize the approved strategy into a clear, "
                    "actionable artifact the user can immediately apply. Write with authority and warmth."
                ),
                capabilities_required={
                    Capability.INSTRUCTION_FOLLOWING.value:  CapabilityLevel.STRONG.value,
                    Capability.EMOTIONAL_INTELLIGENCE.value: CapabilityLevel.MODERATE.value,
                    Capability.STRUCTURED_OUTPUT.value:      CapabilityLevel.MODERATE.value,
                },
                consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
                model_pool_per_tier={
                    ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
                    ModelTier.STANDARD.value:    ["qwen2.5-coder:7b"],
                    ModelTier.HIGH.value:        ["qwen2.5-coder:14b", "deepseek-r1:14b"],
                    ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b", "llama3.3:70b"],
                },
                scales_with=ModelTier.HIGH.value,
                preferred_tier=ModelTier.HIGH.value,
            )
        }

    def get_agent(self, agent_id: str) -> AgentSpec:
        if agent_id not in self.registry:
            raise KeyError(f"Requested Agent ID [{agent_id}] not found in dynamic factory mapping.")
        return self.registry[agent_id]

    def manifest(self) -> list[Dict[str, Any]]:
        return [asdict(spec) for spec in self.registry.values()]

# =====================================================================
# SPRINT 0 — PROFILE LAYER, FINGERPRINTING, VALIDATOR, CONSENSUS
# =====================================================================
# This block implements Steps 2-6 of the Sprint 0 next-session list.
# All functions are inert until called — startup behavior is unchanged.
# The runtime can opt-in piece by piece without breaking MINIMAL_GPU.
#
# Public entry points:
#   hardware_profile_detect()             -> HardwareProfile         (Step 2)
#   run_behavioral_fingerprint(...)       -> {model: {axis: vec}}    (Step 3)
#   model_diversity_score(fp_a, fp_b)     -> float in [0, 1]         (Step 4)
#   validate_profile_against_agents(...)  -> ProfileValidationReport (Step 4)
#   apply_profile_overrides(profile, ...) -> None  (mutates agents)  (Step 5)
#   enforce_consensus(candidates, ...)    -> (chosen, agreed, why)   (Step 5)
#   surface_disagreement(candidates, ...) -> str                     (Step 6)
# =====================================================================

# ─── Hardware Profile ──────────────────────────────────────────────────
@dataclass
class HardwareProfile:
    """Active hardware tier configuration loaded at startup."""
    tier: str
    detected_vram_gb: float
    detected_ram_gb: float
    available_models: List[str]
    profile_path: Optional[Path]            = None
    consensus_overrides: Dict[str, str]     = field(default_factory=dict)
    notes:               List[str]          = field(default_factory=list)

# Default profiles compiled in code (used when YAML files are absent).
# YAML files in <root>/profiles/<tier>.yaml override these when present.
DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    ModelTier.MINIMAL_CPU.value: {
        "tier": ModelTier.MINIMAL_CPU.value,
        "vram_floor_gb": 0.0,
        "vram_ceiling_gb": 0.0,
        "available_models": ["bitnet-b1.58:3b", "qwen2.5-coder:1.5b-q4"],
        "consensus_overrides": {},
        "notes": [
            "CPU-only tier; expects BitNet 1.58-bit + a small quantized companion model.",
            "Two-model minimum maintained via distinct families.",
        ],
    },
    ModelTier.MINIMAL_GPU.value: {
        "tier": ModelTier.MINIMAL_GPU.value,
        "vram_floor_gb": 0.01,
        "vram_ceiling_gb": 7.99,
        "available_models": [MODEL_REASONING, MODEL_SYNTHESIS],
        "consensus_overrides": {},
        "notes": [
            "4GB-class GPUs.  Current default profile.",
            "Architect pair uses same family at runtime today; pool declarations "
            "carry the cross-family intent until pool-based selection ships.",
        ],
    },
    ModelTier.STANDARD.value: {
        "tier": ModelTier.STANDARD.value,
        "vram_floor_gb": 8.0,
        "vram_ceiling_gb": 15.99,
        "available_models": ["deepseek-r1:7b", "qwen2.5-coder:7b"],
        "consensus_overrides": {},
        "notes": ["Two distinct 7B-class families coexist in VRAM."],
    },
    ModelTier.HIGH.value: {
        "tier": ModelTier.HIGH.value,
        "vram_floor_gb": 16.0,
        "vram_ceiling_gb": 39.99,
        "available_models": ["deepseek-r1:14b", "qwen2.5-coder:14b", "llama3.3:8b"],
        "consensus_overrides": {
            "system_guardian":  ConsensusRequirement.TRIANGULATION_REQUIRED.value,
            "factual_auditor":  ConsensusRequirement.PAIR_AGREEMENT.value,
        },
        "notes": ["Three distinct model families; guardian bumped to triangulation."],
    },
    ModelTier.ENTERPRISE.value: {
        "tier": ModelTier.ENTERPRISE.value,
        "vram_floor_gb": 40.0,
        "vram_ceiling_gb": 9999.0,
        "available_models": ["deepseek-r1:32b", "qwen2.5-coder:32b", "llama3.3:70b", "mixtral:8x22b"],
        "consensus_overrides": {
            "system_guardian":       ConsensusRequirement.TRIANGULATION_REQUIRED.value,
            "factual_auditor":       ConsensusRequirement.PAIR_AGREEMENT.value,
            "research_synthesizer":  ConsensusRequirement.SUPERMAJORITY.value,
        },
        "notes": ["Four-five distinct model families; supermajority on stakes-bearing research."],
    },
    ModelTier.HYBRID.value: {
        "tier": ModelTier.HYBRID.value,
        "vram_floor_gb": 0.0,
        "vram_ceiling_gb": 9999.0,
        "available_models": ["deepseek-r1:1.5b", "qwen2.5-coder:1.5b", "remote:claude-haiku"],
        "consensus_overrides": {},
        "notes": [
            "Local + cloud-API burst with sensitivity-tag routing.",
            "Remote routes never receive PII-flagged content (gated by SensitivityRouter).",
        ],
    },
}

PROFILES_DIR = ROOT_DIR / "profiles"

def detect_vram_gb() -> float:
    """Best-effort VRAM detection via nvidia-smi.  Returns 0.0 on failure."""
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            vals = [int(x.strip()) for x in r.stdout.strip().splitlines() if x.strip().isdigit()]
            if vals:
                return max(vals) / 1024.0
    except Exception:
        pass
    return 0.0

def detect_ram_gb() -> float:
    try:
        import psutil  # optional dep
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return 0.0

def _load_yaml_override(path: Path) -> Optional[Dict[str, Any]]:
    """Optional YAML profile override.  Returns None if pyyaml unavailable."""
    if not path.exists():
        return None
    try:
        import yaml  # optional dep
    except Exception:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"profile YAML load failed for {path}: {e}")
        return None

def hardware_profile_detect(force_tier: Optional[str] = None) -> HardwareProfile:
    """
    Detect the active hardware tier and load the matching HardwareProfile.

    Tier selection ladder:
        VRAM >= 40 GB  -> ENTERPRISE
        VRAM >= 16 GB  -> HIGH
        VRAM >=  8 GB  -> STANDARD
        VRAM  >  0 GB  -> MINIMAL_GPU
        otherwise      -> MINIMAL_CPU

    Override paths:
        - force_tier argument
        - LATTICED_TIER env var
        - LATTICED_TIER set to 'hybrid' for cloud-API burst mode
    """
    env_override = os.environ.get("LATTICED_TIER", "").strip().lower()
    chosen_override = (force_tier or "").strip().lower() or env_override

    vram = detect_vram_gb()
    ram  = detect_ram_gb()

    if chosen_override and chosen_override in DEFAULT_PROFILES:
        chosen_tier = chosen_override
    elif vram >= 40.0:
        chosen_tier = ModelTier.ENTERPRISE.value
    elif vram >= 16.0:
        chosen_tier = ModelTier.HIGH.value
    elif vram >= 8.0:
        chosen_tier = ModelTier.STANDARD.value
    elif vram > 0.0:
        chosen_tier = ModelTier.MINIMAL_GPU.value
    else:
        chosen_tier = ModelTier.MINIMAL_CPU.value

    cfg = dict(DEFAULT_PROFILES.get(chosen_tier, DEFAULT_PROFILES[ModelTier.MINIMAL_GPU.value]))

    profile_path = None
    yaml_candidate = PROFILES_DIR / f"{chosen_tier}.yaml"
    yaml_data = _load_yaml_override(yaml_candidate)
    if yaml_data:
        cfg = {**cfg, **yaml_data}
        profile_path = yaml_candidate

    return HardwareProfile(
        tier=chosen_tier,
        detected_vram_gb=vram,
        detected_ram_gb=ram,
        available_models=list(cfg.get("available_models", [])),
        profile_path=profile_path,
        consensus_overrides=dict(cfg.get("consensus_overrides", {})),
        notes=list(cfg.get("notes", [])),
    )

# ─── Behavioral Fingerprinting (Sprint 0 Step 3) ───────────────────────
FINGERPRINT_CACHE_PATH = STORAGE_DIR / "model_fingerprints.json"

def _fingerprint_response_vector(response: str) -> List[float]:
    """
    Convert a model response into an 8-dim feature vector.  Pure-text
    heuristic — no embedding model required.  Captures: length, brevity,
    refusal markers, structure, hedging, numeracy, code-likeness, density.
    """
    if not response:
        return [0.0] * 8
    text = response.strip()
    words = text.split()
    n_words = max(len(words), 1)
    lo = text.lower()
    return [
        min(n_words / 100.0, 1.0),                                                                     # length (normalized)
        1.0 if n_words <= 5 else 0.0,                                                                  # very_brief
        1.0 if any(t in lo for t in ("i cannot", "i can't", "won't", "unable", "consult", "professional")) else 0.0,  # refusal
        1.0 if any(c in text for c in ("•", "- ", "1.", "2.", "* ")) else 0.0,                         # bulleted/structured
        1.0 if any(t in lo for t in ("maybe", "perhaps", "might", "could", "i think", "possibly")) else 0.0,  # hedging
        1.0 if any(c.isdigit() for c in text) else 0.0,                                                # contains_numbers
        1.0 if ("```" in text or "def " in text or "function " in text or "return " in text) else 0.0, # code-like
        sum(1 for c in text if c in ".!?") / n_words,                                                  # sentence density
    ]

async def run_behavioral_fingerprint(
    model_names: List[str],
    invoke_fn: Callable[[str, str], Awaitable[str]],
    use_cache: bool = True,
) -> Dict[str, Dict[str, List[float]]]:
    """
    Probe each model with BEHAVIORAL_FINGERPRINT_PROMPTS and produce a
    feature vector per evaluation axis.  Results are cached on disk so
    fingerprints persist across restarts.

    invoke_fn(model, prompt) is the async invoker — typically a thin
    wrapper around the Ollama client.  Unreachable models contribute
    zero-vectors rather than aborting the sweep.
    """
    cache: Dict[str, Any] = {}
    if use_cache and FINGERPRINT_CACHE_PATH.exists():
        try:
            cache = json.loads(FINGERPRINT_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    out: Dict[str, Dict[str, List[float]]] = {}
    for model in model_names:
        if use_cache and model in cache:
            out[model] = cache[model]
            continue
        axis_vectors: Dict[str, List[float]] = {}
        for prompt, axis in BEHAVIORAL_FINGERPRINT_PROMPTS:
            try:
                resp = await invoke_fn(model, prompt)
            except Exception as e:
                logger.warning(f"fingerprint probe failed for {model} / {axis}: {e}")
                resp = ""
            axis_vectors.setdefault(axis, [])
            axis_vectors[axis].extend(_fingerprint_response_vector(resp))
        out[model] = axis_vectors

    try:
        FINGERPRINT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        merged = {**cache, **out}
        FINGERPRINT_CACHE_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"failed to persist fingerprint cache: {e}")
    return out

def model_diversity_score(
    fp_a: Dict[str, List[float]],
    fp_b: Dict[str, List[float]],
) -> float:
    """
    Cosine distance between two fingerprints, averaged across shared axes.
    1.0 = totally different behavior; 0.0 = identical.  Pairs below
    MODEL_DIVERSITY_MIN are flagged as behaviorally too similar to act
    as a valid adversarial pair.
    """
    axes = sorted(set(fp_a.keys()) & set(fp_b.keys()))
    if not axes:
        return 0.0
    dists: List[float] = []
    for axis in axes:
        va = fp_a.get(axis) or []
        vb = fp_b.get(axis) or []
        L = min(len(va), len(vb))
        if L == 0:
            continue
        va, vb = va[:L], vb[:L]
        dot = sum(x * y for x, y in zip(va, vb))
        na  = math.sqrt(sum(x * x for x in va))
        nb  = math.sqrt(sum(y * y for y in vb))
        if na == 0.0 or nb == 0.0:
            continue
        dists.append(1.0 - (dot / (na * nb)))
    return (sum(dists) / len(dists)) if dists else 0.0

# ─── Profile Validator (Sprint 0 Step 4) ───────────────────────────────
@dataclass
class ProfileValidationReport:
    valid:    bool
    errors:   List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes:    List[str] = field(default_factory=list)

    def summary(self) -> str:
        head = "VALID" if self.valid else "INVALID"
        bits = [f"profile validation: {head}"]
        for e in self.errors:   bits.append(f"  ERR: {e}")
        for w in self.warnings: bits.append(f"  WARN: {w}")
        for n in self.notes:    bits.append(f"  note: {n}")
        return "\n".join(bits)

def _model_family(model_name: str) -> str:
    """Map a model identifier to a coarse family bucket."""
    n = (model_name or "").lower()
    for fam in (
        "deepseek-r1", "deepseek",
        "qwen2.5-coder", "qwen",
        "llama3.3", "llama",
        "mixtral", "mistral",
        "bitnet", "phi",
        "remote",          # cloud-API stand-in
    ):
        if fam in n:
            return fam
    return n.split(":", 1)[0]

def validate_profile_against_agents(
    profile: HardwareProfile,
    agents: Dict[str, AgentSpec],
    fingerprints: Optional[Dict[str, Dict[str, List[float]]]] = None,
    strict: bool = True,
) -> ProfileValidationReport:
    """
    Enforce the two-model-minimum and adversarial-diversity principles
    on a profile + agent registry.  Returns a structured report instead
    of raising — the caller decides whether to abort.

    Checks performed:
      1. Profile offers >= 2 distinct model families.
      2. Each adversarial pair resolves to different families at this tier
         (warning, not error, on MINIMAL_GPU — documented compromise).
      3. Fingerprint diversity above MODEL_DIVERSITY_MIN (when fingerprints
         are provided).
      4. Every agent's consensus_requirement is satisfiable at this tier.
    """
    rep = ProfileValidationReport(valid=True)

    # 1. Two-model minimum
    fams = {_model_family(m) for m in profile.available_models}
    if len(fams) < 2:
        msg = (f"Profile '{profile.tier}' offers only {len(fams)} model family "
               f"({sorted(fams)}) — two-model minimum violated.")
        if strict:
            rep.errors.append(msg)
            rep.valid = False
        else:
            rep.warnings.append(msg)

    # 2. Adversarial pair family diversity
    seen_pairs: set = set()
    for aid, spec in agents.items():
        if not spec.adversarial_pair:
            continue
        partner = agents.get(spec.adversarial_pair)
        if not partner:
            rep.warnings.append(
                f"Agent '{aid}' declares adversarial_pair='{spec.adversarial_pair}' but partner not in registry."
            )
            continue
        key = tuple(sorted([aid, spec.adversarial_pair]))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        pool_a = spec.model_pool_per_tier.get(profile.tier)    or [spec.model_name]
        pool_b = partner.model_pool_per_tier.get(profile.tier) or [partner.model_name]
        fams_a = {_model_family(m) for m in pool_a}
        fams_b = {_model_family(m) for m in pool_b}

        if fams_a & fams_b and len(fams_a) == 1 and len(fams_b) == 1:
            msg = (f"Adversarial pair '{aid}' <-> '{spec.adversarial_pair}' resolves to the same "
                   f"model family ({sorted(fams_a)}) at tier '{profile.tier}' — not a real adversary.")
            if profile.tier == ModelTier.MINIMAL_GPU.value:
                rep.warnings.append(
                    msg + " [MINIMAL_GPU documented compromise: pool declares cross-family target.]"
                )
            else:
                rep.errors.append(msg)
                rep.valid = False

    # 3. Fingerprint diversity
    if fingerprints:
        for i, m1 in enumerate(profile.available_models):
            for m2 in profile.available_models[i + 1:]:
                fp1 = fingerprints.get(m1)
                fp2 = fingerprints.get(m2)
                if not fp1 or not fp2:
                    continue
                score = model_diversity_score(fp1, fp2)
                if score < MODEL_DIVERSITY_MIN:
                    rep.warnings.append(
                        f"Models '{m1}' and '{m2}' fingerprint diversity {score:.3f} "
                        f"< MODEL_DIVERSITY_MIN ({MODEL_DIVERSITY_MIN}) — behaviorally similar."
                    )

    # 4. Consensus satisfiability
    n_fams = max(len(fams), 1)
    need_map = {
        ConsensusRequirement.SINGLE_MODEL.value:           1,
        ConsensusRequirement.PAIR_AGREEMENT.value:         2,
        ConsensusRequirement.TRIANGULATION_REQUIRED.value: 3,
        ConsensusRequirement.SUPERMAJORITY.value:          3,
        ConsensusRequirement.SURFACE_DISAGREEMENT.value:   2,
    }
    for aid, spec in agents.items():
        # consensus overrides may have raised the bar at this tier
        effective = profile.consensus_overrides.get(aid, spec.consensus_requirement)
        need = need_map.get(effective, 1)
        if need > n_fams:
            rep.warnings.append(
                f"Agent '{aid}' requires '{effective}' (needs {need} families) "
                f"but profile '{profile.tier}' has {n_fams}."
            )

    if rep.valid and not rep.errors:
        rep.notes.append(
            f"Profile '{profile.tier}': {len(fams)} families, "
            f"{len(seen_pairs)} adversarial pair(s) checked."
        )
    return rep

# ─── Consensus Helpers (Sprint 0 Step 5) ───────────────────────────────
def apply_profile_overrides(profile: HardwareProfile, agents: Dict[str, AgentSpec]) -> None:
    """Mutate agents in-place with the profile's per-tier consensus overrides."""
    for aid, new_req in (profile.consensus_overrides or {}).items():
        if aid in agents:
            agents[aid].consensus_requirement = new_req

def _normalize_for_compare(s: str) -> str:
    return " ".join((s or "").lower().split())

def enforce_consensus(
    candidates: List[str],
    requirement: str,
    minimum_must_agree: int = 1,
) -> Tuple[str, bool, str]:
    """
    Reconcile N candidate outputs into a single choice.
    Returns (chosen_output, consensus_reached, disagreement_summary).

    Semantics:
      SINGLE_MODEL                -> return first candidate (always agreed).
      PAIR_AGREEMENT              -> >= 2 candidates with same normalized text.
      TRIANGULATION_REQUIRED      -> >= 3 candidates agree.
      SUPERMAJORITY               -> >= ceil(0.6 * N) candidates agree.
      SURFACE_DISAGREEMENT        -> never silently chooses; consensus_reached
                                     is False whenever candidates disagree.

    When the bar is not met the longest candidate is returned with
    consensus_reached=False so the caller can format a disagreement-
    surfacing response (see surface_disagreement).
    """
    candidates = [c for c in candidates if c is not None]
    if not candidates:
        return "", False, "no candidates"
    if requirement == ConsensusRequirement.SINGLE_MODEL.value or len(candidates) == 1:
        return candidates[0], True, ""

    buckets: Dict[str, List[int]] = {}
    for i, c in enumerate(candidates):
        buckets.setdefault(_normalize_for_compare(c), []).append(i)

    largest_key  = max(buckets, key=lambda k: len(buckets[k]))
    largest_size = len(buckets[largest_key])

    threshold = {
        ConsensusRequirement.PAIR_AGREEMENT.value:         2,
        ConsensusRequirement.TRIANGULATION_REQUIRED.value: 3,
        ConsensusRequirement.SUPERMAJORITY.value:          math.ceil(len(candidates) * 0.6),
        ConsensusRequirement.SURFACE_DISAGREEMENT.value:   len(candidates),  # require unanimity
    }.get(requirement, max(minimum_must_agree, 1))

    if largest_size >= threshold:
        return candidates[buckets[largest_key][0]], True, ""

    chosen  = max(candidates, key=len)
    summary = (f"{len(buckets)} distinct outputs from {len(candidates)} models; "
               f"largest cluster {largest_size}/{threshold} required.")
    return chosen, False, summary

def surface_disagreement(
    candidates: List[Tuple[str, str]],
    header: str = "Models disagreed on this response. Both versions are shown so you can judge:",
) -> str:
    """
    Format competing outputs as a single user-facing message that exposes
    rather than hides the disagreement.
    candidates = [(model_name, output_text), ...]
    """
    if not candidates:
        return ""
    lines = [header]
    for model, text in candidates:
        lines.append(f"\n--- {model} ---\n{(text or '').strip()}")
    lines.append("\n--- end ---")
    lines.append("Treat any specific numbers, dates, or rules as unverified until cross-checked.")
    return "\n".join(lines)

# =====================================================================
# SPRINT 1 — PERSISTENT IDENTITY FOUNDATION + PRIVACY SEEDS
# =====================================================================
# A higher layer above the SQLite belief_graph: structured, versioned,
# sensitivity-tagged identity state that survives across sessions and
# answers "who is this user?" with explicit categories, not embeddings.
#
# Architecture:
#   LifeDomain     — 8 explicit life domains, plus UNCATEGORIZED.
#   Sensitivity    — 4 levels gating where data may travel.
#   IdentityFact   — single attested claim about the user.
#   NorthStar      — long-horizon value/goal that anchors agent voice.
#   ConstitutionalRule — user-written behavior anchor (always honored).
#   IdentityDocument   — the persistent identity blob, versioned.
#   IdentityStore  — load/save JSON to runtime/storage/identity.json.
#   SensitivityRouter  — gates outbound calls by tag (HIGH+ never leaves
#                        the local machine; the MCP / cloud-burst layer
#                        consults this router before egress).
#
# Public entry points (all inert until called):
#   IdentityStore.load() / .save()
#   IdentityStore.add_fact(...) / add_north_star(...) / add_rule(...)
#   IdentityStore.facts_for_domain(domain)
#   SensitivityRouter.allow_egress(tag, destination)
#   SensitivityRouter.classify_text(text)            — heuristic seed
#   biographer agent is registered in AgentFactoryRegistry but NOT
#   wired into the pipeline yet (Sprint 3 lights it up).
# =====================================================================

# ─── Life Domains ──────────────────────────────────────────────────────
class LifeDomain(str, Enum):
    """
    The 8 explicit life domains LatticeD tracks per user, plus a fallback
    UNCATEGORIZED bucket.  Used to organize identity facts, north stars,
    and reflection prompts.
    """
    CAREER        = "career"        # employment, role, professional trajectory
    BUSINESS      = "business"      # ownership, ventures, products (distinct from Career)
    FINANCIAL     = "financial"     # income, debt, savings, allocation goals
    HEALTH        = "health"        # physical, mental, sleep, nutrition, fitness
    RELATIONSHIPS = "relationships" # family, partner, friends, social fabric
    GROWTH        = "growth"        # learning, skills, personal development
    LIFESTYLE     = "lifestyle"     # hobbies, leisure, travel, daily texture
    SPIRITUAL     = "spiritual"     # values, meaning, faith, philosophy
    UNCATEGORIZED = "uncategorized"

# Lightweight keyword cues used by classify_domain().  Hybrid signal: any
# semantic embedding pipeline (Chroma) can override at runtime; this is
# the deterministic baseline that works without one.
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    LifeDomain.CAREER.value:        ["job", "boss", "career", "promotion", "raise", "interview", "resume", "coworker", "work as", "designer", "engineer", "manager", "agency", "office", "team"],
    LifeDomain.BUSINESS.value:      ["company", "startup", "client", "revenue", "product", "founder", "launch", "customer", "ltd", "llc"],
    LifeDomain.FINANCIAL.value:     ["budget", "savings", "debt", "rent", "mortgage", "401k", "ira", "invest", "expense", "income", "loan", "salary", "paycheck", "afford", "$"],
    LifeDomain.HEALTH.value:        ["sleep", "exercise", "doctor", "diet", "stress", "anxiety", "tired", "workout", "work out", "weight", "therapy", "gym", "run", "fitness"],
    LifeDomain.RELATIONSHIPS.value: ["wife", "husband", "partner", "girlfriend", "boyfriend", "friend", "mother", "father", "kid", "child", "family", "brother", "sister"],
    LifeDomain.GROWTH.value:        ["learn", "study", "course", "book", "skill", "practice", "habit", "improve", "growth"],
    LifeDomain.LIFESTYLE.value:     ["hobby", "travel", "vacation", "weekend", "park", "music", "movie", "game", "cook", "garden"],
    LifeDomain.SPIRITUAL.value:     ["faith", "pray", "meditate", "purpose", "meaning", "values", "belief", "soul", "spirit"],
}

def classify_domain(text: str) -> str:
    """
    Deterministic keyword-based domain classifier.  Returns the
    LifeDomain value with the most keyword hits; ties broken by domain
    order.  Returns UNCATEGORIZED if no signal.
    """
    if not text:
        return LifeDomain.UNCATEGORIZED.value
    lo = text.lower()
    scores: Dict[str, int] = {}
    for dom, kws in DOMAIN_KEYWORDS.items():
        s = sum(1 for kw in kws if kw in lo)
        if s > 0:
            scores[dom] = s
    if not scores:
        return LifeDomain.UNCATEGORIZED.value
    return max(scores.items(), key=lambda kv: (kv[1], -list(DOMAIN_KEYWORDS).index(kv[0])))[0]

# ─── Sensitivity Levels (Privacy Seeds) ────────────────────────────────
class Sensitivity(str, Enum):
    """
    Where a piece of data is allowed to travel.

    LOW    — fine to send to any remote API (e.g., weather, public facts).
    MEDIUM — local-by-default; allowed to remote endpoints behind explicit
             user-consented routes.
    HIGH   — must stay on the user's local machine.  Cloud-API burst path
             refuses to embed or transmit HIGH content.
    SECRET — never written to disk in plaintext; never embedded; never
             logged.  Held in memory only during the active turn.
    """
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"
    SECRET = "secret"

# Heuristic patterns the SensitivityRouter uses to seed-tag incoming text
# when no explicit tag is provided.  Conservative on purpose: false-high
# is preferable to false-low for personal data.
_SENSITIVITY_PATTERNS_SECRET: List[str] = [
    r"\bpassword\b", r"\bpasscode\b", r"\bapi[_ -]?key\b",
    r"\bprivate[_ ]?key\b", r"\bsecret[_ ]?key\b", r"\baccess[_ ]?token\b",
]
_SENSITIVITY_PATTERNS_HIGH: List[str] = [
    r"\bssn\b", r"\bsocial security\b", r"\b\d{3}-\d{2}-\d{4}\b",            # SSN
    r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",                              # credit card-ish
    r"\bpin\b",
    r"\bmedical\b", r"\bdiagnos(is|ed)\b", r"\bprescription\b", r"\bdosage\b",
    r"\btherapist\b", r"\bsuicid", r"\bself[- ]harm\b",
]
_SENSITIVITY_PATTERNS_MEDIUM: List[str] = [
    r"\bsalary\b", r"\bincome\b", r"\bnet worth\b", r"\bdebt\b", r"\bmortgage\b",
    r"\bemail\b", r"\bphone number\b", r"\baddress\b",
    r"\bwife\b", r"\bhusband\b", r"\bpartner\b", r"\bgirlfriend\b", r"\bboyfriend\b",
    r"\bkids?\b", r"\bchildren\b", r"\bfamily\b",
]

# ─── Identity Data Structures ──────────────────────────────────────────
IDENTITY_SCHEMA_VERSION = 1

@dataclass
class IdentityFact:
    """A single attested claim about the user."""
    text: str
    domain: str                           = LifeDomain.UNCATEGORIZED.value
    sensitivity: str                      = Sensitivity.MEDIUM.value
    confidence: float                     = 0.7
    source: str                           = "user_stated"      # user_stated | inferred | imported
    first_seen: float                     = field(default_factory=lambda: time.time())
    last_seen:  float                     = field(default_factory=lambda: time.time())
    seen_count: int                       = 1
    metadata:   Dict[str, Any]            = field(default_factory=dict)

@dataclass
class NorthStar:
    """
    A long-horizon value or goal that anchors agent voice across all
    sessions.  Examples: 'be a present father', 'financial independence
    by 50', 'always tell the truth even when it costs me'.
    """
    text: str
    domain: str                           = LifeDomain.UNCATEGORIZED.value
    weight: float                         = 1.0     # 0.0..2.0 — informs influence
    created: float                        = field(default_factory=lambda: time.time())
    last_referenced: Optional[float]      = None
    metadata: Dict[str, Any]              = field(default_factory=dict)

@dataclass
class ConstitutionalRule:
    """
    A user-written behavior rule the framework MUST honor.  Constitutional
    rules outrank inferred preferences, agent suggestions, and even the
    Identity Document's own facts when in conflict.
    """
    text: str
    priority: int                         = 100    # higher = stronger
    created: float                        = field(default_factory=lambda: time.time())
    metadata: Dict[str, Any]              = field(default_factory=dict)

@dataclass
class IdentityDocument:
    """The persistent identity blob — versioned, JSON-serializable."""
    schema_version: int                                     = IDENTITY_SCHEMA_VERSION
    user_id: str                                            = "local"
    created: float                                          = field(default_factory=lambda: time.time())
    updated: float                                          = field(default_factory=lambda: time.time())
    facts: List[IdentityFact]                               = field(default_factory=list)
    north_stars: List[NorthStar]                            = field(default_factory=list)
    constitutional_rules: List[ConstitutionalRule]          = field(default_factory=list)
    domain_summaries: Dict[str, str]                        = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    @classmethod
    def from_json(cls, raw: str) -> "IdentityDocument":
        data = json.loads(raw)
        return cls(
            schema_version=int(data.get("schema_version", IDENTITY_SCHEMA_VERSION)),
            user_id=str(data.get("user_id", "local")),
            created=float(data.get("created", time.time())),
            updated=float(data.get("updated", time.time())),
            facts=[IdentityFact(**f) for f in data.get("facts", [])],
            north_stars=[NorthStar(**n) for n in data.get("north_stars", [])],
            constitutional_rules=[ConstitutionalRule(**r) for r in data.get("constitutional_rules", [])],
            domain_summaries=dict(data.get("domain_summaries", {})),
        )

IDENTITY_PATH = STORAGE_DIR / "identity.json"

class IdentityStore:
    """
    Persistent identity layer.  Wraps an IdentityDocument with disk-backed
    save / load and convenient mutation methods.  All writes are atomic
    (tmp file + rename) so a crash during save never corrupts state.
    """
    def __init__(self, path: Path = IDENTITY_PATH, user_id: str = "local") -> None:
        self.path = path
        self.doc  = IdentityDocument(user_id=user_id)

    # ----- lifecycle -----
    def load(self) -> "IdentityStore":
        if self.path.exists():
            try:
                self.doc = IdentityDocument.from_json(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"identity load failed at {self.path}: {e}")
        return self

    def save(self) -> None:
        self.doc.updated = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(self.doc.to_json(), encoding="utf-8")
        os.replace(tmp, self.path)

    # ----- facts -----
    def add_fact(
        self,
        text: str,
        domain: Optional[str] = None,
        sensitivity: Optional[str] = None,
        confidence: float = 0.7,
        source: str = "user_stated",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IdentityFact:
        dom = domain or classify_domain(text)
        sens = sensitivity or SensitivityRouter.classify_text(text)
        # Dedupe by normalized text.
        norm = " ".join(text.lower().split())
        for f in self.doc.facts:
            if " ".join(f.text.lower().split()) == norm:
                f.seen_count += 1
                f.last_seen = time.time()
                f.confidence = min(1.0, f.confidence + 0.05)
                return f
        fact = IdentityFact(
            text=text, domain=dom, sensitivity=sens,
            confidence=confidence, source=source,
            metadata=metadata or {},
        )
        self.doc.facts.append(fact)
        return fact

    def facts_for_domain(self, domain: str) -> List[IdentityFact]:
        return [f for f in self.doc.facts if f.domain == domain]

    def facts_above_sensitivity(self, level: str) -> List[IdentityFact]:
        order = {s.value: i for i, s in enumerate([
            Sensitivity.LOW, Sensitivity.MEDIUM, Sensitivity.HIGH, Sensitivity.SECRET
        ])}
        threshold = order.get(level, 1)
        return [f for f in self.doc.facts if order.get(f.sensitivity, 1) >= threshold]

    # ----- north stars -----
    def add_north_star(
        self, text: str, domain: Optional[str] = None, weight: float = 1.0,
    ) -> NorthStar:
        ns = NorthStar(text=text, domain=domain or classify_domain(text), weight=weight)
        self.doc.north_stars.append(ns)
        return ns

    def active_north_stars(self) -> List[NorthStar]:
        return sorted(self.doc.north_stars, key=lambda n: -n.weight)

    # ----- constitutional rules -----
    def add_rule(self, text: str, priority: int = 100) -> ConstitutionalRule:
        rule = ConstitutionalRule(text=text, priority=priority)
        self.doc.constitutional_rules.append(rule)
        return rule

    def active_rules(self) -> List[ConstitutionalRule]:
        return sorted(self.doc.constitutional_rules, key=lambda r: -r.priority)

# ─── Sensitivity Router (Privacy Seeds) ────────────────────────────────
class SensitivityRouter:
    """
    Decides what may leave the local machine.

    classify_text(text) -> Sensitivity   (heuristic seed)
    allow_egress(tag, destination)       (gate before any outbound call)

    Destination semantics:
      'local'         — always allowed.
      'remote_api'    — generic third-party endpoint (cloud LLM, web).
      'public_search' — search engine queries; never carry HIGH/SECRET.
      'user_export'   — exports created at explicit user request; SECRET
                        is still blocked, HIGH triggers a confirmation.
    """

    @staticmethod
    def classify_text(text: str) -> str:
        if not text:
            return Sensitivity.LOW.value
        lo = text.lower()
        for pat in _SENSITIVITY_PATTERNS_SECRET:
            if re.search(pat, lo):
                return Sensitivity.SECRET.value
        for pat in _SENSITIVITY_PATTERNS_HIGH:
            if re.search(pat, lo):
                return Sensitivity.HIGH.value
        for pat in _SENSITIVITY_PATTERNS_MEDIUM:
            if re.search(pat, lo):
                return Sensitivity.MEDIUM.value
        return Sensitivity.LOW.value

    @staticmethod
    def allow_egress(tag: str, destination: str) -> Tuple[bool, str]:
        """
        Returns (allowed, reason).  reason is a short string for logging
        and for surfacing to the user when blocked.
        """
        dest = (destination or "").strip().lower()
        if dest == "local":
            return True, "local destination always allowed"
        if tag == Sensitivity.SECRET.value:
            return False, "SECRET content is never permitted to leave the local machine"
        if tag == Sensitivity.HIGH.value:
            if dest == "user_export":
                return True, "HIGH allowed to user_export with confirmation"
            return False, f"HIGH content is not permitted to egress to '{dest}'"
        if tag == Sensitivity.MEDIUM.value:
            if dest in ("remote_api", "user_export"):
                return True, "MEDIUM allowed to user-consented routes"
            if dest == "public_search":
                return False, "MEDIUM content is not allowed in public search queries"
        return True, "LOW content cleared for egress"

# ─── Biographer Agent (declared, not yet wired) ────────────────────────
# Registered on AgentFactoryRegistry construction below.  Sprint 3 will
# wire this into a passive background extraction step that runs after
# user turns.  Until then it sits in the registry as available metadata
# and is harmless.
BIOGRAPHER_AGENT_SPEC: Optional["AgentSpec"] = None  # populated lazily below

def _build_biographer_spec() -> "AgentSpec":
    return AgentSpec(
        agent_id="biographer",
        display_name="Biographer",
        purpose="Extracts durable identity facts, domain assignments, and sensitivity tags from user turns for the Identity Document.",
        model_name=MODEL_SYNTHESIS,
        temperature=0.0,
        max_tokens=200,
        system_prompt=(
            "You are LatticeD's Biographer. Given a user message, extract zero or more "
            "DURABLE facts about the user (their situation, preferences, relationships, "
            "values, or goals). For each fact emit: text, domain (career, business, "
            "financial, health, relationships, growth, lifestyle, spiritual, "
            "uncategorized), sensitivity (low, medium, high, secret), confidence (0-1). "
            "Do NOT extract transient facts (today's weather, what they ate for lunch). "
            "Do NOT invent facts the user did not state. If nothing durable was said, "
            "return an empty list."
        ),
        output_schema={
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text":        {"type": "string"},
                            "domain":      {"type": "string"},
                            "sensitivity": {"type": "string"},
                            "confidence":  {"type": "number"},
                        },
                        "required": ["text"],
                    },
                    "maxItems": 5,
                }
            },
            "required": ["facts"],
        },
        capabilities_required={
            Capability.STRUCTURED_OUTPUT.value:     CapabilityLevel.STRONG.value,
            Capability.INSTRUCTION_FOLLOWING.value: CapabilityLevel.STRONG.value,
            Capability.NUANCED_CRITIQUE.value:      CapabilityLevel.MODERATE.value,
        },
        capabilities_avoid=[Capability.CREATIVE_GENERATION.value],
        consensus_requirement=ConsensusRequirement.SINGLE_MODEL.value,
        model_pool_per_tier={
            ModelTier.MINIMAL_GPU.value: [MODEL_SYNTHESIS],
            ModelTier.STANDARD.value:    ["qwen2.5-coder:7b"],
            ModelTier.HIGH.value:        ["qwen2.5-coder:14b"],
            ModelTier.ENTERPRISE.value:  ["qwen2.5-coder:32b"],
        },
        scales_with=ModelTier.STANDARD.value,
        preferred_tier=ModelTier.STANDARD.value,
    )

# Register the biographer on the AgentFactoryRegistry — done by patching
# the registry dict on instantiation rather than touching the class body.
_OriginalAgentFactoryRegistryInit = AgentFactoryRegistry.__init__

def _patched_agent_factory_init(self):
    _OriginalAgentFactoryRegistryInit(self)
    if "biographer" not in self.registry:
        self.registry["biographer"] = _build_biographer_spec()

AgentFactoryRegistry.__init__ = _patched_agent_factory_init  # type: ignore[method-assign]

# =====================================================================
# SPRINT 2 — CURIOSITY ENGINE (INFORMATION-THEORETIC)
# =====================================================================
# The system's active learner.  Reads gaps in the IdentityDocument and
# proposes questions whose expected information gain about the user is
# highest, with a strict budget so the user never feels surveyed.
#
# Architecture:
#   GapType                 — taxonomy of identity ambiguity
#   IdentityGap             — one detected gap with a score
#   CuriosityEngagement     — one asked question + outcome
#   EngagementLedger        — persistent record of asked questions and
#                             response rates per domain
#   CuriosityEngine         — gap detection, information-gain scoring,
#                             question selection under a session budget
#
# Information-theoretic framing:
#   For each domain D with N facts of average confidence c, define
#     uncertainty(D) = 1 / (N * c + 0.5)
#     H(D) = log2(1 + uncertainty(D))
#   Answering a well-targeted question moves us to (N+1, c+epsilon).
#   Expected information gain = H_before - H_after.  This is the
#   InfoPO-inspired objective the engine maximizes when choosing the
#   next question to ask.
#
# Budget:
#   Default 1 active outstanding curiosity question per hour.  No more
#   than 3 questions per 24h regardless of gap pressure.  Configurable
#   via CuriosityEngine(max_per_hour, max_per_day).
#
# Engagement signal:
#   record_response(answered, response_excerpt) updates the ledger so
#   the engine can learn which domains the user engages with vs which
#   they skip — future sprints can shape question phrasing per domain
#   based on observed answer rate.
# =====================================================================

# ─── Taxonomy ──────────────────────────────────────────────────────────
class GapType(str, Enum):
    LOW_COVERAGE   = "low_coverage"     # fewer than COVERAGE_FLOOR facts in domain
    LOW_CONFIDENCE = "low_confidence"   # average confidence in domain below 0.55
    CONFLICTING    = "conflicting"      # facts contain contradictory keywords
    NO_NORTH_STAR  = "no_north_star"    # active in domain but no anchoring goal
    STALE_DOMAIN   = "stale_domain"     # last_seen > STALE_DAYS ago

# Tunables
COVERAGE_FLOOR    = 3
CONFIDENCE_FLOOR  = 0.55
STALE_DAYS        = 30.0

# Question templates per (domain, gap_type).  Short, friend-tone, never
# clinical.  Templates chosen on a single axis so the engine can reason
# about expected information gain without LLM lookups (deterministic
# baseline; later sprints can layer LLM-generated variants on top).
_TEMPLATES_LOW_COVERAGE: Dict[str, List[str]] = {
    LifeDomain.CAREER.value:        ["What do you do for work these days?", "What part of your job energizes you most?"],
    LifeDomain.BUSINESS.value:      ["Are you running anything of your own — side project, business, anything?", "What's the current shape of your business?"],
    LifeDomain.FINANCIAL.value:     ["What's the single biggest money question on your mind right now?", "How would you describe your current financial situation in one line?"],
    LifeDomain.HEALTH.value:        ["How have you been feeling physically lately?", "What's your relationship with sleep right now?"],
    LifeDomain.RELATIONSHIPS.value: ["Who are the few people closest to you right now?", "Who do you turn to when things get hard?"],
    LifeDomain.GROWTH.value:        ["What are you learning or working on improving lately?", "If you could be sharper at one skill in six months, what would it be?"],
    LifeDomain.LIFESTYLE.value:     ["What does a good week look like for you?", "What do you do when you actually get free time?"],
    LifeDomain.SPIRITUAL.value:     ["What gives your week meaning beyond the daily grind?", "When you think about why you do what you do, what comes up?"],
}
_TEMPLATES_LOW_CONFIDENCE: Dict[str, List[str]] = {
    d: [f"Can I check something I think I heard from you — does this still feel accurate for your {d}?"]
    for d in [m.value for m in LifeDomain if m != LifeDomain.UNCATEGORIZED]
}
_TEMPLATES_NO_NORTH_STAR: Dict[str, List[str]] = {
    d: [f"If you could pick one thing you want to be true about your {d} a year from now, what would it be?"]
    for d in [m.value for m in LifeDomain if m != LifeDomain.UNCATEGORIZED]
}
_TEMPLATES_STALE: Dict[str, List[str]] = {
    d: [f"It's been a while since we talked about your {d} — anything moving there?"]
    for d in [m.value for m in LifeDomain if m != LifeDomain.UNCATEGORIZED]
}
_TEMPLATES_CONFLICTING: Dict[str, List[str]] = {
    d: [f"I'm holding two things about your {d} that don't quite line up — can I read them back to make sure I have it right?"]
    for d in [m.value for m in LifeDomain if m != LifeDomain.UNCATEGORIZED]
}

QUESTION_TEMPLATES: Dict[Tuple[str, str], List[str]] = {}
for _domain, _qs in _TEMPLATES_LOW_COVERAGE.items():
    QUESTION_TEMPLATES[(_domain, GapType.LOW_COVERAGE.value)] = _qs
for _domain, _qs in _TEMPLATES_LOW_CONFIDENCE.items():
    QUESTION_TEMPLATES[(_domain, GapType.LOW_CONFIDENCE.value)] = _qs
for _domain, _qs in _TEMPLATES_NO_NORTH_STAR.items():
    QUESTION_TEMPLATES[(_domain, GapType.NO_NORTH_STAR.value)] = _qs
for _domain, _qs in _TEMPLATES_STALE.items():
    QUESTION_TEMPLATES[(_domain, GapType.STALE_DOMAIN.value)] = _qs
for _domain, _qs in _TEMPLATES_CONFLICTING.items():
    QUESTION_TEMPLATES[(_domain, GapType.CONFLICTING.value)] = _qs

# ─── Data structures ───────────────────────────────────────────────────
@dataclass
class IdentityGap:
    domain: str
    gap_type: str
    score: float                                  # 0..1, higher = more uncertainty
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CuriosityEngagement:
    question: str
    domain: str
    gap_type: str
    asked_at: float                               = field(default_factory=lambda: time.time())
    answered: Optional[bool]                      = None
    answered_at: Optional[float]                  = None
    response_excerpt: Optional[str]               = None
    expected_information_gain: float              = 0.0
    metadata: Dict[str, Any]                      = field(default_factory=dict)

CURIOSITY_PATH = STORAGE_DIR / "curiosity.json"

class EngagementLedger:
    """
    Persistent record of curiosity engagements.  JSON on disk so the
    engine remembers across restarts what it has already asked and what
    the user actually engaged with.
    """
    def __init__(self, path: Path = CURIOSITY_PATH) -> None:
        self.path: Path = path
        self.entries: List[CuriosityEngagement] = []

    def load(self) -> "EngagementLedger":
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.entries = [CuriosityEngagement(**e) for e in data.get("entries", [])]
            except Exception as e:
                logger.warning(f"engagement ledger load failed at {self.path}: {e}")
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [asdict(e) for e in self.entries]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, entry: CuriosityEngagement) -> None:
        self.entries.append(entry)

    def already_asked(self, question: str) -> bool:
        norm = " ".join((question or "").lower().split())
        return any(" ".join(e.question.lower().split()) == norm for e in self.entries)

    def recent_in_window(self, window_seconds: float) -> List[CuriosityEngagement]:
        cutoff = time.time() - window_seconds
        return [e for e in self.entries if e.asked_at >= cutoff]

    def response_rate(self, domain: Optional[str] = None) -> float:
        """
        Fraction of asked questions that received a response.
        None for domain = global rate; otherwise per-domain.
        """
        pool = [e for e in self.entries if (domain is None or e.domain == domain)]
        if not pool:
            return 0.0
        answered = sum(1 for e in pool if e.answered)
        return answered / len(pool)

# ─── Curiosity Engine ──────────────────────────────────────────────────
class CuriosityEngine:
    """
    Detects identity gaps and selects the highest-expected-gain question
    under a per-session budget.

    Inputs:
        store           IdentityStore — gap oracle
        ledger          EngagementLedger — what we've already asked
        max_per_hour    soft cap on outstanding questions (default 1)
        max_per_day     hard cap regardless of pressure (default 3)
    """

    def __init__(
        self,
        store: "IdentityStore",
        ledger: Optional["EngagementLedger"] = None,
        max_per_hour: int = 1,
        max_per_day: int  = 3,
    ) -> None:
        self.store        = store
        self.ledger       = ledger or EngagementLedger()
        self.max_per_hour = max_per_hour
        self.max_per_day  = max_per_day

    # ----- gap detection -----
    def detect_gaps(self) -> List[IdentityGap]:
        gaps: List[IdentityGap] = []
        now = time.time()
        for domain_enum in LifeDomain:
            domain = domain_enum.value
            if domain == LifeDomain.UNCATEGORIZED.value:
                continue
            facts = self.store.facts_for_domain(domain)
            n = len(facts)

            # Coverage
            if n < COVERAGE_FLOOR:
                score = 1.0 - (n / COVERAGE_FLOOR)
                gaps.append(IdentityGap(
                    domain=domain, gap_type=GapType.LOW_COVERAGE.value,
                    score=score, details={"fact_count": n, "floor": COVERAGE_FLOOR},
                ))

            # Confidence
            if facts:
                avg = sum(f.confidence for f in facts) / n
                if avg < CONFIDENCE_FLOOR:
                    gaps.append(IdentityGap(
                        domain=domain, gap_type=GapType.LOW_CONFIDENCE.value,
                        score=1.0 - (avg / CONFIDENCE_FLOOR),
                        details={"avg_confidence": avg, "floor": CONFIDENCE_FLOOR},
                    ))

            # North star
            ns_in_domain = [n for n in self.store.doc.north_stars if n.domain == domain]
            if facts and not ns_in_domain:
                # Only worth asking once the user is clearly active in the domain.
                gaps.append(IdentityGap(
                    domain=domain, gap_type=GapType.NO_NORTH_STAR.value,
                    score=0.6, details={"fact_count": n},
                ))

            # Staleness
            if facts:
                last = max(f.last_seen for f in facts)
                age_days = (now - last) / 86400.0
                if age_days > STALE_DAYS:
                    gaps.append(IdentityGap(
                        domain=domain, gap_type=GapType.STALE_DOMAIN.value,
                        score=min(1.0, age_days / (STALE_DAYS * 2)),
                        details={"age_days": age_days, "stale_after": STALE_DAYS},
                    ))

            # Conflict (lightweight heuristic: same domain, contradictory verbs)
            if n >= 2:
                texts = [f.text.lower() for f in facts]
                positives = sum(1 for t in texts if " do " in t or " am " in t or " have " in t)
                negatives = sum(1 for t in texts if " don't " in t or " not " in t or " no " in t)
                if positives > 0 and negatives > 0:
                    # Surfaced as a soft signal, not a high-confidence conflict claim.
                    gaps.append(IdentityGap(
                        domain=domain, gap_type=GapType.CONFLICTING.value,
                        score=0.5,
                        details={"positive_markers": positives, "negative_markers": negatives},
                    ))

        return sorted(gaps, key=lambda g: -g.score)

    # ----- information theory -----
    def domain_entropy(self, domain: str) -> float:
        """
        H(D) = log2(1 + uncertainty(D)), uncertainty = 1 / (N * c + 0.5).
        Empty domain -> high entropy.  Many high-confidence facts -> low.
        """
        facts = self.store.facts_for_domain(domain)
        n = len(facts)
        if n == 0:
            return math.log2(1.0 + 1.0 / 0.5)   # = log2(3) ≈ 1.585
        avg_conf = sum(f.confidence for f in facts) / n
        uncertainty = 1.0 / (n * avg_conf + 0.5)
        return math.log2(1.0 + uncertainty)

    def expected_information_gain(self, gap: IdentityGap) -> float:
        """
        Approximate H_before - H_after for asking a question targeting
        this gap.  Assumes a successful answer adds 1 fact at confidence
        0.7 to the domain.  Higher gap.score boosts the estimate so
        coverage gaps weigh more than soft-signal conflicts.
        """
        h_before = self.domain_entropy(gap.domain)
        facts = self.store.facts_for_domain(gap.domain)
        n  = len(facts)
        cb = sum(f.confidence for f in facts) / n if n else 0.0
        n2 = n + 1
        cb2 = ((cb * n) + 0.7) / n2 if n else 0.7
        uncertainty_after = 1.0 / (n2 * cb2 + 0.5)
        h_after = math.log2(1.0 + uncertainty_after)
        raw = max(0.0, h_before - h_after)
        return raw * (0.5 + 0.5 * gap.score)

    # ----- question generation -----
    def question_candidates_for_gap(self, gap: IdentityGap) -> List[str]:
        return list(QUESTION_TEMPLATES.get((gap.domain, gap.gap_type), []))

    def fresh_candidates_for_gap(self, gap: IdentityGap) -> List[str]:
        return [q for q in self.question_candidates_for_gap(gap)
                if not self.ledger.already_asked(q)]

    # ----- budget -----
    def _budget_available(self) -> Tuple[bool, str]:
        hour = self.ledger.recent_in_window(3600.0)
        day  = self.ledger.recent_in_window(86400.0)
        # Outstanding = asked but not yet answered (or skipped).
        outstanding_hour = sum(1 for e in hour if e.answered is None)
        if outstanding_hour >= self.max_per_hour:
            return False, f"hourly budget reached: {outstanding_hour}/{self.max_per_hour} outstanding"
        if len(day) >= self.max_per_day:
            return False, f"daily budget reached: {len(day)}/{self.max_per_day} asked in 24h"
        return True, "ok"

    # ----- selection -----
    def select_next_question(self) -> Optional[Tuple[str, IdentityGap, float]]:
        ok, _ = self._budget_available()
        if not ok:
            return None
        gaps = self.detect_gaps()
        if not gaps:
            return None
        # Highest expected information gain wins.
        scored: List[Tuple[float, IdentityGap, str]] = []
        for gap in gaps:
            cands = self.fresh_candidates_for_gap(gap)
            if not cands:
                continue
            gain = self.expected_information_gain(gap)
            scored.append((gain, gap, cands[0]))
        if not scored:
            return None
        scored.sort(key=lambda t: -t[0])
        gain, gap, question = scored[0]
        return question, gap, gain

    # ----- lifecycle hooks -----
    def record_question_asked(
        self, question: str, gap: IdentityGap, expected_gain: float,
    ) -> CuriosityEngagement:
        entry = CuriosityEngagement(
            question=question, domain=gap.domain, gap_type=gap.gap_type,
            expected_information_gain=expected_gain,
        )
        self.ledger.add(entry)
        return entry

    def record_response(
        self, question: str, answered: bool, response_excerpt: Optional[str] = None,
    ) -> Optional[CuriosityEngagement]:
        norm = " ".join((question or "").lower().split())
        for e in reversed(self.ledger.entries):
            if " ".join(e.question.lower().split()) == norm and e.answered is None:
                e.answered = answered
                e.answered_at = time.time()
                e.response_excerpt = (response_excerpt or "")[:400]
                return e
        return None

# =====================================================================
# SPRINT 3 — AGENT VOICE CONTEXT + CONTINUITY TOKENS
# =====================================================================
# Rather than rewriting the existing agent system prompts (risky — the
# user already iterated to good ones), Sprint 3 ships an additive PREAMBLE
# layer that the runtime can prepend per turn.  Voice rewrites become
# data, not code.
#
# Public entry points (all opt-in):
#   build_voice_preamble(agent_id, store, ledger=None) -> str
#       Selects identity facts, north stars, and constitutional rules
#       relevant to the named agent; renders a compact preamble block
#       suitable for prepending to the agent's system_prompt.
#   weave_curiosity_question(response, question) -> str
#       Cleanly appends a curiosity question to a generated response
#       without breaking voice (single blank line + question, no header).
#   ContinuityToken / ContinuityStore
#       Short, structured per-session summary tokens persisted across
#       restarts so the next session's preamble can include 1-2 lines
#       of "what we last talked about" without dragging full transcripts.
# =====================================================================

# Per-agent salience map: which identity slices matter for that agent.
# Tunables; future Voice Evolution sprint can rebalance these.
AGENT_SALIENCE: Dict[str, Dict[str, Any]] = {
    "fast_mentor":           {"facts_per_domain": 1, "domains": None,                   "north_stars": True,  "rules": True,  "max_facts": 4},
    "life_coach":            {"facts_per_domain": 2, "domains": None,                   "north_stars": True,  "rules": True,  "max_facts": 8},
    "quant_architect":       {"facts_per_domain": 3, "domains": [LifeDomain.FINANCIAL.value, LifeDomain.BUSINESS.value], "north_stars": True, "rules": True, "max_facts": 6},
    "quant_architect_explore": {"facts_per_domain": 3, "domains": [LifeDomain.FINANCIAL.value, LifeDomain.BUSINESS.value], "north_stars": True, "rules": True, "max_facts": 6},
    "executive_arbiter":     {"facts_per_domain": 1, "domains": None,                   "north_stars": True,  "rules": True,  "max_facts": 5},
    "research_synthesizer":  {"facts_per_domain": 0, "domains": [],                     "north_stars": False, "rules": True,  "max_facts": 0},
    "factual_auditor":       {"facts_per_domain": 0, "domains": [],                     "north_stars": False, "rules": False, "max_facts": 0},
    "system_guardian":       {"facts_per_domain": 0, "domains": [],                     "north_stars": False, "rules": True,  "max_facts": 0},
    "intent_router":         {"facts_per_domain": 0, "domains": [],                     "north_stars": False, "rules": False, "max_facts": 0},
    "fact_extractor":        {"facts_per_domain": 0, "domains": [],                     "north_stars": False, "rules": False, "max_facts": 0},
    "grounding_extractor":   {"facts_per_domain": 0, "domains": [],                     "north_stars": False, "rules": False, "max_facts": 0},
    "biographer":            {"facts_per_domain": 0, "domains": [],                     "north_stars": False, "rules": True,  "max_facts": 0},
}

def _select_facts(store: "IdentityStore", policy: Dict[str, Any]) -> List["IdentityFact"]:
    domains = policy.get("domains")
    per     = int(policy.get("facts_per_domain", 0) or 0)
    cap     = int(policy.get("max_facts", 0) or 0)
    if per <= 0 or cap <= 0:
        return []
    if domains is None:
        domains = [d.value for d in LifeDomain if d != LifeDomain.UNCATEGORIZED]
    picked: List["IdentityFact"] = []
    for dom in domains:
        facts = sorted(store.facts_for_domain(dom),
                       key=lambda f: (-(f.confidence), -(f.seen_count)))
        picked.extend(facts[:per])
    # Stable cap by confidence then recency.
    picked.sort(key=lambda f: (-(f.confidence), -(f.last_seen)))
    return picked[:cap]

def build_voice_preamble(
    agent_id: str,
    store: "IdentityStore",
    ledger: Optional["EngagementLedger"] = None,
    include_curiosity_hint: bool = False,
) -> str:
    """
    Render a compact identity-aware preamble for the named agent.
    Returns "" when the agent should not see user identity at all
    (router, auditor, guardian, etc.).
    """
    policy = AGENT_SALIENCE.get(agent_id)
    if not policy:
        return ""

    lines: List[str] = []

    # Constitutional rules outrank everything else.
    if policy.get("rules"):
        rules = store.active_rules()
        if rules:
            lines.append("USER GROUND RULES (always honor; outranks any inferred preference):")
            for r in rules[:5]:
                lines.append(f"  - {r.text.strip()}")

    # North stars next.
    if policy.get("north_stars"):
        stars = store.active_north_stars()
        if stars:
            lines.append("USER NORTH STARS (anchor your voice to these):")
            for n in stars[:5]:
                tag = f"[{n.domain}] " if n.domain and n.domain != LifeDomain.UNCATEGORIZED.value else ""
                lines.append(f"  - {tag}{n.text.strip()}")

    # Facts.
    facts = _select_facts(store, policy)
    if facts:
        lines.append("WHAT YOU KNOW ABOUT THE USER (do not quote verbatim):")
        for f in facts:
            tag = f"[{f.domain}] " if f.domain and f.domain != LifeDomain.UNCATEGORIZED.value else ""
            lines.append(f"  - {tag}{f.text.strip()}")

    if include_curiosity_hint and ledger is not None:
        recent = ledger.recent_in_window(86400.0)
        outstanding = [e for e in recent if e.answered is None]
        if outstanding:
            lines.append("OPEN CURIOSITY (an unanswered question from earlier — only revisit if the user reopens it):")
            for e in outstanding[:2]:
                lines.append(f"  - {e.question.strip()}")

    return "\n".join(lines)

def weave_curiosity_question(response: str, question: str) -> str:
    """
    Append a curiosity question to a response without breaking voice.
    Single blank line separator; no header label.  Returns the response
    unchanged if the question is empty or already present.
    """
    if not question:
        return response or ""
    base = (response or "").rstrip()
    if question.strip().lower() in base.lower():
        return base
    return f"{base}\n\n{question.strip()}"

# ─── Continuity Tokens ─────────────────────────────────────────────────
@dataclass
class ContinuityToken:
    """
    A compact per-session summary token.  Persisted across restarts so
    the NEXT session's preamble can include 1-2 lines of context without
    dragging full transcripts.
    """
    session_id: str
    created: float                                     = field(default_factory=lambda: time.time())
    last_intent: Optional[str]                         = None
    open_threads: List[str]                            = field(default_factory=list)   # short phrases
    domains_touched: List[str]                         = field(default_factory=list)
    mood_signal: Optional[str]                         = None                          # one of: light, focused, heavy, mixed
    summary: Optional[str]                             = None                          # <= 240 chars
    metadata: Dict[str, Any]                           = field(default_factory=dict)

CONTINUITY_PATH = STORAGE_DIR / "continuity.json"
MAX_CONTINUITY_TOKENS = 20

class ContinuityStore:
    """Disk-backed ring buffer of ContinuityTokens."""
    def __init__(self, path: Path = CONTINUITY_PATH) -> None:
        self.path: Path = path
        self.tokens: List[ContinuityToken] = []

    def load(self) -> "ContinuityStore":
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.tokens = [ContinuityToken(**t) for t in data.get("tokens", [])]
            except Exception as e:
                logger.warning(f"continuity load failed at {self.path}: {e}")
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tokens": [asdict(t) for t in self.tokens[-MAX_CONTINUITY_TOKENS:]]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, token: ContinuityToken) -> None:
        self.tokens.append(token)
        if len(self.tokens) > MAX_CONTINUITY_TOKENS:
            self.tokens = self.tokens[-MAX_CONTINUITY_TOKENS:]

    def latest(self, n: int = 1) -> List[ContinuityToken]:
        return self.tokens[-n:] if self.tokens else []

def build_continuity_preamble(store: "ContinuityStore", n: int = 1) -> str:
    """
    Render the last N continuity tokens into a tiny preamble block
    suitable for prepending to fast_mentor / life_coach / executive_arbiter.
    Returns "" if there's nothing to carry forward.
    """
    tokens = store.latest(n)
    if not tokens:
        return ""
    lines = ["RECENT CONTEXT (from prior sessions — reference only if the user reopens it):"]
    for t in tokens:
        parts: List[str] = []
        if t.summary:
            parts.append(t.summary.strip())
        if t.open_threads:
            parts.append("open: " + "; ".join(t.open_threads[:3]))
        if t.mood_signal:
            parts.append(f"mood: {t.mood_signal}")
        if parts:
            lines.append("  - " + " | ".join(parts))
    return "\n".join(lines)

# =====================================================================
# SPRINT 4 — VOICE EVOLUTION ENGINE
# =====================================================================
# Per-agent voice parameters that adapt over time from engagement
# signals.  When users engage more with brief, warm fast_mentor outputs,
# the brevity preference inches up; when curiosity questions in a domain
# go unanswered, that domain's curiosity multiplier drifts down.
#
# Persistent at runtime/storage/voice_profiles.json.  All evolution
# is opt-in: the runtime calls record_interaction(...) and reads
# evolved_salience(agent_id) only when ready.
# =====================================================================

@dataclass
class EngagementSignal:
    """A single observation about how an agent's output landed."""
    agent_id: str
    timestamp: float                      = field(default_factory=lambda: time.time())
    output_chars: int                     = 0
    user_followed_up: Optional[bool]      = None      # did the user reply within window?
    user_explicit_positive: Optional[bool] = None     # 👍 / "thanks" / "perfect"
    user_explicit_negative: Optional[bool] = None     # 👎 / "wrong" / "too long"
    curiosity_question_answered: Optional[bool] = None
    domain: Optional[str]                 = None
    metadata: Dict[str, Any]              = field(default_factory=dict)

@dataclass
class VoiceProfile:
    """
    Learned per-agent voice parameters.  Centered at 1.0 (neutral);
    drift bounded to [0.5, 2.0] so no single bad week can destroy voice.
    """
    agent_id: str
    brevity_pref:        float            = 1.0     # >1 = user prefers shorter outputs
    warmth_pref:         float            = 1.0     # >1 = user prefers warmer tone
    curiosity_mult:      float            = 1.0     # >1 = ask more curiosity questions
    domain_curiosity:    Dict[str, float] = field(default_factory=dict)  # per-domain multiplier
    interaction_count:   int              = 0
    last_updated:        float            = field(default_factory=lambda: time.time())
    metadata:            Dict[str, Any]   = field(default_factory=dict)

VOICE_PROFILES_PATH = STORAGE_DIR / "voice_profiles.json"
VOICE_DRIFT_MIN  = 0.5
VOICE_DRIFT_MAX  = 2.0
VOICE_LEARN_RATE = 0.05   # per-signal nudge

class VoiceEvolutionEngine:
    """
    Tracks engagement signals per agent and evolves a VoiceProfile.
    Drift is bounded and slow — voices change over weeks, not minutes.
    """
    def __init__(self, path: Path = VOICE_PROFILES_PATH) -> None:
        self.path: Path = path
        self.profiles: Dict[str, VoiceProfile] = {}
        self.signals: List[EngagementSignal] = []   # recent ring buffer

    # ----- lifecycle -----
    def load(self) -> "VoiceEvolutionEngine":
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.profiles = {
                    aid: VoiceProfile(**v)
                    for aid, v in data.get("profiles", {}).items()
                }
            except Exception as e:
                logger.warning(f"voice profiles load failed at {self.path}: {e}")
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"profiles": {aid: asdict(p) for aid, p in self.profiles.items()}}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self.path)

    # ----- access -----
    def profile_for(self, agent_id: str) -> VoiceProfile:
        if agent_id not in self.profiles:
            self.profiles[agent_id] = VoiceProfile(agent_id=agent_id)
        return self.profiles[agent_id]

    @staticmethod
    def _clamp(x: float) -> float:
        return max(VOICE_DRIFT_MIN, min(VOICE_DRIFT_MAX, x))

    # ----- learning -----
    def record_interaction(self, signal: EngagementSignal) -> VoiceProfile:
        """
        Nudge the agent's profile based on a single observation.
        Effect sizes are small (VOICE_LEARN_RATE) so evolution is slow.
        """
        p = self.profile_for(signal.agent_id)
        p.interaction_count += 1
        p.last_updated = time.time()

        # Brevity: positive feedback on a long output -> user tolerates length
        # (brevity pref drifts DOWN); negative feedback on a long output ->
        # brevity pref drifts UP.
        if signal.output_chars and signal.user_explicit_positive:
            if signal.output_chars > 600:
                p.brevity_pref = self._clamp(p.brevity_pref - VOICE_LEARN_RATE)
            elif signal.output_chars < 200:
                p.brevity_pref = self._clamp(p.brevity_pref + VOICE_LEARN_RATE / 2)
        if signal.user_explicit_negative and signal.output_chars and signal.output_chars > 400:
            p.brevity_pref = self._clamp(p.brevity_pref + VOICE_LEARN_RATE * 2)

        # Warmth: positive emoji/word feedback nudges warmth up.
        if signal.user_explicit_positive:
            p.warmth_pref = self._clamp(p.warmth_pref + VOICE_LEARN_RATE / 2)
        if signal.user_explicit_negative:
            p.warmth_pref = self._clamp(p.warmth_pref - VOICE_LEARN_RATE / 4)

        # Curiosity: answered question -> bump global curiosity AND domain;
        # unanswered question -> drop both.
        if signal.curiosity_question_answered is True:
            p.curiosity_mult = self._clamp(p.curiosity_mult + VOICE_LEARN_RATE)
            if signal.domain:
                p.domain_curiosity[signal.domain] = self._clamp(
                    p.domain_curiosity.get(signal.domain, 1.0) + VOICE_LEARN_RATE * 2
                )
        elif signal.curiosity_question_answered is False:
            p.curiosity_mult = self._clamp(p.curiosity_mult - VOICE_LEARN_RATE / 2)
            if signal.domain:
                p.domain_curiosity[signal.domain] = self._clamp(
                    p.domain_curiosity.get(signal.domain, 1.0) - VOICE_LEARN_RATE
                )

        # User followed up at all = mild positive signal for the agent.
        if signal.user_followed_up is True and signal.user_explicit_negative is not True:
            p.warmth_pref = self._clamp(p.warmth_pref + VOICE_LEARN_RATE / 4)

        # Keep a small recent-signal ring buffer (memory-only).
        self.signals.append(signal)
        if len(self.signals) > 200:
            self.signals = self.signals[-200:]
        return p

    # ----- application -----
    def evolved_salience(self, agent_id: str, base: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply the learned profile to a base AGENT_SALIENCE policy.
        Heavy brevity_pref shrinks max_facts; high curiosity_mult is
        used by callers to decide whether to weave a curiosity question.
        """
        p = self.profile_for(agent_id)
        out = dict(base or {})
        base_facts = int(out.get("max_facts", 0) or 0)
        if base_facts > 0 and p.brevity_pref > 1.0:
            shrink = 1.0 / p.brevity_pref
            out["max_facts"] = max(1, int(round(base_facts * shrink)))
        out["_voice_brevity_pref"]   = p.brevity_pref
        out["_voice_warmth_pref"]    = p.warmth_pref
        out["_voice_curiosity_mult"] = p.curiosity_mult
        return out

    def should_ask_curiosity(
        self, agent_id: str, domain: Optional[str], default: bool = True,
    ) -> bool:
        """
        Combine the global curiosity_mult and the domain-specific
        multiplier to decide whether to weave a curiosity question this
        turn.  Result is deterministic given the same profile state.
        """
        p = self.profile_for(agent_id)
        score = p.curiosity_mult * (p.domain_curiosity.get(domain, 1.0) if domain else 1.0)
        # default=True means "ask unless score has clearly drifted below 0.7"
        return score >= 0.7 if default else score >= 1.3

# =====================================================================
# SPRINT 5 — IDENTITY SYNTHESIS LAYER
# =====================================================================
# Synthesizes the raw IdentityFact stream into a coherent, queryable
# user portrait.  Deterministic baseline (theme clustering by keyword
# overlap; contradiction detection by verb opposition).  Sprint 7 will
# layer LLM-generated narrative summaries on top using the same data
# structures.
#
# Public entry points:
#   IdentitySynthesizer(store)
#     .synthesize_domain(domain)   -> DomainSummary
#     .synthesize_portrait()       -> UserPortrait    (across all domains)
#     .detect_contradictions()     -> List[Contradiction]
#     .write_back_summaries()      -> updates store.doc.domain_summaries
# =====================================================================

@dataclass
class DomainSummary:
    domain: str
    fact_count: int                                 = 0
    avg_confidence: float                           = 0.0
    themes: List[str]                               = field(default_factory=list)
    representative_facts: List[str]                 = field(default_factory=list)
    narrative: str                                  = ""

@dataclass
class Contradiction:
    domain: str
    fact_a: str
    fact_b: str
    reason: str
    score: float                                    = 0.5

@dataclass
class UserPortrait:
    generated_at: float                             = field(default_factory=lambda: time.time())
    domains: Dict[str, DomainSummary]               = field(default_factory=dict)
    north_stars: List[str]                          = field(default_factory=list)
    rules: List[str]                                = field(default_factory=list)
    contradictions: List[Contradiction]             = field(default_factory=list)
    one_line_summary: str                           = ""

# Verbs that, paired across two facts in the same domain, suggest
# contradiction.  Conservative — we surface a soft signal, never claim
# certainty.
_OPPOSING_VERB_PAIRS: List[Tuple[str, str]] = [
    ("love",  "hate"),   ("like",  "dislike"),
    ("want",  "avoid"),  ("enjoy", "dread"),
    ("am",    "am not"), ("do",    "don't"),
    ("have",  "don't have"),
]

# Stopwords for theme keyword extraction.
_THEME_STOPWORDS = set(
    "i me my we us our the a an and or but if of in on at to for with from "
    "is am are was were be been being do does did don dont have has had this "
    "that those these as by it about not no yes you your they them their".split()
)

class IdentitySynthesizer:
    """Builds DomainSummary / UserPortrait from an IdentityStore."""

    def __init__(self, store: "IdentityStore") -> None:
        self.store = store

    # ----- theme extraction -----
    @staticmethod
    def _extract_themes(texts: List[str], top_k: int = 5) -> List[str]:
        freq: Dict[str, int] = {}
        for t in texts:
            for w in re.findall(r"[a-zA-Z][a-zA-Z'-]+", t.lower()):
                if w in _THEME_STOPWORDS or len(w) <= 2:
                    continue
                freq[w] = freq.get(w, 0) + 1
        # Themes are words appearing in at least 2 facts (or the most
        # frequent if fewer facts).
        if len(texts) >= 2:
            promoted = {w: c for w, c in freq.items() if c >= 2}
            if promoted:
                return [w for w, _ in sorted(promoted.items(), key=lambda kv: -kv[1])[:top_k]]
        return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:top_k]]

    # ----- per-domain -----
    def synthesize_domain(self, domain: str) -> DomainSummary:
        facts = self.store.facts_for_domain(domain)
        s = DomainSummary(domain=domain, fact_count=len(facts))
        if not facts:
            return s
        s.avg_confidence = sum(f.confidence for f in facts) / len(facts)
        texts = [f.text for f in facts]
        s.themes = self._extract_themes(texts)
        ranked = sorted(facts, key=lambda f: (-(f.confidence), -(f.seen_count)))
        s.representative_facts = [f.text for f in ranked[:3]]
        # Compact narrative — deterministic, no LLM required.
        s.narrative = self._narrate(domain, s)
        return s

    @staticmethod
    def _narrate(domain: str, s: DomainSummary) -> str:
        if not s.representative_facts:
            return ""
        themes = (" / ".join(s.themes[:3])).strip()
        themes_part = f" Themes: {themes}." if themes else ""
        conf = f" (avg confidence {s.avg_confidence:.2f})"
        lead = s.representative_facts[0].rstrip(".")
        more = len(s.representative_facts) - 1
        more_part = f" Plus {more} more attested fact{'s' if more > 1 else ''}." if more > 0 else ""
        return f"[{domain}] {lead}.{more_part}{themes_part}{conf}"

    # ----- contradictions -----
    def detect_contradictions(self) -> List[Contradiction]:
        out: List[Contradiction] = []
        seen_pairs: set = set()
        for dom_enum in LifeDomain:
            dom = dom_enum.value
            if dom == LifeDomain.UNCATEGORIZED.value:
                continue
            facts = self.store.facts_for_domain(dom)
            for i, f1 in enumerate(facts):
                for f2 in facts[i + 1:]:
                    key = tuple(sorted([f1.text, f2.text]))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    lo1, lo2 = f1.text.lower(), f2.text.lower()
                    for pos, neg in _OPPOSING_VERB_PAIRS:
                        if (pos in lo1 and neg in lo2) or (neg in lo1 and pos in lo2):
                            # Boost when subject keywords overlap too.
                            shared = set(re.findall(r"[a-zA-Z]+", lo1)) & set(re.findall(r"[a-zA-Z]+", lo2))
                            shared -= _THEME_STOPWORDS
                            score = 0.4 + min(0.5, 0.1 * len(shared))
                            out.append(Contradiction(
                                domain=dom, fact_a=f1.text, fact_b=f2.text,
                                reason=f"opposing markers: '{pos}' vs '{neg}'",
                                score=score,
                            ))
                            break
        return sorted(out, key=lambda c: -c.score)

    # ----- portrait -----
    def synthesize_portrait(self) -> UserPortrait:
        port = UserPortrait()
        for dom_enum in LifeDomain:
            dom = dom_enum.value
            if dom == LifeDomain.UNCATEGORIZED.value:
                continue
            summary = self.synthesize_domain(dom)
            if summary.fact_count > 0:
                port.domains[dom] = summary
        port.north_stars = [n.text for n in self.store.active_north_stars()[:5]]
        port.rules       = [r.text for r in self.store.active_rules()[:5]]
        port.contradictions = self.detect_contradictions()
        port.one_line_summary = self._compose_one_liner(port)
        return port

    @staticmethod
    def _compose_one_liner(port: UserPortrait) -> str:
        if not port.domains:
            return "Identity portrait is empty — no attested facts yet."
        ranked = sorted(port.domains.values(), key=lambda d: -d.fact_count)
        top = ranked[:3]
        bits = [f"{d.domain}({d.fact_count})" for d in top]
        ns_bit = f"; north stars: {len(port.north_stars)}" if port.north_stars else ""
        contra_bit = f"; {len(port.contradictions)} contradiction(s)" if port.contradictions else ""
        return f"User portrait: {len(port.domains)} active domain(s) — " + ", ".join(bits) + ns_bit + contra_bit + "."

    # ----- write back -----
    def write_back_summaries(self) -> None:
        for dom_enum in LifeDomain:
            dom = dom_enum.value
            if dom == LifeDomain.UNCATEGORIZED.value:
                continue
            summary = self.synthesize_domain(dom)
            if summary.fact_count > 0:
                self.store.doc.domain_summaries[dom] = summary.narrative

# =====================================================================
# SPRINT 6 — MEMORY ARCHITECTURE ADVANCES
# =====================================================================
# A tiered memory model on top of the existing belief_graph + ChromaDB.
#
#   WORKING   in-conversation scratch (held in process state)
#   EPISODIC  per-turn record with decay (45-day half-life)
#   SEMANTIC  consolidated, deduped, low-decay general knowledge
#   IDENTITY  durable identity facts (delegated to IdentityStore)
#
# Public entry points (all opt-in):
#   MemoryRecord                a tier-tagged, decayable memory cell
#   apply_decay(record, now)    confidence with exponential half-life
#   MemoryRouter.route(text)    picks the right tier + sensitivity tag
#   MemoryStore.add(record)     dedupe + consolidate hint
#   MemoryStore.search(query)   tier-aware retrieval (recency * decay)
#   MemoryStore.consolidate()   episodic -> semantic when seen_count ≥ 3
#   MemoryStore.purge_expired() drops records below MIN_LIVE_CONFIDENCE
# =====================================================================

class MemoryTier(str, Enum):
    WORKING  = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    IDENTITY = "identity"

# Per-tier half-life (days).  WORKING is in-RAM-only; IDENTITY is handled
# elsewhere and listed here for completeness.
TIER_HALFLIFE_DAYS: Dict[str, float] = {
    MemoryTier.WORKING.value:  0.0,        # ephemeral
    MemoryTier.EPISODIC.value: 45.0,
    MemoryTier.SEMANTIC.value: 365.0,
    MemoryTier.IDENTITY.value: 1825.0,     # ~5 years before any decay matters
}
MIN_LIVE_CONFIDENCE = 0.05
CONSOLIDATION_FLOOR = 3   # seen_count required to promote episodic -> semantic

@dataclass
class MemoryRecord:
    text: str
    tier: str                                       = MemoryTier.EPISODIC.value
    sensitivity: str                                = Sensitivity.MEDIUM.value
    domain: str                                     = LifeDomain.UNCATEGORIZED.value
    confidence: float                               = 0.7
    seen_count: int                                 = 1
    created: float                                  = field(default_factory=lambda: time.time())
    last_seen: float                                = field(default_factory=lambda: time.time())
    metadata: Dict[str, Any]                        = field(default_factory=dict)

def apply_decay(record: MemoryRecord, now: Optional[float] = None) -> float:
    """
    Exponential half-life decay.  Returns the EFFECTIVE confidence at
    `now` without mutating the record.  WORKING tier never persists so
    its effective confidence is whatever the record carries.
    """
    now = now if now is not None else time.time()
    halflife_days = TIER_HALFLIFE_DAYS.get(record.tier, 45.0)
    if halflife_days <= 0:
        return record.confidence
    age_days = max(0.0, (now - record.last_seen) / 86400.0)
    factor = 0.5 ** (age_days / halflife_days)
    return max(0.0, record.confidence * factor)

class MemoryRouter:
    """
    Picks the right tier + sensitivity tag for incoming text.
    Heuristic baseline; ChromaDB-similarity overrides are plug-ins
    that the runtime can layer on later.
    """

    @staticmethod
    def route(text: str, hint_tier: Optional[str] = None) -> Tuple[str, str, str]:
        """Returns (tier, sensitivity, domain)."""
        sensitivity = SensitivityRouter.classify_text(text)
        domain      = classify_domain(text)

        # SECRET content never goes beyond WORKING.
        if sensitivity == Sensitivity.SECRET.value:
            return MemoryTier.WORKING.value, sensitivity, domain

        # Identity-shaped statements ("I am...", "I have...", "I want...")
        # route to IDENTITY when the domain is meaningful.
        is_identity_shaped = bool(re.match(r"\s*i\s+(am|have|live|work|like|love|hate|want|believe)", text.lower()))
        if hint_tier:
            return hint_tier, sensitivity, domain
        if is_identity_shaped and domain != LifeDomain.UNCATEGORIZED.value:
            return MemoryTier.IDENTITY.value, sensitivity, domain
        # Default everything else to EPISODIC.
        return MemoryTier.EPISODIC.value, sensitivity, domain

class MemoryStore:
    """
    Tiered in-memory store.  Persistence is handled by the existing
    SQLite belief_graph + ChromaDB at the runtime layer — this class is
    the logical model the runtime will eventually delegate to.
    """
    def __init__(self) -> None:
        self.records: List[MemoryRecord] = []

    def add(self, record: MemoryRecord) -> MemoryRecord:
        norm = " ".join(record.text.lower().split())
        for r in self.records:
            if " ".join(r.text.lower().split()) == norm and r.tier == record.tier:
                r.seen_count += 1
                r.last_seen   = time.time()
                r.confidence  = min(1.0, r.confidence + 0.05)
                return r
        self.records.append(record)
        return record

    def search(
        self, query: str, limit: int = 5,
        tiers: Optional[Iterable[str]] = None,
        max_sensitivity: Optional[str] = None,
    ) -> List[Tuple[MemoryRecord, float]]:
        """
        Lexical search; returns (record, score) sorted by score desc.
        score = (token-overlap) * effective_confidence.
        Filter by tier + sensitivity ceiling for privacy-aware retrieval.
        """
        order = {s.value: i for i, s in enumerate(
            [Sensitivity.LOW, Sensitivity.MEDIUM, Sensitivity.HIGH, Sensitivity.SECRET])}
        ceiling = order.get(max_sensitivity, 3) if max_sensitivity else 3
        qtokens = set(re.findall(r"[a-zA-Z]+", query.lower()))
        if not qtokens:
            return []
        tier_set = set(tiers) if tiers else None
        scored: List[Tuple[MemoryRecord, float]] = []
        for r in self.records:
            if tier_set and r.tier not in tier_set:
                continue
            if order.get(r.sensitivity, 1) > ceiling:
                continue
            rtokens = set(re.findall(r"[a-zA-Z]+", r.text.lower()))
            if not rtokens:
                continue
            overlap = len(qtokens & rtokens) / max(len(qtokens | rtokens), 1)
            if overlap == 0.0:
                continue
            score = overlap * apply_decay(r)
            if score > 0:
                scored.append((r, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]

    def consolidate(self) -> int:
        """
        Promote stable episodic memories to semantic when seen_count
        >= CONSOLIDATION_FLOOR.  Returns the number of promotions.
        """
        promoted = 0
        for r in self.records:
            if (r.tier == MemoryTier.EPISODIC.value
                    and r.seen_count >= CONSOLIDATION_FLOOR
                    and apply_decay(r) > 0.5):
                r.tier = MemoryTier.SEMANTIC.value
                r.metadata["consolidated_at"] = time.time()
                promoted += 1
        return promoted

    def purge_expired(self) -> int:
        """Drop records whose effective confidence has fallen below the floor."""
        before = len(self.records)
        self.records = [
            r for r in self.records
            if r.tier == MemoryTier.WORKING.value or apply_decay(r) >= MIN_LIVE_CONFIDENCE
        ]
        return before - len(self.records)

# =====================================================================
# SPRINT 7 — HARDWARE & PERFORMANCE + PHASE 2 MODEL INTELLIGENCE
# =====================================================================
# Two related pieces:
#
# 1. PerformanceLog — per-node latency tracking on a ring buffer so the
#    runtime can answer "what's slow?" without keeping unbounded state.
#
# 2. Phase 2 Model Intelligence — uses behavioral fingerprints to
#    SELECT the best available model for an agent's declared
#    capabilities, replacing the Sprint 0 pool's positional pick with
#    a real best-fit search.  Activation flips one line in the
#    runtime (model_for_agent).
#
# 3. SpeculativeBrancher — a skeleton dispatcher that runs N model
#    variants in parallel (capability-permitting) and lets the caller
#    pick the winner via custom scoring.  Wired into synthesis_node
#    in a future revision.
# =====================================================================

# ---------- 1. Performance log -----------------------------------------
@dataclass
class PerfSample:
    node:        str
    latency_ms:  float
    timestamp:   float                              = field(default_factory=lambda: time.time())
    metadata:    Dict[str, Any]                     = field(default_factory=dict)

PERF_RING_SIZE = 1000

class PerformanceLog:
    """In-memory ring buffer of per-node latency samples + aggregates."""
    def __init__(self, ring_size: int = PERF_RING_SIZE) -> None:
        self.samples: List[PerfSample] = []
        self.ring_size = ring_size

    def record(self, node: str, latency_ms: float, **md: Any) -> None:
        self.samples.append(PerfSample(node=node, latency_ms=float(latency_ms), metadata=dict(md)))
        if len(self.samples) > self.ring_size:
            self.samples = self.samples[-self.ring_size:]

    def aggregate(self, node: Optional[str] = None) -> Dict[str, float]:
        pool = [s for s in self.samples if (node is None or s.node == node)]
        if not pool:
            return {"count": 0.0}
        lat = sorted(s.latency_ms for s in pool)
        n = len(lat)
        return {
            "count":  float(n),
            "p50":    lat[n // 2],
            "p90":    lat[min(n - 1, int(n * 0.9))],
            "p99":    lat[min(n - 1, int(n * 0.99))],
            "mean":   sum(lat) / n,
            "max":    lat[-1],
            "min":    lat[0],
        }

    def slowest_nodes(self, top_k: int = 5) -> List[Tuple[str, float]]:
        per_node: Dict[str, List[float]] = {}
        for s in self.samples:
            per_node.setdefault(s.node, []).append(s.latency_ms)
        scored = [(n, sum(v) / len(v)) for n, v in per_node.items() if v]
        scored.sort(key=lambda kv: -kv[1])
        return scored[:top_k]

# ---------- 2. Phase 2 Model Intelligence ------------------------------
# Map evaluation axis (returned by fingerprint prompts) -> Capability enum value.
FINGERPRINT_AXIS_TO_CAPABILITY: Dict[str, str] = {
    "instruction_following":  Capability.INSTRUCTION_FOLLOWING.value,
    "structured_output":      Capability.STRUCTURED_OUTPUT.value,
    "math_reasoning":         Capability.MATH_REASONING.value,
    "brief_responses":        Capability.BRIEF_RESPONSES.value,
    "emotional_intelligence": Capability.EMOTIONAL_INTELLIGENCE.value,
    "code_generation":        Capability.CODE_GENERATION.value,
    "refusal_discipline":     Capability.REFUSAL_DISCIPLINE.value,
    "nuanced_critique":       Capability.NUANCED_CRITIQUE.value,
    "creative_generation":    Capability.CREATIVE_GENERATION.value,
    "factual_recall":         Capability.FACTUAL_RECALL.value,
    "reasoning":              Capability.REASONING.value,
}

# How a CapabilityLevel translates to required axis strength.  STRONG must
# clear AXIS_STRENGTH_STRONG; MODERATE only AXIS_STRENGTH_MODERATE; AVOID
# is a hard exclusion when the axis is strongly present.
AXIS_STRENGTH_STRONG    = 0.6
AXIS_STRENGTH_MODERATE  = 0.35

def _axis_strength(vec: List[float]) -> float:
    """
    Reduce an 8-dim feature vector for one axis into a 0..1 scalar.
    Heuristic: features 1, 3, 4, 5, 6, 7 are signal-bearing (brevity,
    structure, hedging, numeracy, code-likeness, density).  Take the
    mean as the strength estimate.
    """
    if not vec:
        return 0.0
    return min(1.0, sum(vec) / len(vec))

def score_model_for_agent(
    model_name: str,
    agent_spec: "AgentSpec",
    fingerprints: Dict[str, Dict[str, List[float]]],
) -> Tuple[float, List[str]]:
    """
    Returns (score, notes).  Score is in [0, 1]; higher = better fit.
    A return of (-1.0, [...]) signals a hard exclusion (avoid violated).
    """
    notes: List[str] = []
    fp = fingerprints.get(model_name)
    if not fp:
        # No evidence — neutral 0.5.
        return 0.5, [f"no fingerprint for {model_name}; neutral score"]

    # Hard exclusion: capabilities_avoid
    for cap in (agent_spec.capabilities_avoid or []):
        axis = None
        for ax, c in FINGERPRINT_AXIS_TO_CAPABILITY.items():
            if c == cap:
                axis = ax; break
        if not axis:
            continue
        strength = _axis_strength(fp.get(axis, []))
        if strength >= AXIS_STRENGTH_STRONG:
            notes.append(f"AVOID violated: {axis} strength {strength:.2f}")
            return -1.0, notes

    # Required capabilities
    required_ok = 0.0
    required_total = 0.0
    for cap, level in (agent_spec.capabilities_required or {}).items():
        axis = None
        for ax, c in FINGERPRINT_AXIS_TO_CAPABILITY.items():
            if c == cap:
                axis = ax; break
        if not axis:
            continue
        strength = _axis_strength(fp.get(axis, []))
        threshold = AXIS_STRENGTH_STRONG if level == CapabilityLevel.STRONG.value else AXIS_STRENGTH_MODERATE
        required_total += 1.0
        if strength >= threshold:
            required_ok += 1.0
        else:
            notes.append(f"REQUIRED short: {axis} {strength:.2f} < {threshold:.2f}")

    # Preferred capabilities (soft bonus)
    preferred_bonus = 0.0
    preferred_total = max(len(agent_spec.capabilities_preferred or {}), 1)
    for cap in (agent_spec.capabilities_preferred or {}).keys():
        axis = None
        for ax, c in FINGERPRINT_AXIS_TO_CAPABILITY.items():
            if c == cap:
                axis = ax; break
        if not axis:
            continue
        strength = _axis_strength(fp.get(axis, []))
        if strength >= AXIS_STRENGTH_MODERATE:
            preferred_bonus += 1.0

    req_score = (required_ok / required_total) if required_total > 0 else 0.7
    pref_score = preferred_bonus / preferred_total
    score = 0.8 * req_score + 0.2 * pref_score
    notes.append(f"required={required_ok:.0f}/{required_total:.0f} preferred_bonus={preferred_bonus:.0f}/{preferred_total}")
    return score, notes

def select_model_for_agent(
    agent_spec: "AgentSpec",
    profile: "HardwareProfile",
    fingerprints: Optional[Dict[str, Dict[str, List[float]]]] = None,
) -> Tuple[str, float, List[str]]:
    """
    Pick the best-fit model for this agent at the active tier.
    Falls back to agent_spec.model_name if the pool is empty.
    """
    pool = list(agent_spec.model_pool_per_tier.get(profile.tier, []))
    if not pool:
        return agent_spec.model_name, 0.5, ["empty pool — falling back to model_name"]
    if not fingerprints:
        return pool[0], 0.5, ["no fingerprints available — first-in-pool"]
    scored: List[Tuple[float, str, List[str]]] = []
    for m in pool:
        sc, notes = score_model_for_agent(m, agent_spec, fingerprints)
        scored.append((sc, m, notes))
    # Drop hard-excluded.
    live = [s for s in scored if s[0] >= 0.0]
    if not live:
        return pool[0], 0.0, ["all pool models excluded — falling back"]
    live.sort(key=lambda t: -t[0])
    winner = live[0]
    return winner[1], winner[0], winner[2]

# ---------- 3. Speculative branching skeleton --------------------------
@dataclass
class SpeculativeBranch:
    model_name: str
    output: str
    latency_ms: float
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

class SpeculativeBrancher:
    """
    Picks the winning output among N parallel model candidates using a
    user-supplied scoring function.  Stateless; the runtime supplies the
    actual async invokers in a future activation pass.
    """
    def __init__(self, scorer: Optional[Callable[[SpeculativeBranch], float]] = None) -> None:
        self.scorer = scorer or (lambda b: float(len(b.output or "")))

    def pick(self, branches: List[SpeculativeBranch]) -> Optional[SpeculativeBranch]:
        if not branches:
            return None
        for b in branches:
            b.score = float(self.scorer(b))
        branches.sort(key=lambda b: -b.score)
        return branches[0]

    @staticmethod
    def latency_weighted_scorer(weight: float = 0.001) -> Callable[[SpeculativeBranch], float]:
        """Higher output content but lightly penalize slow branches."""
        def _score(b: SpeculativeBranch) -> float:
            return float(len(b.output or "")) - weight * float(b.latency_ms or 0.0)
        return _score

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
            logger.warning("Default security key is active. Set LATTICED_SECRET env var before exposing the service beyond localhost.")

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
                    CREATE TABLE IF NOT EXISTS belief_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT UNIQUE NOT NULL, confidence REAL DEFAULT 0.5, last_seen REAL, source TEXT, categories TEXT DEFAULT '');
                    CREATE TABLE IF NOT EXISTS interaction_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, thread_id TEXT, user_input TEXT, intent TEXT, path TEXT, approved INTEGER, loop_count INTEGER, latency_ms INTEGER, output_prev TEXT);
                    CREATE TABLE IF NOT EXISTS hardware_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, node TEXT, latency_ms INTEGER);
                    CREATE TABLE IF NOT EXISTS pending_questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_id TEXT,
                        thread_id TEXT,
                        memory_preview TEXT,
                        question_type TEXT,
                        question_text TEXT,
                        options TEXT,
                        scores_json TEXT,
                        created_at REAL,
                        answered_at REAL,
                        answer TEXT,
                        status TEXT DEFAULT 'pending'
                    );
                    CREATE INDEX IF NOT EXISTS idx_pending_questions_status ON pending_questions(status, created_at DESC);
                    """
                )
                # Idempotent migration: add categories column to belief_graph if not present.
                # Older databases predate the category taxonomy.
                try:
                    conn.execute("ALTER TABLE belief_graph ADD COLUMN categories TEXT DEFAULT ''")
                    logger.info("[init_db] Added 'categories' column to belief_graph (migration).")
                except sqlite3.OperationalError:
                    pass   # Column already exists — nothing to do.
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
                name="latticed_memory",
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
        Read the belief graph, apply temporal decay AND relevance filtering.

        Two-stage scoring:
          1. Temporal decay: confidence decays exponentially with age.
             Facts below 0.20 effective confidence are excluded.
          2. Relevance: each surviving fact is scored by cosine similarity
             against the current user query using the shared embedding model.
             Facts below BELIEF_RELEVANCE_THRESHOLD are excluded.

        Without stage 2, every query received the same top-10 beliefs regardless
        of topic — causing financial beliefs to leak into casual chat queries.
        With stage 2, a casual greeting retrieves no beliefs unless beliefs
        about casual topics exist; a financial query retrieves only beliefs
        about money, goals, expenses; a "what do I do for fun" query retrieves
        beliefs about activities, hobbies, restaurants.
        """
        try:
            now = time.time()
            with self.open_db() as conn:
                rows = conn.execute(
                    "SELECT fact, confidence, last_seen FROM belief_graph "
                    "WHERE confidence > 0.20 ORDER BY last_seen DESC LIMIT 40"
                ).fetchall()
            if not rows:
                return ""

            # Stage 1: temporal decay
            decayed: list[tuple[float, str]] = []
            for fact, raw_conf, last_seen in rows:
                age_days = (now - float(last_seen)) / 86400.0
                eff_conf = float(raw_conf) * math.exp(-DECAY_LAMBDA * age_days)
                if eff_conf >= 0.20:
                    decayed.append((eff_conf, fact))
            if not decayed:
                return ""

            # Stage 2: relevance filtering by cosine similarity
            encoder = _get_shared_st_model() if _SHARED_ST_MODEL is not None else None
            if encoder is not None and query and query.strip():
                try:
                    import numpy as np
                    q_emb = encoder.encode(query, convert_to_numpy=True)
                    q_norm = float(np.linalg.norm(q_emb)) or 1.0
                    scored: list[tuple[float, float, str]] = []
                    for conf, fact in decayed:
                        f_emb = encoder.encode(fact, convert_to_numpy=True)
                        f_norm = float(np.linalg.norm(f_emb)) or 1.0
                        sim = float(np.dot(q_emb, f_emb) / (q_norm * f_norm))
                        if sim >= BELIEF_RELEVANCE_THRESHOLD:
                            scored.append((sim, conf, fact))
                    # Rank by combined score (similarity weighted by confidence)
                    scored.sort(key=lambda t: t[0] * t[1], reverse=True)
                    if not scored:
                        logger.info(
                            "[belief_retrieval] %d beliefs survived decay but none "
                            "passed relevance threshold (%.2f) for query: %.60s",
                            len(decayed), BELIEF_RELEVANCE_THRESHOLD, query,
                        )
                        return ""
                    logger.info(
                        "[belief_retrieval] %d relevant beliefs returned (of %d candidates).",
                        len(scored[:10]), len(decayed),
                    )
                    return "BELIEF GRAPH:\n" + "\n".join(
                        f"  [{conf:.2f} | rel {sim:.2f}] {fact}"
                        for sim, conf, fact in scored[:10]
                    )
                except Exception:
                    logger.warning(
                        "[belief_retrieval] Relevance scoring failed — falling back to confidence-only.",
                        exc_info=True,
                    )
                    # Fall through to confidence-only result below

            # Fallback: confidence-only ranking (encoder unavailable or scoring failed)
            decayed.sort(key=lambda x: x[0], reverse=True)
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
                        # Tag the fact with category labels from the taxonomy.
                        categories = ",".join(categorize_text(fact))
                        row = conn.execute("SELECT id, confidence FROM belief_graph WHERE fact=?", (fact,)).fetchone()
                        if row:
                            confidence = max(0.0, min(1.0, float(row[1]) + delta))
                            conn.execute(
                                "UPDATE belief_graph SET confidence=?, last_seen=?, source=?, categories=? WHERE id=?",
                                (confidence, time.time(), source, categories, row[0])
                            )
                        else:
                            conn.execute(
                                "INSERT INTO belief_graph (fact, confidence, last_seen, source, categories) VALUES (?,?,?,?,?)",
                                (fact, 0.58 if confirmed else 0.35, time.time(), source, categories)
                            )
                    conn.commit()
            except Exception:
                logger.warning("[update_belief_graph] DB write failed.", exc_info=True)

    # Minimum cosine similarity for a stored memory to be considered relevant
    # enough to surface in retrieval. Without this floor, ChromaDB returns the
    # top-N nearest matches even when they're only loosely related — causing
    # the model to reference unrelated past memories (e.g. 'hiking' surfacing
    # for a 'park' query) and produce contaminated responses.
    MEMORY_RELEVANCE_THRESHOLD = 0.45

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
                similarity = 1.0 - float(dist)                       # cosine distance → similarity
                # Skip memories below the relevance floor before even applying decay
                if similarity < self.MEMORY_RELEVANCE_THRESHOLD:
                    continue
                age_days = (now - float(meta.get("created_at_epoch", now))) / 86400
                score = similarity * math.exp(-DECAY_LAMBDA * age_days)
                scored.append((score, similarity, doc))
            if not scored:
                logger.info(
                    "[semantic_recall] %d candidates fetched but none passed relevance "
                    "threshold (%.2f) for query: %.60s",
                    len(docs), self.MEMORY_RELEVANCE_THRESHOLD, query,
                )
                return ""
            scored.sort(key=lambda item: item[0], reverse=True)
            logger.info(
                "[semantic_recall] Returning %d relevant memories (max similarity %.3f) for query: %.60s",
                min(limit, len(scored)), scored[0][1] if scored else 0.0, query,
            )
            return "SEMANTIC MEMORY:\n" + "\n---\n".join(d for _, _, d in scored[:limit])
        return await asyncio.to_thread(_query)

    async def semantic_write(self, user_input: str, output: str, thread_id: str) -> None:
        if self.chroma_collection is None: return
        # Categorize the memory before storing — produces multi-label tags from
        # the fixed taxonomy so future retrieval can filter or boost by category.
        # Categorize the USER INPUT only (not the assistant response) to mirror
        # the Fact Extractor's anti-amplification rule — we tag what the user
        # actually said, not what the model wrote about it.
        categories, ambiguous, suggested = categorize_with_confidence(user_input)
        # If the result is uncertain, mark it for user review and queue a question
        # rather than committing to a guess. Categories ["pending_review"] is a
        # sentinel value — retrieval filters can choose whether to include them.
        if ambiguous and not categories:
            categories_str = "pending_review"
        else:
            categories_str = ",".join(categories) if categories else "other"

        memory_id = str(uuid.uuid4())
        def _write():
            self.chroma_collection.add(
                documents=[f"User: {user_input[:400]} | LatticeD: {output[:800]}"],
                metadatas=[{
                    "user_id": INTERNAL_USER_ID,
                    "thread_id": thread_id,
                    "created_at_epoch": time.time(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "categories": categories_str,
                }],
                ids=[memory_id]
            )
        await asyncio.to_thread(_write)
        logger.info("[semantic_write] Memory stored — categories: [%s] (ambiguous=%s)", categories_str, ambiguous)

        # Queue a question when categorization is uncertain. The user answers
        # at their convenience via the Refine view — never blocks the pipeline.
        if ambiguous and suggested:
            await asyncio.to_thread(
                self.queue_category_question,
                memory_id, thread_id, user_input[:400],
                suggested, scores={c: s for c, s in suggested},
            )

    def queue_category_question(
        self,
        memory_id: str,
        thread_id: str,
        memory_preview: str,
        suggested: List[Tuple[str, float]],
        scores: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Add an ambiguous-categorization question to the pending queue. The user
        sees these in the Refine view and answers at their convenience. Their
        answer updates the memory's category tags and (in Phase 3) becomes a
        pattern rule the system learns from.
        """
        options = [c for c, _ in suggested[:4]]
        if not options:
            return
        question_text = (
            "I noticed this memory could fit a few categories. Which one matches best?"
        )
        try:
            with self.db_lock:
                with self.open_db() as conn:
                    conn.execute(
                        """
                        INSERT INTO pending_questions
                            (memory_id, thread_id, memory_preview, question_type,
                             question_text, options, scores_json, created_at, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                        """,
                        (
                            memory_id, thread_id, memory_preview, "category",
                            question_text, ",".join(options),
                            json.dumps(scores or {}), time.time(),
                        ),
                    )
                    conn.commit()
            logger.info(
                "[queue_category_question] Queued question for memory %s — options: %s",
                memory_id[:8], options,
            )
        except Exception:
            logger.warning("[queue_category_question] Failed to queue question.", exc_info=True)

    def answer_category_question(self, question_id: int, answer: str) -> Dict[str, Any]:
        """
        Apply the user's answer: update the memory's category tags in ChromaDB
        and mark the question as answered. Returns a status dict.
        """
        with self.db_lock:
            with self.open_db() as conn:
                row = conn.execute(
                    "SELECT memory_id, options, status FROM pending_questions WHERE id = ?",
                    (question_id,),
                ).fetchone()
                if not row:
                    return {"ok": False, "error": "Question not found"}
                memory_id, options_str, status = row
                if status != "pending":
                    return {"ok": False, "error": f"Question already {status}"}

                options = [o.strip() for o in (options_str or "").split(",") if o.strip()]
                if answer not in options and answer != "skip":
                    return {"ok": False, "error": f"Answer '{answer}' not in options {options}"}

                conn.execute(
                    "UPDATE pending_questions SET answered_at=?, answer=?, status=? WHERE id=?",
                    (time.time(), answer, "skipped" if answer == "skip" else "answered", question_id),
                )
                conn.commit()

        # If user actually chose a category (not skip), update the memory's ChromaDB metadata
        if answer != "skip" and memory_id and self.chroma_collection is not None:
            try:
                def _update():
                    self.chroma_collection.update(
                        ids=[memory_id],
                        metadatas=[{"categories": answer}],
                    )
                _update()
                logger.info(
                    "[answer_category_question] Memory %s re-tagged with category: %s",
                    memory_id[:8], answer,
                )
            except Exception:
                logger.warning("[answer_category_question] Failed to update memory.", exc_info=True)

        return {"ok": True, "memory_id": memory_id, "answer": answer}

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
    global INTENT_ENCODER, INTENT_ANCHOR_EMBEDDINGS, CATEGORY_ANCHOR_EMBEDDINGS
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
        # Pre-compute category anchor embeddings using the same shared encoder.
        # Reuses _SHARED_ST_MODEL — zero extra weight loading.
        CATEGORY_ANCHOR_EMBEDDINGS = {
            cat: INTENT_ENCODER.encode(text, convert_to_numpy=True)
            for cat, text in CATEGORY_ANCHORS_TEXT.items()
        }
        logger.info(
            "Category anchors ready — %d categories precomputed for memory tagging.",
            len(CATEGORY_ANCHOR_EMBEDDINGS)
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

def fast_fanout_node(state: SovereignState) -> dict:
    # Routing-only node. Echo execution_path so LangGraph's stream mode emits
    # an update event — otherwise empty-dict returns are filtered out and the
    # UI's pipeline visualization never lights this node up.
    return {"execution_path": state.get("execution_path", "fast")}

def deep_fanout_node(state: SovereignState) -> dict:
    # Same routing-only pattern as fast_fanout_node above.
    return {"execution_path": state.get("execution_path", "deep")}

async def memory_retrieval_node(state: SovereignState) -> dict:
    """
    Recall past conversation memories from ChromaDB scoped to this thread.

    Skipped for pure-chat prompts so previous casual exchanges don't bleed into
    each new message. With memory recall enabled on chat, a previous 'park'
    memory can surface for a 'dinner' query (cosine similarity stays high
    across short casual statements), causing the model to reference unrelated
    past context. Mirrors the belief_retrieval gating added earlier.
    """
    timer = PerfTimer("memory_retrieval")
    intent = (state.get("intent_category") or "").lower()
    path   = (state.get("execution_path")  or "").lower()

    if intent == "chat" or path == "fast":
        logger.info("[memory_retrieval] Skipped — intent=%s path=%s (light conversation)", intent, path)
        timer.stop()
        return {"retrieved_memory": ""}

    mem = await runtime.semantic_recall(state["user_input"], state.get("thread_id", "main"))
    timer.stop()
    return {"retrieved_memory": mem}

async def belief_retrieval_node(state: SovereignState) -> dict:
    """
    Pull verified facts from the belief graph that are RELEVANT to the current
    user query. The retrieval function (get_belief_context_sync) applies both
    temporal decay AND cosine-similarity relevance filtering — so casual chat
    queries naturally retrieve no off-topic financial beliefs, while a
    question like "what do I do for fun?" still retrieves activity-related
    beliefs from any past session.
    """
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
        # and only fall back to a very small pre-window (10 chars) if post is empty.
        # PRE radius reduced from 15 to 10 to prevent the previous amount's frequency
        # keyword from bleeding into this amount's window when amounts are close
        # together. Example: "$66,000 a year and pay $1,300" — "a year" sits 16 chars
        # before $1,300; a 15-char PRE would include it and misclassify $1,300 as
        # annual. 10-char PRE still catches "monthly $X" (8 chars) and "yearly $X"
        # (7 chars), which are the common leading-frequency forms.
        FREQ_POST_RADIUS = 30
        FREQ_PRE_RADIUS  = 10

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
        # IMPORTANT: extract facts ONLY from the user's own statement, NOT from the
        # assistant's response. Including the assistant output creates an amplification
        # loop — if the model produces a contaminated response (e.g. mentions a 529 plan
        # when the user never did), the Fact Extractor would store "user has 529 plan"
        # as a belief, which then re-contaminates every future query. Reading the user
        # input only breaks that cycle.
        extraction_context = (
            f"USER REQUEST: {state.get('user_input', '')[:400]}\n\n"
            "Extract only facts the USER explicitly stated. Do not infer goals, "
            "preferences, or financial details that were not literally said."
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
    # Non-empty return so LangGraph stream mode yields this node — without it,
    # the UI's pipeline visualization never sees the Artifact Writer activate.
    # Re-stating final_output is a benign no-op (same value, same key).
    return {"final_output": output}

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
        logger.info("LatticeD V3.1 Cognitive System Online.")
        yield
    finally:
        await checkpoint_cm.__aexit__(None, None, None)

app = FastAPI(title="LatticeD", lifespan=lifespan)

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

                    # Emit routing metadata as soon as intent_classifier resolves
                    # so the UI can show which path the pipeline took.
                    if node == "intent_classifier" and "execution_path" in update:
                        yield "data: " + json.dumps({
                            "phase":            "routing",
                            "execution_path":   update.get("execution_path", ""),
                            "intent_category":  update.get("intent_category", ""),
                            "route_reason":     update.get("route_reason", ""),
                        }) + "\n\n"
                    # Emit goal metadata when the math engine detects a financial goal
                    if node == "math_engine" and update.get("active_goal") and update.get("active_goal") != "default":
                        yield "data: " + json.dumps({
                            "phase":          "goal",
                            "active_goal":    update["active_goal"],
                        }) + "\n\n"
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
                        if node == "intent_classifier" and "execution_path" in update:
                            await websocket.send_json({
                                "phase":            "routing",
                                "execution_path":   update.get("execution_path", ""),
                                "intent_category":  update.get("intent_category", ""),
                                "route_reason":     update.get("route_reason", ""),
                            })
                        if node == "math_engine" and update.get("active_goal") and update.get("active_goal") != "default":
                            await websocket.send_json({
                                "phase":       "goal",
                                "active_goal": update["active_goal"],
                            })
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

@app.get("/api/questions/pending")
async def list_pending_questions(
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_authenticated_user),
):
    """List all questions waiting for the user's answer, newest first."""
    del user_id
    try:
        with runtime.open_db() as conn:
            rows = conn.execute(
                """
                SELECT id, memory_id, thread_id, memory_preview, question_type,
                       question_text, options, scores_json, created_at
                  FROM pending_questions
                 WHERE status = 'pending'
              ORDER BY created_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        questions = []
        for r in rows:
            qid, mem_id, thread_id, preview, qtype, qtext, opts_str, scores_json, created_at = r
            options = [o.strip() for o in (opts_str or "").split(",") if o.strip()]
            try:
                scores = json.loads(scores_json) if scores_json else {}
            except Exception:
                scores = {}
            questions.append({
                "id": int(qid),
                "memory_id": mem_id,
                "thread_id": thread_id,
                "memory_preview": preview or "",
                "question_type": qtype,
                "question_text": qtext or "",
                "options": options,
                "scores": scores,
                "created_at_epoch": float(created_at) if created_at else 0.0,
            })
        return {"questions": questions, "pending_count": len(questions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pending question list failed: {e}")

@app.get("/api/questions/count")
async def count_pending_questions(user_id: str = Depends(get_authenticated_user)):
    """Quick count of pending questions — used by the sidebar nav badge."""
    del user_id
    try:
        with runtime.open_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM pending_questions WHERE status='pending'"
            ).fetchone()[0]
        return {"pending_count": int(count)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pending question count failed: {e}")

@app.post("/api/questions/{question_id}/answer")
async def answer_question(
    question_id: int = ApiPath(..., ge=1),
    answer: str = Query(..., min_length=1, max_length=64),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Record the user's answer and apply it. If the answer is a category name from
    the offered options, the related memory's category tags are updated in
    ChromaDB. If the answer is 'skip', the question is marked skipped and
    nothing else changes.
    """
    del user_id
    try:
        result = await asyncio.to_thread(runtime.answer_category_question, question_id, answer)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Answer failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Answer failed: {e}")

@app.delete("/api/questions/{question_id}")
async def skip_question(
    question_id: int = ApiPath(..., ge=1),
    user_id: str = Depends(get_authenticated_user),
):
    """Skip a question without answering. Same effect as POST .../answer?answer=skip."""
    del user_id
    try:
        result = await asyncio.to_thread(runtime.answer_category_question, question_id, "skip")
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Skip failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Skip failed: {e}")

@app.get("/api/categorize")
async def categorize_endpoint(
    text: str = Query(..., min_length=2, max_length=2000),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Classify arbitrary text into one or more life-event categories using the
    hybrid scoring layer. Useful for UI debugging, eval harness verification,
    and confirming the categorization layer is operational. Returns the
    matched categories and the raw scores for transparency.
    """
    del user_id
    try:
        import numpy as np
        if not CATEGORY_ANCHOR_EMBEDDINGS:
            return {"categories": ["other"], "scores": {}, "ready": False}

        encoder = _get_shared_st_model() if _SHARED_ST_MODEL is not None else None
        if encoder is None:
            return {"categories": ["other"], "scores": {}, "ready": False}

        text_emb = encoder.encode(text, convert_to_numpy=True)
        text_norm = float(np.linalg.norm(text_emb)) or 1.0
        text_lower = text.lower()
        text_words = set(re.findall(r"[a-z0-9]+", text_lower))
        def _kw_match(kw: str) -> bool:
            return (kw in text_lower) if " " in kw else (kw in text_words)

        scores: Dict[str, Dict[str, float]] = {}
        for cat, anchor_emb in CATEGORY_ANCHOR_EMBEDDINGS.items():
            a_norm = float(np.linalg.norm(anchor_emb)) or 1.0
            emb_sim = float(np.dot(text_emb, anchor_emb) / (text_norm * a_norm))
            kws = CATEGORY_KEYWORDS.get(cat, set())
            if kws:
                hits = sum(1 for kw in kws if _kw_match(kw))
                kw_score = min(1.0, hits / CATEGORY_KEYWORD_SATURATION)
            else:
                kw_score = 0.0
            combined = (
                CATEGORY_HYBRID_EMB_WEIGHT     * emb_sim +
                CATEGORY_HYBRID_KEYWORD_WEIGHT * kw_score
            )
            scores[cat] = {
                "embedding_similarity": round(emb_sim, 4),
                "keyword_score":        round(kw_score, 4),
                "combined":             round(combined, 4),
            }

        categories = categorize_text(text)
        return {
            "text":      text,
            "categories": categories,
            "threshold": CATEGORY_MATCH_THRESHOLD,
            "weights":   {
                "embedding": CATEGORY_HYBRID_EMB_WEIGHT,
                "keyword":   CATEGORY_HYBRID_KEYWORD_WEIGHT,
            },
            "scores":    scores,
            "ready":     True,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Categorization failed: {e}")

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
                SELECT id, fact, confidence, last_seen, source, categories
                  FROM belief_graph
                 WHERE confidence > 0.20
                 ORDER BY last_seen DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        now = time.time()
        beliefs = []
        for bid, fact, raw_conf, last_seen, source, categories in rows:
            age_days = (now - float(last_seen)) / 86400.0
            eff_conf = float(raw_conf) * math.exp(-DECAY_LAMBDA * age_days)
            beliefs.append({
                "id":                 int(bid),
                "fact":               fact,
                "categories":         [c for c in (categories or "").split(",") if c],
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

@app.get("/api/cache")
async def list_cache_entries(
    limit: int = Query(50, ge=1, le=500),
    user_id: str = Depends(get_authenticated_user),
):
    """
    List entries in the semantic cache with their stored metadata.
    Used by the UI's Cache view to surface contamination and enable purge.
    """
    del user_id
    if runtime.semantic_cache_collection is None:
        return {"entries": [], "threshold": SEMANTIC_CACHE_THRESHOLD}
    try:
        def _fetch():
            return runtime.semantic_cache_collection.get(
                limit=limit,
                include=["documents", "metadatas"],
            )
        raw = await asyncio.to_thread(_fetch)
        ids = raw.get("ids", []) or []
        docs = raw.get("documents", []) or []
        metas = raw.get("metadatas", []) or []
        now = time.time()
        entries = []
        for i, cid in enumerate(ids):
            prompt = docs[i] if i < len(docs) else ""
            meta = metas[i] if i < len(metas) else {}
            cached_at = float(meta.get("cached_at", 0))
            ttl       = float(meta.get("ttl_seconds", CACHE_TTL_DEFAULT_SECONDS))
            age_sec   = (now - cached_at) if cached_at > 0 else None
            ttl_remaining = (ttl - age_sec) if age_sec is not None else None
            entries.append({
                "id":                cid,
                "prompt":            prompt or "",
                "response_preview":  (meta.get("response") or "")[:240],
                "intent":            meta.get("intent") or "",
                "cached_at_epoch":   cached_at,
                "age_seconds":       age_sec,
                "ttl_seconds":       ttl,
                "ttl_remaining_seconds": ttl_remaining,
                "expired":           (ttl_remaining is not None and ttl_remaining <= 0),
            })
        # Most recent first
        entries.sort(key=lambda e: e["cached_at_epoch"], reverse=True)
        return {"entries": entries, "threshold": SEMANTIC_CACHE_THRESHOLD}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cache list failed: {e}")

@app.delete("/api/cache")
async def forget_all_cache(
    confirm: bool = Query(False, description="Must be true to actually delete. Safety guard."),
    user_id: str = Depends(get_authenticated_user),
):
    """
    Bulk-delete every semantic cache entry. Useful for dev/test workflows
    where stale or contaminated cache entries are interfering with fresh runs.
    Beliefs and conversation memory are NOT touched — use their respective
    DELETE endpoints to wipe those.
    """
    del user_id
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Bulk cache delete requires ?confirm=true to execute.",
        )
    if runtime.semantic_cache_collection is None:
        return {"ok": True, "deleted_count": 0}
    try:
        def _purge():
            existing = runtime.semantic_cache_collection.get(include=[])
            ids = existing.get("ids", []) or []
            if ids:
                runtime.semantic_cache_collection.delete(ids=ids)
            return len(ids)
        count = await asyncio.to_thread(_purge)
        logger.warning("[forget_all_cache] Purged ALL cache entries: %d rows deleted.", count)
        return {"ok": True, "deleted_count": int(count)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk cache forget failed: {e}")

@app.delete("/api/cache/{cache_id}")
async def forget_cache_entry(
    cache_id: str,
    user_id: str = Depends(get_authenticated_user),
):
    """
    Delete a single cache entry by its ChromaDB document ID. Used by the UI's
    per-row Forget button on the Cache view.
    """
    del user_id
    if runtime.semantic_cache_collection is None:
        raise HTTPException(status_code=503, detail="Semantic cache not initialized.")
    try:
        def _delete():
            runtime.semantic_cache_collection.delete(ids=[cache_id])
        await asyncio.to_thread(_delete)
        logger.info("[forget_cache_entry] Purged cache id=%s", cache_id)
        return {"ok": True, "deleted_id": cache_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cache forget failed: {e}")

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

    # Bind configuration — defaults to localhost-only for safety.
    # Set LATTICED_HOST=0.0.0.0 to expose on the LAN (e.g. for phone testing).
    bind_host = os.getenv("LATTICED_HOST", "127.0.0.1").strip()
    bind_port = int(os.getenv("LATTICED_PORT", "8000"))

    logger.info("Initializing Uvicorn production engine on %s:%d ...", bind_host, bind_port)

    # Loud security warning if exposing to the network with the default secret
    if bind_host != "127.0.0.1" and ACTIVE_SECRET == DEFAULT_SECRET:
        warning = (
            "\n" + "!" * 72 + "\n"
            "!! SECURITY WARNING\n"
            f"!! Binding to {bind_host} exposes LatticeD beyond localhost,\n"
            "!! but LATTICED_SECRET is still the default value 'local_dev_secret_123'.\n"
            "!! ANYONE on this network can call the API with that key.\n"
            "!!\n"
            "!! Set a strong LATTICED_SECRET environment variable before exposing\n"
            "!! this service on any network with other devices on it.\n"
            + "!" * 72 + "\n"
        )
        logger.warning(warning)

    uvicorn.run(
        "latticed:app",
        host=bind_host,
        port=bind_port,
        reload=False,
        log_level="info"
    )
