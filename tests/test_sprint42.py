"""Sprint 42 - Negotiator + First-Principles PersonaPacks tests."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

METHOD_IDS = {"negotiator", "first_principles"}


def _fresh_registry():
    reg = L.PersonaPackRegistry(Path("x.json"))
    L.register_seed_persona_packs(reg)
    return reg


def test_registered_via_seed_path():
    reg = _fresh_registry()
    check("method packs registered through seed boot path",
          METHOD_IDS.issubset(set(reg.packs)), f"got {sorted(reg.packs)}")
    check("off by default",
          all(not reg.packs[p].enabled for p in METHOD_IDS))


def test_direct_method_registration():
    reg = L.PersonaPackRegistry(Path("x.json"))
    L.register_method_persona_packs(reg)
    check("standalone registers both", METHOD_IDS.issubset(set(reg.packs)))


def test_total_pack_count_now_eleven():
    reg = _fresh_registry()
    check("11 packs total (6 seed + 3 power + 2 method)",
          len(reg.packs) == 11, f"got {len(reg.packs)}")


def test_negotiator_faithful_content():
    t = _fresh_registry().packs["negotiator"].agent_overlays["executive_arbiter"].lower()
    check("interest behind position", "interest" in t and "position" in t)
    check("label emotion", "label" in t)
    check("mirror", "mirror" in t)
    check("calibrated how/what questions", "how/what" in t or "calibrated" in t)
    check("BATNA / walk-away", "walk-away" in t)
    check("never split the difference", "split the difference" in t)


def test_negotiator_targets():
    p = _fresh_registry().packs["negotiator"]
    for a in ("executive_arbiter", "life_coach", "fast_mentor", "quant_architect"):
        check(f"negotiator targets {a}", a in p.agent_overlays)


def test_first_principles_faithful_content():
    t = _fresh_registry().packs["first_principles"].agent_overlays["executive_arbiter"].lower()
    check("strip to bedrock", "bedrock" in t)
    check("reason from fundamentals not analogy", "fundamentals" in t and "analogy" in t)
    check("challenge the premise", "premise" in t)
    check("contrarian question", "few would agree" in t)


def test_first_principles_targets():
    p = _fresh_registry().packs["first_principles"]
    for a in ("executive_arbiter", "quant_architect", "research_synthesizer", "life_coach"):
        check(f"first_principles targets {a}", a in p.agent_overlays)


def test_source_attribution():
    reg = _fresh_registry()
    check("negotiator cites Voss/Fisher",
          "Voss" in reg.packs["negotiator"].source)
    check("first_principles cites Thiel",
          "Thiel" in reg.packs["first_principles"].source)


def test_compact_overlays_short():
    reg = _fresh_registry()
    for pid in METHOD_IDS:
        p = reg.packs[pid]
        for agent_id in p.agent_overlays:
            out = p.overlay_text(agent_id, L.ModelTier.MINIMAL_GPU.value)
            check(f"{pid}/{agent_id} minimal overlay non-empty + <=240",
                  bool(out) and len(out) <= 240, f"len={len(out) if out else 0}")


def test_no_parrotable_quotes():
    reg = _fresh_registry()
    for pid in METHOD_IDS:
        p = reg.packs[pid]
        for text in {**p.agent_overlays, **p.agent_overlays_compact}.values():
            check(f"{pid}: no quoted example", '"' not in text)


def test_no_temp_offsets_out_of_bound():
    reg = _fresh_registry()
    for pid in METHOD_IDS:
        for off in reg.packs[pid].temperature_offsets.values():
            check(f"{pid} temp offset bounded", abs(off) <= L.PERSONA_TEMP_OFFSET_BOUND)


# ---------- end-to-end ----------
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


def test_ctx_negotiator_shapes_arbiter_preamble():
    tmp = Path(tempfile.mkdtemp(prefix="sp42_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        ctx.persona_packs.enable("negotiator")
        p = ctx.compose_preamble("executive_arbiter")
        check("negotiator overlay reaches arbiter",
              "ADVISOR LENS" in p and "walk-away" in p.lower(), f"tail={p[-250:]!r}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_ctx_first_principles_shapes_research():
    tmp = Path(tempfile.mkdtemp(prefix="sp42_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        ctx.persona_packs.enable("first_principles")
        p = ctx.compose_preamble("research_synthesizer")
        check("first_principles overlay reaches research_synthesizer",
              "ADVISOR LENS" in p and "assume" in p.lower(), f"tail={p[-250:]!r}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_both_stack_within_budget():
    tmp = Path(tempfile.mkdtemp(prefix="sp42_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        ctx.persona_packs.enable("negotiator")
        ctx.persona_packs.enable("first_principles")
        overlay = ctx.persona_packs.overlay_for("executive_arbiter",
                                                  ctx.profile.tier)
        check("stacked overlay within budget",
              len(overlay) <= L.PERSONA_OVERLAY_BUDGET_CHARS + 80,
              f"len={len(overlay)}")
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
        test_registered_via_seed_path,
        test_direct_method_registration,
        test_total_pack_count_now_eleven,
        test_negotiator_faithful_content,
        test_negotiator_targets,
        test_first_principles_faithful_content,
        test_first_principles_targets,
        test_source_attribution,
        test_compact_overlays_short,
        test_no_parrotable_quotes,
        test_no_temp_offsets_out_of_bound,
        test_ctx_negotiator_shapes_arbiter_preamble,
        test_ctx_first_principles_shapes_research,
        test_both_stack_within_budget,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 42 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
