"""Sprint 40 - seed PersonaPacks tests."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

SEED_IDS = {"carnegie_communicator", "graham_investor", "chhabra_allocator",
            "aurelius_stoic", "strategist", "greene_observer"}


def _fresh_registry():
    reg = L.PersonaPackRegistry(Path("x.json"))
    L.register_seed_persona_packs(reg)
    return reg


def test_all_six_registered():
    reg = _fresh_registry()
    check("all six seed packs registered",
          SEED_IDS.issubset(set(reg.packs)), f"got {sorted(reg.packs)}")
    check("none enabled by default",
          all(not p.enabled for p in reg.packs.values()))


def test_every_pack_has_source_attribution():
    reg = _fresh_registry()
    for pid in SEED_IDS:
        p = reg.packs[pid]
        check(f"{pid} cites a source", "—" in p.source and len(p.source) > 15,
              f"source={p.source!r}")
        check(f"{pid} has a description", len(p.description) > 20)


def test_every_overlay_has_compact_or_short_full():
    """Each agent overlay must be usable at minimal_gpu — either has a
    compact variant or a short-enough full text."""
    reg = _fresh_registry()
    for pid, p in reg.packs.items():
        for agent_id in p.agent_overlays:
            out = p.overlay_text(agent_id, L.ModelTier.MINIMAL_GPU.value)
            # aurelius is minimal_gpu-tier so returns full; others return
            # compact.  Either way must be non-empty and short.
            check(f"{pid}/{agent_id} minimal_gpu overlay non-empty",
                  bool(out), f"empty for {pid}/{agent_id}")
            check(f"{pid}/{agent_id} minimal_gpu overlay <= 240 chars",
                  len(out) <= 240, f"len={len(out)} for {pid}/{agent_id}")


def test_no_parrotable_quote_marks_in_overlays():
    """Sprint 36 lesson: no quoted scenario sentences the 1.5B can parrot."""
    reg = _fresh_registry()
    for pid, p in reg.packs.items():
        for agent_id, text in {**p.agent_overlays, **p.agent_overlays_compact}.items():
            check(f"{pid}/{agent_id} has no quoted example sentence",
                  '"' not in text and " — '" not in text,
                  f"quote found in {pid}/{agent_id}")


def test_carnegie_targets_conversational_agents():
    reg = _fresh_registry()
    p = reg.packs["carnegie_communicator"]
    check("carnegie -> fast_mentor + life_coach",
          set(p.agent_overlays) == {"fast_mentor", "life_coach"})


def test_graham_targets_decision_agents():
    reg = _fresh_registry()
    p = reg.packs["graham_investor"]
    check("graham hits architect",
          "quant_architect" in p.agent_overlays)
    check("graham hits research_synthesizer",
          "research_synthesizer" in p.agent_overlays)


def test_chhabra_buckets_present():
    reg = _fresh_registry()
    t = reg.packs["chhabra_allocator"].agent_overlays["quant_architect"]
    for bucket in ("Safety", "Market", "Aspirational"):
        check(f"chhabra names {bucket} bucket", bucket in t)


def test_greene_is_defensive_only():
    reg = _fresh_registry()
    p = reg.packs["greene_observer"]
    for agent_id, text in p.agent_overlays.items():
        lo = text.lower()
        check(f"greene/{agent_id} forbids manipulating others",
              "never coach the user to manipulate" in lo
              or "never teach the user to manipulate" in lo,
              f"missing guard in {agent_id}")
        check(f"greene/{agent_id} is protective-framed",
              "on them" in lo or "aimed at the user" in lo)


def test_aurelius_available_at_minimal_gpu():
    reg = _fresh_registry()
    p = reg.packs["aurelius_stoic"]
    check("aurelius min_tier is minimal_gpu",
          p.min_tier == L.ModelTier.MINIMAL_GPU.value)
    # At minimal_gpu it returns the FULL overlay (tier >= min_tier).
    out = p.overlay_text("life_coach", L.ModelTier.MINIMAL_GPU.value)
    check("aurelius full overlay applies at minimal_gpu",
          "control" in out.lower())


def test_temperature_offsets_within_bound():
    reg = _fresh_registry()
    for pid, p in reg.packs.items():
        for agent_id, off in p.temperature_offsets.items():
            check(f"{pid}/{agent_id} offset within +/-0.20",
                  abs(off) <= L.PERSONA_TEMP_OFFSET_BOUND)


# ---------- end-to-end via LatticeContext ----------
def _redirect_paths(tmp: Path) -> dict:
    keys = ["IDENTITY_PATH", "CURIOSITY_PATH", "VOICE_PROFILES_PATH",
            "CONTINUITY_PATH", "AUDIT_LOG_PATH", "BUSINESS_PATH",
            "PROMPT_EVOLUTION_PATH", "SNAPSHOTS_PATH", "ACTIVITY_PATH",
            "MOODS_PATH", "MILESTONES_PATH", "PERSONA_PACKS_PATH"]
    orig = {k: getattr(L, k) for k in keys}
    for k in keys:
        suffix = ".jsonl" if k in ("AUDIT_LOG_PATH", "ACTIVITY_PATH", "MOODS_PATH") else ".json"
        setattr(L, k, tmp / f"{k.lower()}{suffix}")
    return orig


def _restore(o):
    for k, v in o.items(): setattr(L, k, v)


def test_ctx_autoloads_seed_packs():
    tmp = Path(tempfile.mkdtemp(prefix="sp40_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        check("seed packs auto-registered at boot",
              SEED_IDS.issubset(set(ctx.persona_packs.packs)))
        check("all off by default at boot",
              len(ctx.persona_packs.enabled_packs()) == 0)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_ctx_enabled_pack_shapes_preamble():
    tmp = Path(tempfile.mkdtemp(prefix="sp40_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        ctx.persona_packs.enable("chhabra_allocator")
        p = ctx.compose_preamble("quant_architect")
        check("chhabra overlay reaches architect preamble",
              "Aspirational" in p and "ADVISOR LENS" in p, f"tail={p[-300:]!r}")
        # And an unrelated agent should NOT get it.
        p_router = ctx.compose_preamble("intent_router")
        check("router preamble unaffected by chhabra",
              "ADVISOR LENS" not in p_router)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_ctx_enabled_state_persists_across_boot():
    tmp = Path(tempfile.mkdtemp(prefix="sp40_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        ctx.persona_packs.enable("aurelius_stoic")
        ctx.save_all()
        ctx2 = L.LatticeContext.boot(user_id="t", tier_override="high")
        check("aurelius still enabled after reboot",
              ctx2.persona_packs.packs["aurelius_stoic"].enabled)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_all_six_registered,
        test_every_pack_has_source_attribution,
        test_every_overlay_has_compact_or_short_full,
        test_no_parrotable_quote_marks_in_overlays,
        test_carnegie_targets_conversational_agents,
        test_graham_targets_decision_agents,
        test_chhabra_buckets_present,
        test_greene_is_defensive_only,
        test_aurelius_available_at_minimal_gpu,
        test_temperature_offsets_within_bound,
        test_ctx_autoloads_seed_packs,
        test_ctx_enabled_pack_shapes_preamble,
        test_ctx_enabled_state_persists_across_boot,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 40 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
