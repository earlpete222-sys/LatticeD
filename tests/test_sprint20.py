"""Sprint 20 - Diagnostics + Self-Introspection. Standalone."""
from __future__ import annotations
import json
import sys
import tempfile
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _redirect_paths(tmp: Path) -> dict:
    keys = ["IDENTITY_PATH", "CURIOSITY_PATH", "VOICE_PROFILES_PATH",
            "CONTINUITY_PATH", "AUDIT_LOG_PATH", "BUSINESS_PATH",
            "PROMPT_EVOLUTION_PATH", "SNAPSHOTS_PATH"]
    orig = {k: getattr(L, k) for k in keys}
    for k in keys:
        suffix = ".jsonl" if k == "AUDIT_LOG_PATH" else ".json"
        setattr(L, k, tmp / f"{k.lower()}{suffix}")
    return orig


def _restore(o):
    for k, v in o.items(): setattr(L, k, v)


def _boot():
    L.install_encrypted_persistence(None)
    return L.LatticeContext.boot(user_id="t", tier_override="minimal_gpu")


def _call(ctx, method, params):
    return ctx.mcp.handle(L.MCPRequest(method=method, consumer_id="c1", params=params))


def _register_consumer(ctx):
    ctx.mcp.register_consumer(
        L.Consumer("c1", "Test"),
        L.ConsumerGrant("c1",
                         sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
                         allowed_destinations=["mcp"]),
    )


# ---------- direct Diagnostics API ----------
def test_diagnostics_snapshot_contains_all_sections():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        snap = ctx.diagnostics.snapshot()
        for key in ["boot", "perf", "audit_24h", "identity", "engagement",
                    "voice", "tension", "business", "encryption"]:
            check(f"snapshot has section '{key}'", key in snap, f"got keys={list(snap)}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_render_text_report():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("I work as a designer.",
                               domain=L.LifeDomain.CAREER.value, confidence=0.9)
        text = ctx.diagnostics.render()
        check("text report starts with header",
              text.startswith("=") and "LatticeD diagnostics" in text)
        check("text report mentions tier",
              "tier" in text)
        check("text report shows the user id", "user" in text)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_perf_summary_counts_samples():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.perf.record("life_coach", 120.0)
        ctx.perf.record("life_coach", 240.0)
        ctx.perf.record("intent_router", 12.0)
        snap = ctx.diagnostics.perf_summary()
        check("perf total_samples=3", snap["total_samples"] == 3)
        check("perf knows both nodes",
              set(snap["nodes"]) == {"life_coach", "intent_router"})
        check("life_coach mean ~ 180",
              abs(snap["per_node"]["life_coach"]["mean"] - 180.0) < 0.01)
        check("slowest first is life_coach",
              snap["slowest"][0][0] == "life_coach")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_audit_summary_counts_decisions():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        # Force a few audit lines.
        consumer = L.Consumer("c1", "C")
        grant = L.ConsumerGrant("c1",
                                  sensitivity_ceiling=L.Sensitivity.LOW.value,
                                  allowed_destinations=["remote_api"])
        L.audited_egress("It rained today.", consumer, grant,
                           "remote_api", ctx.audit)
        L.audited_egress("My SSN is 999-88-7777.", consumer, grant,
                           "remote_api", ctx.audit)
        snap = ctx.diagnostics.audit_summary()
        check("audit total >= 2", snap["total"] >= 2, f"got {snap}")
        check("decisions include allow + deny",
              set(["allow", "deny"]).issubset(snap["by_decision"]),
              f"got {snap['by_decision']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_identity_summary_low_coverage_gap_closes():
    """Closing a LOW_COVERAGE gap for a domain should reduce the count
    of LOW_COVERAGE gaps -- even though a NO_NORTH_STAR gap opens to
    take its place (the curiosity engine's intended behavior)."""
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        before = ctx.diagnostics.identity_summary()["gaps_by_type"]
        before_lc = before.get(L.GapType.LOW_COVERAGE.value, 0)
        for fact in ["My salary is $90k.",
                      "I save into a 401k each month.",
                      "I owe $20k in student loans."]:
            ctx.identity.add_fact(fact,
                                   domain=L.LifeDomain.FINANCIAL.value,
                                   confidence=0.9)
        after = ctx.diagnostics.identity_summary()["gaps_by_type"]
        after_lc = after.get(L.GapType.LOW_COVERAGE.value, 0)
        check("LOW_COVERAGE gap count drops by 1",
              after_lc == before_lc - 1,
              f"before_lc={before_lc} after_lc={after_lc}")
        check("NO_NORTH_STAR gap opens for the newly active domain",
              after.get(L.GapType.NO_NORTH_STAR.value, 0)
              >= before.get(L.GapType.NO_NORTH_STAR.value, 0) + 1,
              f"before={before} after={after}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_engagement_summary_uses_ledger():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for i in range(4):
            ctx.curiosity_ledger.add(L.CuriosityEngagement(
                question=f"q{i}",
                domain=L.LifeDomain.CAREER.value,
                gap_type=L.GapType.LOW_COVERAGE.value,
                answered=(i < 3),
            ))
        snap = ctx.diagnostics.engagement_summary()
        check("total_questions = 4", snap["total_questions"] == 4)
        check("career response rate = 0.75",
              abs(snap["per_domain_rate"]["career"] - 0.75) < 1e-6,
              f"got {snap['per_domain_rate']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_voice_summary_reflects_drift():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for _ in range(6):
            ctx.voice.record_interaction(L.EngagementSignal(
                agent_id="life_coach", output_chars=900,
                user_explicit_negative=True,
            ))
        snap = ctx.diagnostics.voice_summary()
        check("life_coach appears in voice profiles",
              "life_coach" in snap["profiles"])
        check("life_coach brevity_pref > 1.0 after negative-on-long signals",
              snap["profiles"]["life_coach"]["brevity_pref"] > 1.0,
              f"got {snap['profiles']['life_coach']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_tension_summary_lists_domains():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_north_star("Lead a team.",
                                     domain=L.LifeDomain.CAREER.value, weight=2.0)
        snap = ctx.diagnostics.tension_summary()
        check("career domain shows up under tension",
              any(d["domain"] == "career"
                  for d in snap["high_tension_domains"]),
              f"got {snap}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_encryption_status_reflects_passphrase():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        snap_off = ctx.diagnostics.encryption_status()
        check("encryption off when no passphrase",
              snap_off["at_rest_active"] is False)

        # Now boot a context with passphrase.
        ctx2 = L.LatticeContext.boot(
            user_id="t", tier_override="minimal_gpu",
            encrypt_at_rest=True, passphrase="my-pp",
        )
        snap_on = ctx2.diagnostics.encryption_status()
        check("encryption on when passphrase set",
              snap_on["at_rest_active"] is True)
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- MCP wiring ----------
def test_get_diagnostics_tool_default_full():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _register_consumer(ctx)
        resp = _call(ctx, "tools/call", {"name": "get_diagnostics"})
        check("get_diagnostics ok", resp.ok and resp.result["ok"],
              f"got {resp.error or resp.result}")
        snap = resp.result["diagnostics"]
        for key in ["boot", "perf", "identity", "engagement"]:
            check(f"snapshot has '{key}'", key in snap)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_get_diagnostics_tool_sections_filter():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _register_consumer(ctx)
        resp = _call(ctx, "tools/call",
                     {"name": "get_diagnostics",
                      "sections": ["identity", "tension"]})
        snap = resp.result["diagnostics"]
        check("snapshot has identity only", "identity" in snap)
        check("snapshot has tension only", "tension" in snap)
        check("snapshot is exactly 2 sections",
              set(snap.keys()) == {"identity", "tension"},
              f"got {sorted(snap.keys())}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_render_diagnostics_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _register_consumer(ctx)
        resp = _call(ctx, "tools/call", {"name": "render_diagnostics"})
        check("render_diagnostics ok", resp.ok and resp.result["ok"])
        text = resp.result["text"]
        check("render output is human-readable",
              "LatticeD diagnostics" in text and "tier" in text)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_diagnostics_resource_full():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _register_consumer(ctx)
        resp = _call(ctx, "resources/read", {"uri": "diagnostics://full"})
        check("diagnostics://full ok", resp.ok and resp.result["ok"])
        check("returns snapshot dict",
              isinstance(resp.result["snapshot"], dict)
              and "boot" in resp.result["snapshot"])
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_diagnostics_resource_section_subpaths():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _register_consumer(ctx)
        for uri in ["diagnostics://perf", "diagnostics://audit",
                     "diagnostics://identity", "diagnostics://engagement",
                     "diagnostics://voice", "diagnostics://tension",
                     "diagnostics://business", "diagnostics://encryption"]:
            resp = _call(ctx, "resources/read", {"uri": uri})
            check(f"resource {uri} ok",
                  resp.ok and resp.result["ok"], f"got {resp.error}")
            check(f"resource {uri} carries 'section' payload",
                  "section" in resp.result)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_tools_list_includes_diagnostics_tools():
    tmp = Path(tempfile.mkdtemp(prefix="sp20_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _register_consumer(ctx)
        resp = _call(ctx, "tools/list", {})
        check("tools/list ok", resp.ok)
        names = set(resp.result)
        for needed in ["get_diagnostics", "render_diagnostics"]:
            check(f"tools/list contains {needed}", needed in names,
                  f"got {sorted(names)}")
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
        test_diagnostics_snapshot_contains_all_sections,
        test_render_text_report,
        test_perf_summary_counts_samples,
        test_audit_summary_counts_decisions,
        test_identity_summary_low_coverage_gap_closes,
        test_engagement_summary_uses_ledger,
        test_voice_summary_reflects_drift,
        test_tension_summary_lists_domains,
        test_encryption_status_reflects_passphrase,
        test_get_diagnostics_tool_default_full,
        test_get_diagnostics_tool_sections_filter,
        test_render_diagnostics_tool,
        test_diagnostics_resource_full,
        test_diagnostics_resource_section_subpaths,
        test_tools_list_includes_diagnostics_tools,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 20 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
