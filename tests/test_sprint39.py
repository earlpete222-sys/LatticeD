"""Sprint 39 - PersonaPack infrastructure tests."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


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


def _pack(pid="carnegie", **kw):
    defaults = dict(
        pack_id=pid, display_name="Carnegie", source="HtWFaIP — Carnegie",
        description="warmth tactics",
        agent_overlays={"life_coach": "Use the person's own frame; show genuine interest."},
        agent_overlays_compact={"life_coach": "Show genuine interest."},
        temperature_offsets={"life_coach": 0.05},
        min_tier=L.ModelTier.STANDARD.value,
    )
    defaults.update(kw)
    return L.PersonaPack(**defaults)


# ---------- pack overlay tier selection ----------
def test_overlay_full_at_or_above_min_tier():
    p = _pack()
    check("HIGH tier gets full overlay",
          "genuine interest" in p.overlay_text("life_coach", L.ModelTier.HIGH.value)
          and "own frame" in p.overlay_text("life_coach", L.ModelTier.HIGH.value))


def test_overlay_compact_below_min_tier():
    p = _pack()
    out = p.overlay_text("life_coach", L.ModelTier.MINIMAL_GPU.value)
    check("minimal_gpu gets compact overlay",
          out == "Show genuine interest.", f"got {out!r}")


def test_overlay_empty_for_unlisted_agent():
    p = _pack()
    check("unlisted agent -> empty overlay",
          p.overlay_text("intent_router", L.ModelTier.HIGH.value) == "")


def test_overlay_fallback_when_no_compact_and_short():
    p = _pack(agent_overlays={"life_coach": "Be kind."},
              agent_overlays_compact={})
    check("short full overlay used below min_tier when no compact",
          p.overlay_text("life_coach", L.ModelTier.MINIMAL_GPU.value) == "Be kind.")


def test_overlay_suppressed_when_long_and_no_compact_below_tier():
    long_text = "x" * 400
    p = _pack(agent_overlays={"life_coach": long_text}, agent_overlays_compact={})
    check("long full overlay suppressed below min_tier (no compact)",
          p.overlay_text("life_coach", L.ModelTier.MINIMAL_GPU.value) == "")


# ---------- registry ----------
def test_registry_enable_disable():
    reg = L.PersonaPackRegistry(Path("x.json"))
    reg.register(_pack())
    check("starts disabled", not reg.packs["carnegie"].enabled)
    check("enable returns True", reg.enable("carnegie"))
    check("now enabled", reg.packs["carnegie"].enabled)
    check("disable returns True", reg.disable("carnegie"))
    check("unknown enable returns False", not reg.enable("nope"))


def test_registry_overlay_for_combines_and_prefixes():
    reg = L.PersonaPackRegistry(Path("x.json"))
    reg.register(_pack("a", display_name="A",
                       agent_overlays={"life_coach": "Frame it as theirs."}))
    reg.register(_pack("b", display_name="B",
                       agent_overlays={"life_coach": "Name the feeling."}))
    reg.enable("a"); reg.enable("b")
    out = reg.overlay_for("life_coach", L.ModelTier.HIGH.value)
    check("overlay has ADVISOR LENS header", "ADVISOR LENS" in out)
    check("both packs labeled", "[A]" in out and "[B]" in out)
    check("deterministic order a before b", out.index("[A]") < out.index("[B]"))


def test_registry_overlay_empty_when_none_enabled():
    reg = L.PersonaPackRegistry(Path("x.json"))
    reg.register(_pack())  # not enabled
    check("no enabled packs -> empty overlay",
          reg.overlay_for("life_coach", L.ModelTier.HIGH.value) == "")


def test_registry_budget_cap():
    reg = L.PersonaPackRegistry(Path("x.json"))
    big = "y" * 500
    for i in range(4):
        reg.register(_pack(f"p{i}", display_name=f"P{i}",
                           agent_overlays={"life_coach": big}))
        reg.enable(f"p{i}")
    out = reg.overlay_for("life_coach", L.ModelTier.HIGH.value)
    check("combined overlay capped at budget",
          len(out) <= L.PERSONA_OVERLAY_BUDGET_CHARS + 80,  # +header
          f"len={len(out)}")


def test_registry_temperature_offset_bounded():
    reg = L.PersonaPackRegistry(Path("x.json"))
    reg.register(_pack("a", temperature_offsets={"life_coach": 0.15}))
    reg.register(_pack("b", temperature_offsets={"life_coach": 0.15}))
    reg.enable("a"); reg.enable("b")
    off = reg.temperature_offset_for("life_coach")
    check("summed offset clamped to bound",
          off == L.PERSONA_TEMP_OFFSET_BOUND, f"got {off}")


def test_registry_persist_enabled_state():
    tmp = Path(tempfile.mkdtemp(prefix="sp39_"))
    try:
        path = tmp / "packs.json"
        reg = L.PersonaPackRegistry(path)
        reg.register(_pack("carnegie"))
        reg.enable("carnegie")
        reg.save()
        # New registry, re-register definitions, load enabled state.
        reg2 = L.PersonaPackRegistry(path)
        reg2.register(_pack("carnegie"))
        reg2.load()
        check("enabled state restored from disk",
              reg2.packs["carnegie"].enabled)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_register_preserves_enabled_on_redef():
    reg = L.PersonaPackRegistry(Path("x.json"))
    reg.register(_pack("carnegie"))
    reg.enable("carnegie")
    # Re-register (e.g., updated definition) — enabled must survive.
    reg.register(_pack("carnegie", description="updated"))
    check("enabled survives re-registration", reg.packs["carnegie"].enabled)
    check("definition updated", reg.packs["carnegie"].description == "updated")


# ---------- LatticeContext integration ----------
def _boot():
    L.install_encrypted_persistence(None)
    return L.LatticeContext.boot(user_id="t", tier_override="high")


def test_ctx_has_persona_registry():
    tmp = Path(tempfile.mkdtemp(prefix="sp39_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        check("ctx.persona_packs present",
              isinstance(ctx.persona_packs, L.PersonaPackRegistry))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_ctx_preamble_includes_enabled_overlay():
    tmp = Path(tempfile.mkdtemp(prefix="sp39_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.persona_packs.register(_pack("carnegie"))
        ctx.persona_packs.enable("carnegie")
        p = ctx.compose_preamble("life_coach")
        check("enabled overlay appears in preamble",
              "ADVISOR LENS" in p and "genuine interest" in p, f"got {p[-300:]!r}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_ctx_preamble_excludes_disabled_overlay():
    tmp = Path(tempfile.mkdtemp(prefix="sp39_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.persona_packs.register(_pack("carnegie"))  # not enabled
        p = ctx.compose_preamble("life_coach")
        check("disabled overlay absent from preamble",
              "ADVISOR LENS" not in p)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- MCP tools ----------
def _call(ctx, method, params):
    ctx.mcp.register_consumer(
        L.Consumer("c1", "T"),
        L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                        allowed_destinations=["mcp"]))
    return ctx.mcp.handle(L.MCPRequest(method=method, consumer_id="c1", params=params))


def test_mcp_list_enable_disable():
    tmp = Path(tempfile.mkdtemp(prefix="sp39_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.persona_packs.register(_pack("carnegie"))
        r1 = _call(ctx, "tools/call", {"name": "list_persona_packs"})
        check("list ok", r1.ok and any(p["pack_id"] == "carnegie"
              for p in r1.result["packs"]))
        r2 = _call(ctx, "tools/call",
                   {"name": "enable_persona_pack", "pack_id": "carnegie"})
        check("enable ok", r2.ok and r2.result["enabled"])
        check("pack now enabled in registry",
              ctx.persona_packs.packs["carnegie"].enabled)
        r3 = _call(ctx, "tools/call",
                   {"name": "enable_persona_pack", "pack_id": "ghost"})
        check("unknown pack -> error", not r3.result["ok"])
        r4 = _call(ctx, "tools/call",
                   {"name": "disable_persona_pack", "pack_id": "carnegie"})
        check("disable ok", r4.ok and not r4.result["enabled"])
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mcp_tools_registered():
    tmp = Path(tempfile.mkdtemp(prefix="sp39_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        r = _call(ctx, "tools/list", {})
        names = set(r.result)
        for needed in ["list_persona_packs", "enable_persona_pack",
                        "disable_persona_pack"]:
            check(f"tool {needed} registered", needed in names)
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
        test_overlay_full_at_or_above_min_tier,
        test_overlay_compact_below_min_tier,
        test_overlay_empty_for_unlisted_agent,
        test_overlay_fallback_when_no_compact_and_short,
        test_overlay_suppressed_when_long_and_no_compact_below_tier,
        test_registry_enable_disable,
        test_registry_overlay_for_combines_and_prefixes,
        test_registry_overlay_empty_when_none_enabled,
        test_registry_budget_cap,
        test_registry_temperature_offset_bounded,
        test_registry_persist_enabled_state,
        test_register_preserves_enabled_on_redef,
        test_ctx_has_persona_registry,
        test_ctx_preamble_includes_enabled_overlay,
        test_ctx_preamble_excludes_disabled_overlay,
        test_mcp_list_enable_disable,
        test_mcp_tools_registered,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 39 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
