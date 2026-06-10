"""
Sprint 0 Step 7 — profile validator + consensus enforcement tests.

Runs standalone (no server, no Ollama) so it can serve as the always-on
Sprint 0 regression check. Exit code 0 = all pass; non-zero = at least
one test failed.

Usage:
    python tests/test_sprint0.py
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Allow `import latticed` when run from repo root.
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "latticed"))

import latticed as L  # noqa: E402


# ---------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------
PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, PASS if cond else FAIL, detail))


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------
def test_hardware_profile_detect_returns_valid_tier() -> None:
    p = L.hardware_profile_detect()
    check(
        "hardware_profile_detect returns a known tier",
        p.tier in {t.value for t in L.ModelTier},
        f"got tier={p.tier}",
    )
    check(
        "detected profile has >= 1 available model",
        len(p.available_models) >= 1,
        f"available_models={p.available_models}",
    )


def test_force_tier_via_arg() -> None:
    p = L.hardware_profile_detect(force_tier="standard")
    check("force_tier='standard' loads STANDARD profile",
          p.tier == L.ModelTier.STANDARD.value, f"got {p.tier}")


def test_env_tier_override() -> None:
    os.environ["LATTICED_TIER"] = "high"
    try:
        p = L.hardware_profile_detect()
        check("LATTICED_TIER=high overrides detection",
              p.tier == L.ModelTier.HIGH.value, f"got {p.tier}")
    finally:
        del os.environ["LATTICED_TIER"]


def test_minimal_gpu_profile_validates_with_warnings() -> None:
    """MINIMAL_GPU passes pool-level validation (architect pool declares
    cross-family target), but research_synthesizer's triangulation
    requirement cannot be fully satisfied with only two families - this
    is the expected surfaced warning."""
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    agents = L.AgentFactoryRegistry().registry
    rep = L.validate_profile_against_agents(p, agents, strict=True)
    check("MINIMAL_GPU passes strict validation (valid=True)", rep.valid,
          f"errors={rep.errors}")
    # Triangulation needs 3 families; MINIMAL_GPU has 2 - must be flagged.
    triangulation_warned = any(
        "research_synthesizer" in w and "triangulation" in w for w in rep.warnings
    )
    check("MINIMAL_GPU surfaces research_synthesizer triangulation gap as WARN",
          triangulation_warned, f"warnings={rep.warnings}")


def test_standard_profile_validates_clean() -> None:
    p = L.hardware_profile_detect(force_tier="standard")
    agents = L.AgentFactoryRegistry().registry
    # On STANDARD, architect pair pools are different families - no warning expected.
    rep = L.validate_profile_against_agents(p, agents, strict=True)
    check("STANDARD profile is valid", rep.valid, f"errors={rep.errors}")
    arch_err = any("quant_architect" in e for e in rep.errors)
    check("STANDARD profile has no architect-pair ERROR",
          not arch_err, f"errors={rep.errors}")


def test_validator_rejects_single_family_profile() -> None:
    """Two-model minimum: a synthetic single-family profile must fail."""
    bad = L.HardwareProfile(
        tier=L.ModelTier.STANDARD.value,
        detected_vram_gb=10.0,
        detected_ram_gb=32.0,
        available_models=["qwen2.5-coder:7b", "qwen2.5-coder:14b"],  # SAME family
    )
    agents = L.AgentFactoryRegistry().registry
    rep = L.validate_profile_against_agents(bad, agents, strict=True)
    check("single-family profile flagged INVALID",
          not rep.valid and any("two-model minimum" in e for e in rep.errors),
          f"valid={rep.valid} errors={rep.errors}")


def test_validator_flags_same_family_adversarial_pair_above_minimal() -> None:
    """Above MINIMAL_GPU, a same-family adversarial pair must be an ERROR."""
    profile = L.HardwareProfile(
        tier=L.ModelTier.STANDARD.value,
        detected_vram_gb=10.0,
        detected_ram_gb=32.0,
        available_models=["qwen2.5-coder:7b", "deepseek-r1:7b"],  # diversity OK at profile level
    )
    # Synthesize a registry where conservative + explore SHARE the qwen family at STANDARD.
    factory = L.AgentFactoryRegistry()
    agents = factory.registry
    agents["quant_architect_explore"].model_pool_per_tier[L.ModelTier.STANDARD.value] = ["qwen2.5-coder:7b"]
    agents["quant_architect"].model_pool_per_tier[L.ModelTier.STANDARD.value]         = ["qwen2.5-coder:7b"]
    rep = L.validate_profile_against_agents(profile, agents, strict=True)
    check("same-family adversarial pair above MINIMAL_GPU is an ERROR",
          not rep.valid and any("same model family" in e.lower() for e in rep.errors),
          f"valid={rep.valid} errors={rep.errors}")


def test_apply_profile_overrides() -> None:
    factory = L.AgentFactoryRegistry()
    agents = factory.registry
    before = agents["system_guardian"].consensus_requirement
    p = L.hardware_profile_detect(force_tier="high")
    L.apply_profile_overrides(p, agents)
    after = agents["system_guardian"].consensus_requirement
    check("HIGH profile bumps system_guardian consensus to triangulation",
          before != after and after == L.ConsensusRequirement.TRIANGULATION_REQUIRED.value,
          f"before={before} after={after}")


def test_enforce_consensus_single_model() -> None:
    chosen, agreed, _ = L.enforce_consensus(["alpha"], L.ConsensusRequirement.SINGLE_MODEL.value)
    check("SINGLE_MODEL: returns the only candidate", chosen == "alpha" and agreed)


def test_enforce_consensus_pair_agreement() -> None:
    chosen, agreed, _ = L.enforce_consensus(
        ["The answer is 42.", "The answer is 42.", "Different output."],
        L.ConsensusRequirement.PAIR_AGREEMENT.value,
    )
    check("PAIR_AGREEMENT: two matching candidates yield consensus",
          agreed and chosen.strip() == "The answer is 42.",
          f"chosen={chosen!r} agreed={agreed}")


def test_enforce_consensus_triangulation_fails_gracefully() -> None:
    chosen, agreed, why = L.enforce_consensus(
        ["alpha", "beta", "gamma"],
        L.ConsensusRequirement.TRIANGULATION_REQUIRED.value,
    )
    check("TRIANGULATION: total disagreement returns agreed=False with summary",
          (not agreed) and ("largest cluster" in why),
          f"agreed={agreed} why={why}")


def test_enforce_consensus_supermajority() -> None:
    chosen, agreed, _ = L.enforce_consensus(
        ["yes", "yes", "yes", "no", "no"],  # 3-of-5 = 60% threshold
        L.ConsensusRequirement.SUPERMAJORITY.value,
    )
    check("SUPERMAJORITY: 3-of-5 same answer reaches consensus",
          agreed and chosen == "yes",
          f"chosen={chosen} agreed={agreed}")


def test_surface_disagreement_format() -> None:
    msg = L.surface_disagreement([("deepseek-r1", "answer A"), ("qwen2.5-coder", "answer B")])
    check("surface_disagreement shows both model names + texts",
          "deepseek-r1" in msg and "qwen2.5-coder" in msg
          and "answer A" in msg and "answer B" in msg,
          f"msg={msg[:120]!r}")


def test_fingerprint_vector_shape() -> None:
    v_empty = L._fingerprint_response_vector("")
    v_short = L._fingerprint_response_vector("Paris.")
    v_code  = L._fingerprint_response_vector("```python\ndef f(): return 1\n```")
    check("fingerprint vector is 8-dim",
          len(v_empty) == 8 and len(v_short) == 8 and len(v_code) == 8)
    check("very-brief flag triggers on short answer", v_short[1] == 1.0)
    check("code flag triggers on code-shaped output", v_code[6] == 1.0)


def test_model_diversity_score_bounds() -> None:
    fp_same = {"x": [1.0, 0.0, 1.0]}
    fp_opp  = {"x": [0.0, 1.0, 0.0]}
    d_same  = L.model_diversity_score(fp_same, fp_same)
    d_opp   = L.model_diversity_score(fp_same, fp_opp)
    check("diversity(model, itself) is ~0", d_same < 0.001, f"d_same={d_same}")
    check("diversity(orthogonal vectors) is ~1", d_opp > 0.99, f"d_opp={d_opp}")


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------
def main() -> int:
    tests = [
        test_hardware_profile_detect_returns_valid_tier,
        test_force_tier_via_arg,
        test_env_tier_override,
        test_minimal_gpu_profile_validates_with_warnings,
        test_standard_profile_validates_clean,
        test_validator_rejects_single_family_profile,
        test_validator_flags_same_family_adversarial_pair_above_minimal,
        test_apply_profile_overrides,
        test_enforce_consensus_single_model,
        test_enforce_consensus_pair_agreement,
        test_enforce_consensus_triangulation_fails_gracefully,
        test_enforce_consensus_supermajority,
        test_surface_disagreement_format,
        test_fingerprint_vector_shape,
        test_model_diversity_score_bounds,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            results.append((t.__name__, FAIL, f"EXC {type(e).__name__}: {e}"))

    pass_count = sum(1 for _, s, _ in results if s == PASS)
    total = len(results)
    for name, status, detail in results:
        marker = "[OK]  " if status == PASS else "[XX]  "
        line = f"{marker}{name}"
        if detail:
            line += f"   - {detail}"
        print(line)
    print(f"\n{pass_count}/{total} Sprint 0 tests passed.")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
