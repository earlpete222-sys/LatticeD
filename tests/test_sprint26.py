"""Sprint 26 - runtime hookup tests (LatticeContext into EarlRuntime).

These tests stub the LLM inference path (OllamaLLM / ollama_client) so we
can verify the hookup behavior without needing a running Ollama server.
"""
from __future__ import annotations
import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _redirect_paths(tmp: Path) -> dict:
    keys = ["IDENTITY_PATH", "CURIOSITY_PATH", "VOICE_PROFILES_PATH",
            "CONTINUITY_PATH", "AUDIT_LOG_PATH", "BUSINESS_PATH",
            "PROMPT_EVOLUTION_PATH", "SNAPSHOTS_PATH", "ACTIVITY_PATH",
            "MOODS_PATH", "MILESTONES_PATH"]
    orig = {k: getattr(L, k) for k in keys}
    for k in keys:
        suffix = ".jsonl" if k in ("AUDIT_LOG_PATH", "ACTIVITY_PATH", "MOODS_PATH") else ".json"
        setattr(L, k, tmp / f"{k.lower()}{suffix}")
    return orig


def _restore(o):
    for k, v in o.items(): setattr(L, k, v)


def _fresh_runtime() -> "L.EarlRuntime":
    L.install_encrypted_persistence(None)
    return L.EarlRuntime()


# ---------- activation gating ----------
def test_runtime_starts_without_lattice_ctx_by_default():
    rt = _fresh_runtime()
    check("default runtime has lattice_ctx=None",
          rt.lattice_ctx is None)


def test_init_storage_does_not_activate_without_env_flag():
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    os.environ.pop("LATTICED_ACTIVATE", None)
    try:
        rt = _fresh_runtime()
        rt.init_storage()
        check("env unset -> lattice_ctx stays None",
              rt.lattice_ctx is None)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_init_storage_activates_when_env_flag_set():
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    os.environ["LATTICED_ACTIVATE"] = "1"
    os.environ["LATTICED_TIER"] = "minimal_gpu"
    try:
        rt = _fresh_runtime()
        rt.init_storage()
        check("env=1 -> lattice_ctx populated", rt.lattice_ctx is not None)
        if rt.lattice_ctx is not None:
            check("ctx.profile.tier matches override",
                  rt.lattice_ctx.profile.tier == "minimal_gpu")
            check("runtime.factory swapped to ctx.factory",
                  rt.factory is rt.lattice_ctx.factory)
    finally:
        os.environ.pop("LATTICED_ACTIVATE", None)
        os.environ.pop("LATTICED_TIER", None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_explicit_activate_lattice_idempotent():
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    try:
        rt = _fresh_runtime()
        c1 = rt.activate_lattice(user_id="bob", tier_override="minimal_gpu")
        c2 = rt.activate_lattice(user_id="bob", tier_override="minimal_gpu")
        check("activate_lattice returns a context", c1 is not None)
        check("second call returns same instance (idempotent)",
              c1 is c2)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_activate_lattice_failure_does_not_crash():
    """Force a boot failure (bad tier) and confirm the runtime falls through."""
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    try:
        rt = _fresh_runtime()
        # Stub LatticeContext.boot to raise.
        with patch.object(L.LatticeContext, "boot", side_effect=RuntimeError("forced")):
            out = rt.activate_lattice()
        check("failed activation returns None",
              out is None and rt.lattice_ctx is None)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- preamble injection in execute_registry_inference ----------
def _stub_ollama_llm(captured: dict):
    """Build a MagicMock OllamaLLM that captures the prompt and returns canned."""
    class _Stub:
        def __init__(self, *a, **kw): pass
        def invoke(self, prompt):
            captured["prompt"] = prompt
            return " stubbed response"
    return _Stub


def test_legacy_runtime_preamble_is_not_injected():
    """No lattice_ctx -> prompt_payload contains the agent's plain system_prompt."""
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    captured: dict = {}
    try:
        rt = _fresh_runtime()
        # Force the FREE-FORM path (fast_mentor has no output_schema).
        with patch.object(L, "OllamaLLM", _stub_ollama_llm(captured)), \
             patch.object(L, "OLLAMA_DIRECT_AVAILABLE", False):
            asyncio.run(rt.execute_registry_inference("fast_mentor", "Hi."))
        check("plain runtime: no preamble in prompt",
              "USER NORTH STARS" not in captured["prompt"]
              and "USER MOOD CONTEXT" not in captured["prompt"]
              and "ACTIVE MILESTONES" not in captured["prompt"],
              f"prompt[:300]={captured['prompt'][:300]!r}")
        check("plain runtime: agent's system_prompt still present",
              "LatticeD" in captured["prompt"] or "Fast Mentor" in captured["prompt"]
              or "thoughtful, curious personal companion" in captured["prompt"])
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_activated_runtime_injects_preamble_into_prompt():
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    captured: dict = {}
    try:
        rt = _fresh_runtime()
        rt.activate_lattice(user_id="t", tier_override="minimal_gpu")
        # Seed identity so the preamble is non-empty.
        rt.lattice_ctx.identity.add_fact("My wife is a high school teacher.",
                                          domain=L.LifeDomain.RELATIONSHIPS.value,
                                          confidence=0.95)
        rt.lattice_ctx.identity.add_north_star("Be a present partner.",
                                                 domain=L.LifeDomain.RELATIONSHIPS.value,
                                                 weight=1.5)
        with patch.object(L, "OllamaLLM", _stub_ollama_llm(captured)), \
             patch.object(L, "OLLAMA_DIRECT_AVAILABLE", False):
            asyncio.run(rt.execute_registry_inference("life_coach", "How was your day?"))
        prompt = captured["prompt"]
        check("activated runtime: north star surfaces in prompt",
              "present partner" in prompt.lower(),
              f"prompt[:600]={prompt[:600]!r}")
        check("activated runtime: fact surfaces in prompt",
              "teacher" in prompt.lower())
        check("preamble appears BEFORE the original system prompt",
              prompt.find("USER NORTH STARS") < prompt.find("the user's life coach"))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_activated_runtime_preamble_empty_for_router():
    """intent_router has no salience policy entries -> preamble stays empty
    even when activated.  Schema-constrained behavior is unchanged."""
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    captured: dict = {}
    try:
        rt = _fresh_runtime()
        rt.activate_lattice(user_id="t", tier_override="minimal_gpu")
        rt.lattice_ctx.identity.add_fact("private fact.", confidence=0.9)
        with patch.object(L, "OllamaLLM", _stub_ollama_llm(captured)), \
             patch.object(L, "OLLAMA_DIRECT_AVAILABLE", False):
            asyncio.run(rt.execute_registry_inference("intent_router", "ping"))
        prompt = captured["prompt"]
        check("router prompt excludes identity blocks",
              "USER NORTH STARS" not in prompt
              and "WHAT YOU KNOW ABOUT THE USER" not in prompt
              and "private fact" not in prompt,
              f"prompt[:300]={prompt[:300]!r}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_activated_runtime_records_turn_signals():
    """After inference, voice profile + perf log + memory should pick up
    a signal."""
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    captured: dict = {}
    try:
        rt = _fresh_runtime()
        rt.activate_lattice(user_id="t", tier_override="minimal_gpu")
        with patch.object(L, "OllamaLLM", _stub_ollama_llm(captured)), \
             patch.object(L, "OLLAMA_DIRECT_AVAILABLE", False):
            asyncio.run(rt.execute_registry_inference("fast_mentor", "Hey."))
        ctx = rt.lattice_ctx
        check("voice profile created for fast_mentor",
              "fast_mentor" in ctx.voice.profiles)
        check("perf log captured one sample",
              len(ctx.perf.samples) == 1
              and ctx.perf.samples[0].node == "fast_mentor")
        check("episodic memory captured response",
              len(ctx.memory.records) == 1)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_preamble_compose_failure_falls_through():
    """If compose_preamble raises, the call must still return a stripped response,
    not crash."""
    tmp = Path(tempfile.mkdtemp(prefix="sp26_"))
    orig = _redirect_paths(tmp)
    captured: dict = {}
    try:
        rt = _fresh_runtime()
        rt.activate_lattice(user_id="t", tier_override="minimal_gpu")
        # Force compose_preamble to raise.
        rt.lattice_ctx.compose_preamble = MagicMock(side_effect=RuntimeError("boom"))
        with patch.object(L, "OllamaLLM", _stub_ollama_llm(captured)), \
             patch.object(L, "OLLAMA_DIRECT_AVAILABLE", False):
            out = asyncio.run(rt.execute_registry_inference("fast_mentor", "Hey."))
        check("inference returns stripped response despite compose error",
              out == "stubbed response", f"got {out!r}")
        check("prompt still contains the legacy system block",
              "thoughtful, curious personal companion" in captured["prompt"])
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- regression ----------
def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_runtime_starts_without_lattice_ctx_by_default,
        test_init_storage_does_not_activate_without_env_flag,
        test_init_storage_activates_when_env_flag_set,
        test_explicit_activate_lattice_idempotent,
        test_activate_lattice_failure_does_not_crash,
        test_legacy_runtime_preamble_is_not_injected,
        test_activated_runtime_injects_preamble_into_prompt,
        test_activated_runtime_preamble_empty_for_router,
        test_activated_runtime_records_turn_signals,
        test_preamble_compose_failure_falls_through,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 26 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
