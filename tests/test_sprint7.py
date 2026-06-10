"""Sprint 7 - Performance + Phase 2 Model Intelligence tests. Standalone."""
from __future__ import annotations
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


# ---------- PerformanceLog ----------
def test_perf_log_ring_buffer():
    plog = L.PerformanceLog(ring_size=5)
    for i in range(10):
        plog.record("nodeA", float(i * 10))
    check("ring buffer trims to ring_size", len(plog.samples) == 5,
          f"got {len(plog.samples)}")


def test_perf_log_aggregate():
    plog = L.PerformanceLog()
    for ms in [10.0, 20.0, 30.0, 40.0, 50.0]:
        plog.record("synth", ms)
    agg = plog.aggregate("synth")
    check("count = 5", agg["count"] == 5)
    check("mean = 30", agg["mean"] == 30.0, f"got {agg}")
    check("p50 around middle", 20.0 <= agg["p50"] <= 40.0, f"got {agg['p50']}")


def test_perf_slowest_nodes():
    plog = L.PerformanceLog()
    plog.record("fast", 5.0); plog.record("fast", 6.0)
    plog.record("slow", 500.0); plog.record("slow", 400.0)
    plog.record("medium", 100.0)
    top = plog.slowest_nodes(top_k=3)
    check("slowest first", top[0][0] == "slow", f"got {top}")
    check("medium second", top[1][0] == "medium")


# ---------- Model scoring ----------
def _fake_fingerprint(axis_strengths: dict) -> dict:
    """Build a fingerprint where each axis vector averages to the requested strength."""
    return {axis: [strength] * 8 for axis, strength in axis_strengths.items()}


def test_score_model_no_fingerprint_neutral():
    spec = L.AgentSpec(
        agent_id="x", display_name="x", purpose="x",
        model_name="m", temperature=0.0, max_tokens=10, system_prompt="x",
        capabilities_required={L.Capability.STRUCTURED_OUTPUT.value: L.CapabilityLevel.STRONG.value},
    )
    score, _ = L.score_model_for_agent("missing", spec, {})
    check("missing fingerprint -> neutral 0.5", score == 0.5)


def test_score_model_meets_strong_requirement():
    spec = L.AgentSpec(
        agent_id="x", display_name="x", purpose="x",
        model_name="m", temperature=0.0, max_tokens=10, system_prompt="x",
        capabilities_required={L.Capability.STRUCTURED_OUTPUT.value: L.CapabilityLevel.STRONG.value},
    )
    fp = _fake_fingerprint({"structured_output": 0.9})
    sc, notes = L.score_model_for_agent("good", spec, {"good": fp})
    check("model meeting STRONG requirement scores > 0.7",
          sc > 0.7, f"got {sc} notes={notes}")


def test_score_model_misses_required():
    spec = L.AgentSpec(
        agent_id="x", display_name="x", purpose="x",
        model_name="m", temperature=0.0, max_tokens=10, system_prompt="x",
        capabilities_required={L.Capability.STRUCTURED_OUTPUT.value: L.CapabilityLevel.STRONG.value},
    )
    fp = _fake_fingerprint({"structured_output": 0.1})  # weak
    sc, _ = L.score_model_for_agent("weak", spec, {"weak": fp})
    check("model missing STRONG requirement scores low",
          sc < 0.4, f"got {sc}")


def test_score_model_avoid_hard_excludes():
    spec = L.AgentSpec(
        agent_id="x", display_name="x", purpose="x",
        model_name="m", temperature=0.0, max_tokens=10, system_prompt="x",
        capabilities_avoid=[L.Capability.CREATIVE_GENERATION.value],
    )
    fp = _fake_fingerprint({"creative_generation": 0.85})
    sc, notes = L.score_model_for_agent("creative", spec, {"creative": fp})
    check("AVOID hit -> hard exclusion (-1.0)",
          sc == -1.0, f"got {sc} notes={notes}")


def test_select_model_for_agent_picks_best():
    spec = L.AgentSpec(
        agent_id="x", display_name="x", purpose="x",
        model_name="default", temperature=0.0, max_tokens=10, system_prompt="x",
        capabilities_required={L.Capability.STRUCTURED_OUTPUT.value: L.CapabilityLevel.STRONG.value},
        model_pool_per_tier={
            L.ModelTier.STANDARD.value: ["weak-model", "good-model"],
        },
    )
    profile = L.HardwareProfile(
        tier=L.ModelTier.STANDARD.value, detected_vram_gb=10.0, detected_ram_gb=32.0,
        available_models=["weak-model", "good-model"],
    )
    fps = {
        "weak-model": _fake_fingerprint({"structured_output": 0.1}),
        "good-model": _fake_fingerprint({"structured_output": 0.9}),
    }
    picked, score, _ = L.select_model_for_agent(spec, profile, fps)
    check("selector picks the strong model", picked == "good-model",
          f"picked={picked} score={score}")


def test_select_model_falls_back_when_no_fingerprints():
    spec = L.AgentSpec(
        agent_id="x", display_name="x", purpose="x",
        model_name="default", temperature=0.0, max_tokens=10, system_prompt="x",
        model_pool_per_tier={L.ModelTier.MINIMAL_GPU.value: ["m1", "m2"]},
    )
    profile = L.HardwareProfile(
        tier=L.ModelTier.MINIMAL_GPU.value, detected_vram_gb=4.0, detected_ram_gb=16.0,
        available_models=["m1", "m2"],
    )
    picked, _, notes = L.select_model_for_agent(spec, profile, fingerprints=None)
    check("no fingerprints -> first-in-pool fallback", picked == "m1",
          f"picked={picked} notes={notes}")


def test_select_model_empty_pool_falls_back_to_model_name():
    spec = L.AgentSpec(
        agent_id="x", display_name="x", purpose="x",
        model_name="default-fallback", temperature=0.0, max_tokens=10, system_prompt="x",
        model_pool_per_tier={},
    )
    profile = L.HardwareProfile(
        tier=L.ModelTier.MINIMAL_GPU.value, detected_vram_gb=0.0, detected_ram_gb=0.0,
        available_models=["x"],
    )
    picked, _, _ = L.select_model_for_agent(spec, profile, fingerprints={})
    check("empty pool falls back to model_name",
          picked == "default-fallback", f"picked={picked}")


# ---------- Speculative brancher ----------
def test_brancher_picks_longest_by_default():
    b1 = L.SpeculativeBranch(model_name="m1", output="short", latency_ms=100)
    b2 = L.SpeculativeBranch(model_name="m2", output="a much longer output", latency_ms=200)
    sb = L.SpeculativeBrancher()
    winner = sb.pick([b1, b2])
    check("default scorer picks longest", winner.model_name == "m2",
          f"picked={winner.model_name}")


def test_brancher_latency_weighted():
    b_fast = L.SpeculativeBranch(model_name="fast", output="a" * 50, latency_ms=50)
    b_slow = L.SpeculativeBranch(model_name="slow", output="a" * 60, latency_ms=5000)
    sb = L.SpeculativeBrancher(scorer=L.SpeculativeBrancher.latency_weighted_scorer(weight=0.01))
    winner = sb.pick([b_fast, b_slow])
    check("latency-weighted scorer prefers fast despite slightly shorter output",
          winner.model_name == "fast", f"picked={winner.model_name}")


def test_brancher_empty_list_returns_none():
    sb = L.SpeculativeBrancher()
    check("empty list -> None", sb.pick([]) is None)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_perf_log_ring_buffer,
        test_perf_log_aggregate,
        test_perf_slowest_nodes,
        test_score_model_no_fingerprint_neutral,
        test_score_model_meets_strong_requirement,
        test_score_model_misses_required,
        test_score_model_avoid_hard_excludes,
        test_select_model_for_agent_picks_best,
        test_select_model_falls_back_when_no_fingerprints,
        test_select_model_empty_pool_falls_back_to_model_name,
        test_brancher_picks_longest_by_default,
        test_brancher_latency_weighted,
        test_brancher_empty_list_returns_none,
        test_no_regression,
    ]
    for t in tests:
        try: t()
        except Exception as e: results.append((t.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 7 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
