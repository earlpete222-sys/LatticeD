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
from fastapi import Depends, FastAPI, Header, HTTPException, Path as ApiPath, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

try:
    from langchain_ollama import OllamaLLM
    OLLAMA_AVAILABLE = True
except ImportError:
    OllamaLLM = None
    OLLAMA_AVAILABLE = False

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
INTERNAL_USER_ID = os.getenv("EARL_USER_ID", "earl_prime")

MAX_PROMPT_CHARS = int(os.getenv("EARL_MAX_PROMPT_CHARS", "4000"))
MAX_DOC_CHARS = int(os.getenv("EARL_MAX_DOC_CHARS", "12000"))
THREAD_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
DECAY_LAMBDA = math.log(2) / 45

# Hardware profile settings optimized for low-overhead VRAM boundaries
MODEL_REASONING = "deepseek-r1:1.5b"  # Local reasoning engine with explicit internal thinking
MODEL_SYNTHESIS = "qwen2.5-coder:1.5b" # Fast structural translation, synthesis, and execution engine
OLLAMA_KEEP_ALIVE = "0"                 # Instantly unloads active model matrices from GPU allocation
OLLAMA_NUM_CTX = 3072                   # Controlled context space to safeguard against hardware crashes

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
    fast_generation: str
    core_generation: str
    strategy_plan: str
    tool_results: str
    tool_call_count: int
    audit_critique: str
    belief_conflicts: str
    guardian_decision: str
    loop_count: int
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
@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    display_name: str
    purpose: str
    model_name: str
    temperature: float
    max_tokens: int
    system_prompt: str

class AgentFactoryRegistry:
    def __init__(self):
        self.registry: Dict[str, AgentSpec] = {
            "intent_router": AgentSpec(
                agent_id="intent_router",
                display_name="Intent Router",
                purpose="Classifies upcoming processing streams into exact target modes.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.0,
                max_tokens=150,
                system_prompt="Classify the user input as exactly one word choice: TASK, RESEARCH, SHELL, or CHAT."
            ),
            "fast_mentor": AgentSpec(
                agent_id="fast_mentor",
                display_name="Fast Mentor",
                purpose="Handles light interactive chat utilizing interpersonal empathy and lifelong learning.",
                model_name=MODEL_REASONING,
                temperature=0.6,
                max_tokens=400,
                system_prompt=(
                    "You are Earl Prime in fast mode. Utilize Communication, Empathy, "
                    "and Relationship Building to provide a direct, human-centric solution."
                )
            ),
            "quant_architect": AgentSpec(
                agent_id="quant_architect",
                display_name="Quantitative Architect",
                purpose="Executes data calculations, programming frameworks, and core pattern analysis.",
                model_name=MODEL_REASONING,
                temperature=0.2,
                max_tokens=700,
                system_prompt=(
                    "You are the Quantitative Architect. Design the technical blueprint. "
                    "If you need real system information before finalizing, output EXACTLY: [SHELL: command]. "
                    "When you receive Tool Output, complete your strategy and DO NOT output [SHELL:] again."
                )
            ),
            "factual_auditor": AgentSpec(
                agent_id="factual_auditor",
                display_name="Factual Auditor",
                purpose="Audits draft accuracy using deep critical thinking and objective analysis.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.05,
                max_tokens=300,
                system_prompt=(
                    "You are the Factual Auditor. Review the strategy for logical flaws. "
                    "Return a clean JSON object ONLY: {\"validation_status\": \"PASSED\" or \"FAILED\", \"critique\": \"list of errors\"}"
                )
            ),
            "system_guardian": AgentSpec(
                agent_id="system_guardian",
                display_name="System Guardian",
                purpose="Reviews critical system risks to make strict behavioral gatekeeping decisions.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.0,
                max_tokens=100,
                system_prompt=(
                    "You are the System Guardian. If the auditor found severe errors, output exactly REJECT. "
                    "If correct, output exactly APPROVE. Do not write anything else."
                )
            ),
            "executive_arbiter": AgentSpec(
                agent_id="executive_arbiter",
                display_name="Executive Arbiter",
                purpose="Synthesizes the final approved technical plan into a cohesive production response.",
                model_name=MODEL_SYNTHESIS,
                temperature=0.05,
                max_tokens=800,
                system_prompt="You are the Executive Arbiter. Summarize and format the final approved strategy into a clean, comprehensive artifact."
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
        self.tavily_client: Any = None
        self.inference_sem: Optional[asyncio.Semaphore] = None
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

    def init_chroma(self) -> None:
        if not CHROMA_AVAILABLE: return
        try:
            import chromadb
            from chromadb.utils import embedding_functions
            embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self.chroma_collection = client.get_or_create_collection(
                name="end_game_lattice_cosine",
                embedding_function=embed_fn,
                metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            logger.exception("ChromaDB initialization variant failed.")

    def init_tavily(self) -> None:
        if TAVILY_AVAILABLE:
            from tavily import TavilyClient
            self.tavily_client = TavilyClient(api_key=TAVILY_KEY)

    async def execute_registry_inference(self, agent_id: str, context_package: str) -> str:
        """
        Executes sandboxed sub-model synthesis based strictly on the selected
        registry allocation template, forcing hardware memory cleanup loops.
        We use asyncio.to_thread to prevent blocking the WebSocket Heartbeat.
        """
        if self.inference_sem is None:
            self.inference_sem = asyncio.Semaphore(1)
            
        spec = self.factory.get_agent(agent_id)
        prompt_payload = f"<system>{spec.system_prompt}</system>\n\n[Context Blueprint]:\n{context_package}"
        
        llm = OllamaLLM(
            model=spec.model_name,
            options={
                "temperature": spec.temperature,
                "num_predict": spec.max_tokens,
                "num_ctx": OLLAMA_NUM_CTX,
                "keep_alive": OLLAMA_KEEP_ALIVE
            }
        )
        
        async with self.inference_sem:
            raw_response = await asyncio.to_thread(llm.invoke, prompt_payload)
            return raw_response.strip()

    def get_loyalty_weights(self) -> Dict[str, float]:
        fallback = {"family": 0.35, "reliability": 0.25, "learning": 0.20, "safety": 0.15, "speed": 0.05}
        try:
            with self.open_db() as conn:
                row = conn.execute("SELECT weights FROM loyalty_weights WHERE user_id=?", (INTERNAL_USER_ID,)).fetchone()
            return json.loads(row[0]) if row else fallback
        except Exception:
            return fallback

    def get_belief_context_sync(self, query: str) -> str:
        del query
        try:
            with self.open_db() as conn:
                rows = conn.execute(
                    "SELECT fact, confidence FROM belief_graph WHERE confidence > 0.35 ORDER BY confidence DESC, last_seen DESC LIMIT 10"
                ).fetchall()
            if not rows: return ""
            return "BELIEF GRAPH:\n" + "\n".join(f"  [{confidence:.2f}] {fact}" for fact, confidence in rows)
        except Exception:
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
            except Exception: pass

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
            except Exception: pass

    def log_hardware(self, node: str, latency_ms: int) -> None:
        with self.db_lock:
            try:
                with self.open_db() as conn:
                    conn.execute("INSERT INTO hardware_log (timestamp,node,latency_ms) VALUES (?,?,?)", (time.time(), node, latency_ms))
                    conn.commit()
            except Exception: pass

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
# LangGraph Core Execution Node Algorithms (V3.1 Self-Correcting)
# ---------------------------------------------------------------------
async def intent_classifier_node(state: SovereignState) -> dict:
    timer = PerfTimer("intent_classifier")
    text = state["user_input"]
    requested_path = state.get("requested_path", "auto")

    if re.search(r"https?://[^\s]+", text): intent = "web"
    elif re.search(r"\b(powershell|terminal|shell|command|get-process|get-service)\b", text, re.IGNORECASE): intent = "shell"
    else:
        raw = await runtime.execute_registry_inference("intent_router", text)
        intent = "research" if "RESEARCH" in raw.upper() else "chat"

    if requested_path in ("fast", "deep"): execution_path = requested_path
    elif intent in ("research", "web", "shell"): execution_path = "deep"
    else: execution_path = "fast"

    timer.stop()
    return {"intent_category": intent, "execution_path": execution_path, "route_reason": "Dynamic Classifier Matrix", "loop_count": 0, "tool_call_count": 0}

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
    
    if runtime.tavily_client is not None and state["intent_category"] == "web":
        try:
            res = await asyncio.to_thread(runtime.tavily_client.search, query, max_results=3)
            snippets = [item.get("content", "") for item in res.get("results", []) if item.get("content")]
            if snippets: parts.append("WEB CONTENT GROUNDING:\n" + "\n---\n".join(snippets))
        except Exception as e: parts.append(f"GROUNDING PATH ERROR: {e}")
        
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

async def sovereign_core_node(state: SovereignState) -> dict:
    """Architect node. Handles Context Pruning & Active Tool Feedback."""
    timer = PerfTimer("sovereign_core")
    loop = int(state.get("loop_count", 0)) + 1
    
    # Context Pruning: Only provide critique if we are in a correction loop
    critique_injection = ""
    if state.get("audit_critique"):
        critique_injection = f"\nPAST ERRORS TO FIX:\n{state['audit_critique']}\n"
    
    # Context Pruning: Only provide tool results if they were just requested
    tool_injection = ""
    if state.get("tool_results"):
        tool_injection = f"\nTOOL OUTPUT:\n{state['tool_results']}\n"

    payload = (
        f"SEMANTIC MEMORY ARCHIVE:\n{state.get('retrieved_memory', '')}\n\n"
        f"LIVE GROUNDING DATA:\n{state.get('grounding_context', '')}\n"
        f"{critique_injection}"
        f"{tool_injection}\n"
        f"OBJECTIVE EXECUTION TARGET: {state['user_input']}"
    )
    
    raw = await runtime.execute_registry_inference("quant_architect", payload)
    timer.stop()
    return {"core_generation": clean_model_text(raw), "strategy_plan": clean_model_text(raw), "loop_count": loop}

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
    """Reviews the Architect's strategy plan."""
    timer = PerfTimer("auditor")
    payload = f"GROUNDING REFERENCE:\n{state.get('grounding_context')}\n\nGENERATED TARGET DRAFT:\n{state.get('strategy_plan')}"
    raw = await runtime.execute_registry_inference("factual_auditor", payload)
    
    parsed = json_repair_middleware(raw, fallback_key="critique")
    status_flag = str(parsed.get("validation_status", "")).upper()
    critique = str(parsed.get("critique", raw.strip()))
    timer.stop()
    
    if "PASSED" in status_flag or ("PASSED" in raw.upper() and "FAILED" not in raw.upper()):
        return {"audit_critique": "", "belief_conflicts": ""}
    return {"audit_critique": critique, "belief_conflicts": critique}

async def guardian_node(state: SovereignState) -> dict:
    """Determines if the Architect needs to self-correct."""
    timer = PerfTimer("guardian")
    critique = state.get("audit_critique", "")
    if not critique:
        timer.stop()
        return {"guardian_decision": "approve"}
    raw = await runtime.execute_registry_inference("system_guardian", f"Critique list:\n{critique}")
    decision = "reject" if "REJECT" in raw.upper() else "approve"
    timer.stop()
    return {"guardian_decision": decision}

async def synthesis_node(state: SovereignState) -> dict:
    """Executive Arbiter: Synthesizes final response to user."""
    timer = PerfTimer("synthesis")
    if state.get("execution_path") == "fast":
        return {"final_output": state.get("fast_generation", "")}
        
    payload = f"ORIGINAL REQUEST: {state['user_input']}\n\nAPPROVED TECHNICAL STRATEGY:\n{state.get('strategy_plan')}"
    final = await runtime.execute_registry_inference("executive_arbiter", payload)
    timer.stop()
    return {"final_output": final.strip()}

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
    try: await asyncio.to_thread(_write)
    except Exception: pass

    if output:
        await runtime.semantic_write(state.get("user_input", ""), output, thread_id)
        facts = [line.strip() for line in output.split("\n") if len(line.strip()) > 30][:4]
        await asyncio.to_thread(runtime.update_belief_graph_sync, facts, True, "final_output")
    timer.stop()
    return {}

def clean_model_text(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

# ---------------------------------------------------------------------
# Graph Conditional Routing Functions (V3.1 Logic)
# ---------------------------------------------------------------------
def route_start(state: SovereignState) -> str: return "fast" if state.get("execution_path") == "fast" else "deep"
def route_after_barrier(state: SovereignState) -> str: return "fast" if state.get("execution_path") == "fast" else "deep"

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
    "intent_classifier": "intent_router", "fast_core": "fast_mentor",
    "sovereign_core": "quant_architect", "agency": "system_guardian", # Maps to general tool wrapper internally
    "auditor": "factual_auditor", "guardian": "system_guardian", 
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
    graph.add_conditional_edges("perception_barrier", route_after_barrier, {"fast": "fast_core", "deep": "sovereign_core"})
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
        "final_output": "", "loyalty_scores": {}, "loyalty_verdict": ""
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.validate_dependencies()
    runtime.validate_secret()
    runtime.init_storage()
    runtime.init_db()
    runtime.init_chroma()
    runtime.init_tavily()
    
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
    user_id: str = Depends(get_authenticated_user)
):
    del user_id
    req = ChatRequest(prompt=prompt, thread_id=thread_id, path=path)
    state = make_initial_state(req)
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    
    async def gen():
        started = time.time()
        accumulated = {}
        async for chunk in app.state.graph.astream(state, config):
            for node, update in chunk.items():
                accumulated.update(update)
                # Keep connection alive during model swap phases
                yield "data: " + json.dumps({"node": node, "agent": NODE_AGENT_MAP.get(node, node), "status": "running"}) + "\n\n"
        final_state = {**state, **accumulated}
        runtime.log_interaction(final_state, int((time.time() - started) * 1000))
        yield "data: " + json.dumps({"phase": "Final", "content": final_state.get("final_output", ""), "is_final": True}) + "\n\n"
        
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    api_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key") or ""
    if not hmac.compare_digest(str(api_key), ACTIVE_SECRET):
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
            accumulated = {}
            try:
                # Streaming with active thread offloading prevents iOS Safari timeouts
                async for chunk in app.state.graph.astream(state, config):
                    for node, update in chunk.items():
                        if not update: continue
                        accumulated.update(update)
                        await websocket.send_json({"node": node, "agent": NODE_AGENT_MAP.get(node, node), "status": "complete"})
            except Exception: continue

            final_state = {**state, **accumulated}
            runtime.log_interaction(final_state, int((time.time() - started) * 1000))
            await websocket.send_json({"phase": "Final", "content": final_state.get("final_output", ""), "is_final": True})
    finally: logger.info("Session disconnected safely.")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
