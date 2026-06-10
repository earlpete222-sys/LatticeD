"""Sprint 17 - expanded MCP tool surface tests. Standalone."""
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
            "PROMPT_EVOLUTION_PATH", "SNAPSHOTS_PATH"]
    orig = {k: getattr(L, k) for k in keys}
    for k in keys:
        suffix = ".jsonl" if k == "AUDIT_LOG_PATH" else ".json"
        setattr(L, k, tmp / f"{k.lower()}{suffix}")
    return orig


def _restore(o):
    for k, v in o.items(): setattr(L, k, v)


def _boot(tmp: Path) -> L.LatticeContext:
    ctx = L.LatticeContext.boot(user_id="t", tier_override="minimal_gpu")
    # The default LATTICED_CONSUMER_DOMAINS in MCPServer needs a consumer;
    # register one with broad grant.
    ctx.mcp.register_consumer(
        L.Consumer("c1", "Test"),
        L.ConsumerGrant("c1",
                         sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
                         allowed_destinations=["mcp"]),
    )
    return ctx


def _call(ctx: L.LatticeContext, method: str, params: dict) -> L.MCPResponse:
    return ctx.mcp.handle(L.MCPRequest(method=method, consumer_id="c1", params=params))


# ---------- snapshots + drift ----------
def test_capture_snapshot_and_detect_drift():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.identity.add_fact("I work as an analyst.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        r1 = _call(ctx, "tools/call",
                   {"name": "capture_snapshot", "label": "t0"})
        check("capture_snapshot ok", r1.ok and r1.result["ok"],
              f"got {r1.error or r1.result}")
        check("snapshot recorded fact_count=1",
              r1.result["fact_count"] == 1)

        ctx.identity.add_fact("I run twice a week.",
                              domain=L.LifeDomain.HEALTH.value, confidence=0.85)
        r2 = _call(ctx, "tools/call",
                   {"name": "capture_snapshot", "label": "t1"})
        check("second snapshot ok", r2.ok and r2.result["ok"])

        r3 = _call(ctx, "tools/call",
                   {"name": "detect_drift",
                    "params": {},
                    "earlier": "t0", "later": "t1"})
        check("detect_drift ok", r3.ok and r3.result["ok"],
              f"got {r3.error or r3.result}")
        check("drift saw +1 fact",
              r3.result["fact_delta"] == 1)
        check("drift saw new health domain",
              "health" in r3.result["new_domains"])
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_detect_drift_unknown_label():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        r = _call(ctx, "tools/call",
                  {"name": "detect_drift", "earlier": "no", "later": "such"})
        check("unknown label -> ok:False with available list",
              r.ok and not r.result["ok"]
              and r.result["error"] == "unknown_label"
              and "available" in r.result,
              f"got {r.error or r.result}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- tension ----------
def test_tension_domains_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.identity.add_north_star("Become an engineering manager.",
                                     domain=L.LifeDomain.CAREER.value, weight=2.0)
        r = _call(ctx, "tools/call",
                  {"name": "tension_domains", "threshold": 0.3})
        check("tension_domains ok", r.ok and r.result["ok"])
        check("career surfaces in tension list",
              any(d["domain"] == "career" for d in r.result["domains"]),
              f"got {r.result['domains']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- recombined ----------
def test_get_recombined_insights_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.identity.add_fact("I mentor junior engineers at work.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        ctx.identity.add_fact("I mentor younger family members.",
                              domain=L.LifeDomain.RELATIONSHIPS.value, confidence=0.9)
        r = _call(ctx, "tools/call",
                  {"name": "get_recombined_insights", "top_k": 3})
        check("recombined ok", r.ok and r.result["ok"])
        check("insights include career/relationships pair",
              any({i["domain_a"], i["domain_b"]} == {"career", "relationships"}
                  for i in r.result["insights"]),
              f"got {r.result['insights']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- aspects ----------
def test_extract_aspects_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        r = _call(ctx, "tools/call",
                  {"name": "extract_aspects",
                   "text": "I work as a designer and my wife is a teacher."})
        check("extract_aspects ok", r.ok and r.result["ok"])
        names = {a["name"] for a in r.result["aspects"]}
        check("profession aspect present", "profession" in names, f"got {names}")
        check("partner_status aspect present", "partner_status" in names)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_extract_aspects_empty_text():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        r = _call(ctx, "tools/call", {"name": "extract_aspects", "text": ""})
        check("empty text -> ok:False",
              r.ok and r.result["ok"] is False
              and r.result["error"] == "empty_text")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- predict engagement ----------
def test_predict_engagement_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        r = _call(ctx, "tools/call",
                  {"name": "predict_engagement",
                   "prompt": "What do you do for work?"})
        check("predict_engagement ok", r.ok and r.result["ok"])
        check("likely_domain = career",
              r.result["likely_domain"] == "career",
              f"got {r.result}")
        check("estimated_response_rate in [0,1]",
              0.0 <= r.result["estimated_response_rate"] <= 1.0)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- business routing ----------
def test_route_business_fact_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.business.register(
            L.BusinessProfile(business_id="acme", display_name="Acme Co"),
            set_active=True,
        )
        r = _call(ctx, "tools/call",
                  {"name": "route_business_fact",
                   "text": "Our company is hiring next quarter."})
        check("route_business_fact ok", r.ok and r.result["ok"])
        check("routed to business=acme",
              r.result["route"] == "business" and r.result["business_id"] == "acme",
              f"got {r.result}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- continuity ----------
def test_get_continuity_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.capture_continuity(session_id="s1", summary="talked about budget")
        r = _call(ctx, "tools/call", {"name": "get_continuity", "n": 3})
        check("get_continuity ok", r.ok and r.result["ok"])
        check("returned 1 continuity token", len(r.result["tokens"]) == 1)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- resources ----------
def test_identity_tension_resource():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.identity.add_north_star("Become a leader.",
                                     domain=L.LifeDomain.CAREER.value, weight=1.8)
        r = _call(ctx, "resources/read", {"uri": "identity://tension"})
        check("tension resource ok", r.ok and r.result["ok"], f"got {r.error}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_identity_aspects_resource():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.identity.add_fact("I work as a manager.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        r = _call(ctx, "resources/read", {"uri": "identity://aspects"})
        check("aspects resource ok", r.ok and r.result["ok"])
        check("profession in aspect names",
              "profession" in r.result["names"], f"got {r.result}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_identity_drift_resource_with_suffix():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        # Capture two snapshots.
        ctx.identity.add_fact("I work as an analyst.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        _call(ctx, "tools/call", {"name": "capture_snapshot", "label": "t0"})
        ctx.identity.add_fact("I run twice a week.",
                              domain=L.LifeDomain.HEALTH.value, confidence=0.85)
        _call(ctx, "tools/call", {"name": "capture_snapshot", "label": "t1"})

        r = _call(ctx, "resources/read", {"uri": "identity://drift/t0/t1"})
        check("drift resource ok with two labels",
              r.ok and r.result["ok"], f"got {r.error or r.result}")
        check("drift resource reports +1 fact",
              r.result["fact_delta"] == 1)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_business_list_and_active_resources():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.business.register(
            L.BusinessProfile(business_id="acme", display_name="Acme Co",
                              role="founder"),
            set_active=True,
        )
        r1 = _call(ctx, "resources/read", {"uri": "business://list"})
        check("business://list ok", r1.ok and r1.result["ok"])
        check("active_id reflected",
              r1.result["active_id"] == "acme",
              f"got {r1.result}")
        check("1 profile listed", len(r1.result["profiles"]) == 1)

        r2 = _call(ctx, "resources/read", {"uri": "business://active"})
        check("business://active ok", r2.ok and r2.result["ok"])
        check("active business display_name correct",
              r2.result["active"]["display_name"] == "Acme Co")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_business_active_when_none_registered():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        r = _call(ctx, "resources/read", {"uri": "business://active"})
        check("business://active returns active=None cleanly",
              r.ok and r.result["ok"] and r.result["active"] is None,
              f"got {r.result}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- snapshot persistence ----------
def test_snapshot_roundtrip_across_boots():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        ctx.identity.add_fact("I work as an analyst.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        _call(ctx, "tools/call", {"name": "capture_snapshot", "label": "t0"})
        ctx.save_all()

        # Fresh context loads the snapshot.
        ctx2 = _boot(tmp)
        check("snapshot persists across boots",
              "t0" in ctx2.snapshots.snapshots,
              f"labels={ctx2.snapshots.labels()}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- tools/list reflects new tools ----------
def test_tools_list_includes_sprint17_tools():
    tmp = Path(tempfile.mkdtemp(prefix="sp17_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot(tmp)
        r = _call(ctx, "tools/list", {})
        check("tools/list ok", r.ok)
        names = set(r.result)
        for needed in ["capture_snapshot", "detect_drift", "tension_domains",
                        "get_recombined_insights", "extract_aspects",
                        "predict_engagement", "route_business_fact",
                        "get_continuity"]:
            check(f"tools/list contains {needed}", needed in names,
                  f"got {sorted(names)}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- regression ----------
def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_capture_snapshot_and_detect_drift,
        test_detect_drift_unknown_label,
        test_tension_domains_tool,
        test_get_recombined_insights_tool,
        test_extract_aspects_tool,
        test_extract_aspects_empty_text,
        test_predict_engagement_tool,
        test_route_business_fact_tool,
        test_get_continuity_tool,
        test_identity_tension_resource,
        test_identity_aspects_resource,
        test_identity_drift_resource_with_suffix,
        test_business_list_and_active_resources,
        test_business_active_when_none_registered,
        test_snapshot_roundtrip_across_boots,
        test_tools_list_includes_sprint17_tools,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 17 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
