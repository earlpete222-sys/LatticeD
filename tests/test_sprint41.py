"""Sprint 41 - power PersonaPacks tests (Art of War, 48 Laws, Art of Seduction)."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

POWER_IDS = {"art_of_war", "laws_of_power", "art_of_seduction"}


def _fresh_registry():
    reg = L.PersonaPackRegistry(Path("x.json"))
    L.register_seed_persona_packs(reg)   # also calls register_power_persona_packs
    return reg


def test_all_three_registered_via_seed_path():
    reg = _fresh_registry()
    check("power packs registered through the seed boot path",
          POWER_IDS.issubset(set(reg.packs)), f"got {sorted(reg.packs)}")
    check("off by default",
          all(not reg.packs[p].enabled for p in POWER_IDS))


def test_direct_power_registration():
    reg = L.PersonaPackRegistry(Path("x.json"))
    L.register_power_persona_packs(reg)
    check("register_power_persona_packs standalone registers all three",
          POWER_IDS.issubset(set(reg.packs)))


def test_source_attribution():
    reg = _fresh_registry()
    expect = {
        "art_of_war": "Sun Tzu",
        "laws_of_power": "Robert Greene",
        "art_of_seduction": "Robert Greene",
    }
    for pid, author in expect.items():
        check(f"{pid} cites {author}", author in reg.packs[pid].source,
              f"source={reg.packs[pid].source!r}")


def test_art_of_war_faithful_content():
    t = _fresh_registry().packs["art_of_war"].agent_overlays["executive_arbiter"].lower()
    check("AoW: win before fighting", "before the" in t and "engagement" in t)
    check("AoW: attack weakness", "weakness" in t)
    check("AoW: timing/deception", "timing" in t and ("appear weak" in t or "deception" in t.replace("deceptive","deception")))


def test_laws_of_power_faithful_content():
    t = _fresh_registry().packs["laws_of_power"].agent_overlays["executive_arbiter"].lower()
    check("48L: never outshine superiors", "outshine" in t)
    check("48L: conceal intentions", "conceal intentions" in t)
    check("48L: reputation cornerstone", "reputation" in t)
    check("48L: also sees laws played on user", "played on" in t)


def test_art_of_seduction_faithful_content():
    t = _fresh_registry().packs["art_of_seduction"].agent_overlays["life_coach"].lower()
    check("AoS: magnetism created not innate", "created" in t and "innate" in t)
    check("AoS: mystery", "mystery" in t)
    check("AoS: center the other", "center of attention" in t)
    check("AoS: tension/anticipation", "tension" in t and "anticipation" in t)


def test_no_moralizing_hedges():
    """User wanted these unvarnished — no 'but be ethical' nagging, no
    'defensive only' / 'never' prohibition language like greene_observer."""
    reg = _fresh_registry()
    for pid in POWER_IDS:
        for text in reg.packs[pid].agent_overlays.values():
            lo = text.lower()
            check(f"{pid}: no 'never manipulate' handcuff",
                  "never coach the user to manipulate" not in lo
                  and "never teach the user to manipulate" not in lo
                  and "defensive use only" not in lo,
                  f"handcuff phrasing in {pid}")


def test_scope_clauses_present():
    """Not handcuffs, but each lens scopes to the user's OWN moves /
    consensual-adult domain in a single clause."""
    reg = _fresh_registry()
    aow = reg.packs["art_of_war"].agent_overlays["executive_arbiter"].lower()
    check("AoW scopes to user's own campaign", "user's own campaign" in aow)
    lop = reg.packs["laws_of_power"].agent_overlays["executive_arbiter"].lower()
    check("48L scopes to user's own positioning", "user's own positioning" in lop)
    aos = reg.packs["art_of_seduction"].agent_overlays["life_coach"].lower()
    check("AoS scopes to mutual consensual adult pursuit",
          "consensual adult" in aos and "mutual" in aos)


def test_compact_overlays_present_and_short():
    reg = _fresh_registry()
    for pid in POWER_IDS:
        p = reg.packs[pid]
        for agent_id in p.agent_overlays:
            out = p.overlay_text(agent_id, L.ModelTier.MINIMAL_GPU.value)
            check(f"{pid}/{agent_id} minimal_gpu overlay non-empty + <=240",
                  bool(out) and len(out) <= 240,
                  f"len={len(out) if out else 0}")


def test_no_parrotable_quotes():
    reg = _fresh_registry()
    for pid in POWER_IDS:
        p = reg.packs[pid]
        for text in {**p.agent_overlays, **p.agent_overlays_compact}.values():
            check(f"{pid}: no quoted example sentence", '"' not in text)


def test_temperature_offsets_within_bound():
    reg = _fresh_registry()
    for pid in POWER_IDS:
        for off in reg.packs[pid].temperature_offsets.values():
            check(f"{pid} temp offset within bound",
                  abs(off) <= L.PERSONA_TEMP_OFFSET_BOUND)


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


def test_ctx_power_pack_shapes_preamble():
    tmp = Path(tempfile.mkdtemp(prefix="sp41_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        ctx.persona_packs.enable("laws_of_power")
        p = ctx.compose_preamble("executive_arbiter")
        check("48 Laws overlay reaches arbiter preamble",
              "ADVISOR LENS" in p and "outshine" in p.lower(), f"tail={p[-300:]!r}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_ctx_seduction_temp_offset_available():
    tmp = Path(tempfile.mkdtemp(prefix="sp41_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="high")
        ctx.persona_packs.enable("art_of_seduction")
        off = ctx.persona_packs.temperature_offset_for("life_coach")
        check("seduction adds positive temp offset to life_coach",
              off == 0.05, f"got {off}")
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
        test_all_three_registered_via_seed_path,
        test_direct_power_registration,
        test_source_attribution,
        test_art_of_war_faithful_content,
        test_laws_of_power_faithful_content,
        test_art_of_seduction_faithful_content,
        test_no_moralizing_hedges,
        test_scope_clauses_present,
        test_compact_overlays_present_and_short,
        test_no_parrotable_quotes,
        test_temperature_offsets_within_bound,
        test_ctx_power_pack_shapes_preamble,
        test_ctx_seduction_temp_offset_available,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 41 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
