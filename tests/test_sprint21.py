"""Sprint 21 - MCP prompts surface tests. Standalone."""
from __future__ import annotations
import io
import json
import sys
import tempfile
import shutil
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
    ctx = L.LatticeContext.boot(user_id="t", tier_override="minimal_gpu")
    ctx.mcp.register_consumer(
        L.Consumer("c1", "Test"),
        L.ConsumerGrant("c1",
                         sensitivity_ceiling=L.Sensitivity.LOW.value,
                         allowed_destinations=["mcp"]),
    )
    return ctx


def _call(ctx, method, params):
    return ctx.mcp.handle(L.MCPRequest(method=method, consumer_id="c1", params=params))


# ---------- registry shape ----------
def test_prompts_attached_to_context():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        check("ctx.prompts is dict", isinstance(ctx.prompts, dict))
        check("daily_checkin registered", "daily_checkin" in ctx.prompts)
        check("reflect_on_tension registered", "reflect_on_tension" in ctx.prompts)
        check("summarize_week registered", "summarize_week" in ctx.prompts)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_list_via_mcp():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "prompts/list", {})
        check("prompts/list ok", resp.ok, f"err={resp.error}")
        names = {p["name"] for p in resp.result}
        for needed in ["daily_checkin", "reflect_on_tension", "summarize_week",
                        "propose_next_north_star", "audit_my_engagement",
                        "review_my_north_stars"]:
            check(f"prompts/list contains {needed}", needed in names,
                  f"got {sorted(names)}")
        # Verify arguments structure surfaced.
        rot = next(p for p in resp.result if p["name"] == "reflect_on_tension")
        check("reflect_on_tension exposes 'domain' argument",
              any(a["name"] == "domain" for a in rot["arguments"]),
              f"got {rot['arguments']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_daily_checkin_renders():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_rule("Be direct.", priority=200)
        ctx.identity.add_north_star("Be a present partner.",
                                     domain=L.LifeDomain.RELATIONSHIPS.value, weight=1.5)
        resp = _call(ctx, "prompts/get", {"name": "daily_checkin"})
        check("prompts/get ok", resp.ok, f"err={resp.error}")
        msgs = resp.result["messages"]
        check("at least one message returned", len(msgs) >= 1)
        text = msgs[0]["content"]
        check("rule surfaces in render", "Be direct" in text, f"got {text[:300]}")
        check("north star surfaces", "present partner" in text, f"got {text[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_reflect_on_tension_uses_highest():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_north_star("Lead a team.",
                                     domain=L.LifeDomain.CAREER.value, weight=2.0)
        resp = _call(ctx, "prompts/get", {"name": "reflect_on_tension"})
        check("prompts/get ok", resp.ok)
        text = resp.result["messages"][0]["content"]
        check("career surfaces as the chosen domain (highest tension)",
              "career" in text.lower(), f"got {text[:200]}")
        check("explicit aspirations listed",
              "Lead a team" in text, f"got {text[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_reflect_on_tension_honors_explicit_domain():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_north_star("Lead a team.",
                                     domain=L.LifeDomain.CAREER.value, weight=2.0)
        resp = _call(ctx, "prompts/get",
                      {"name": "reflect_on_tension",
                       "arguments": {"domain": "health"}})
        check("prompts/get ok", resp.ok)
        text = resp.result["messages"][0]["content"]
        check("health used because explicitly passed",
              "health" in text.lower(), f"got {text[:200]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_summarize_week_uses_continuity_tokens():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.capture_continuity(session_id="s1",
                                 summary="Wrapped the prototype demo",
                                 open_threads=["follow up with founder"],
                                 mood_signal="focused")
        ctx.capture_continuity(session_id="s2",
                                 summary="Solid family dinner",
                                 mood_signal="light")
        resp = _call(ctx, "prompts/get",
                      {"name": "summarize_week", "arguments": {"n": 5}})
        check("prompts/get ok", resp.ok)
        text = resp.result["messages"][0]["content"]
        check("first summary surfaces",
              "prototype demo" in text.lower(), f"got {text[:300]}")
        check("second summary surfaces",
              "family dinner" in text.lower(), f"got {text[:300]}")
        check("open thread surfaces",
              "follow up with founder" in text.lower(), f"got {text[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_propose_next_north_star():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("I work as a designer.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        resp = _call(ctx, "prompts/get",
                      {"name": "propose_next_north_star"})
        check("prompts/get ok", resp.ok)
        text = resp.result["messages"][0]["content"]
        check("targets career (gap-heavy) by default",
              "career" in text.lower(),
              f"got {text[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_audit_my_engagement():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for i in range(4):
            ctx.curiosity_ledger.add(L.CuriosityEngagement(
                question=f"q{i}",
                domain=L.LifeDomain.HEALTH.value,
                gap_type=L.GapType.LOW_COVERAGE.value,
                answered=(i == 0),
            ))
        resp = _call(ctx, "prompts/get",
                      {"name": "audit_my_engagement"})
        check("prompts/get ok", resp.ok)
        text = resp.result["messages"][0]["content"]
        check("global response rate quoted",
              "Global response rate" in text)
        check("health surfaces as low-engagement",
              "health" in text.lower(), f"got {text[:300]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_review_my_north_stars():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_north_star("Be a present partner.",
                                     domain=L.LifeDomain.RELATIONSHIPS.value, weight=1.4)
        ctx.identity.add_north_star("Run a half marathon.",
                                     domain=L.LifeDomain.HEALTH.value, weight=1.1)
        resp = _call(ctx, "prompts/get", {"name": "review_my_north_stars"})
        check("prompts/get ok", resp.ok)
        text = resp.result["messages"][0]["content"]
        check("first north star surfaces",
              "present partner" in text.lower())
        check("second north star surfaces",
              "half marathon" in text.lower())
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_unknown_returns_error():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "prompts/get", {"name": "no_such_template"})
        check("unknown -> ok:False with error",
              not resp.ok and "unknown_prompt" in resp.error,
              f"got {resp.error}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_missing_name_returns_error():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "prompts/get", {})
        check("missing name -> error", not resp.ok and resp.error == "missing_name")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_unknown_consumer_denied():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = ctx.mcp.handle(L.MCPRequest(method="prompts/get",
                                              consumer_id="ghost",
                                              params={"name": "daily_checkin"}))
        check("ghost consumer denied", not resp.ok)
        check("error tag = unknown_consumer", resp.error == "unknown_consumer")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_prompts_get_emits_audit_entry_when_denied_at_egress():
    """Consumer's grant without 'mcp' in allowed_destinations triggers a
    deny at audited_egress before the renderer runs."""
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence(None)
        ctx = L.LatticeContext.boot(user_id="t", tier_override="minimal_gpu")
        ctx.mcp.register_consumer(
            L.Consumer("c2", "Constrained"),
            L.ConsumerGrant("c2",
                             sensitivity_ceiling=L.Sensitivity.LOW.value,
                             allowed_destinations=["remote_api"]),   # NOT mcp
        )
        resp = ctx.mcp.handle(L.MCPRequest(method="prompts/get",
                                              consumer_id="c2",
                                              params={"name": "daily_checkin"}))
        check("denied at egress",
              not resp.ok and resp.error.startswith("destination_not_granted"),
              f"got {resp.error}")
        check("response carries audit entry",
              resp.audit_entry is not None
              and resp.audit_entry.decision == "deny")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- stdio bridge translation ----------
def test_stdio_bridge_translates_prompts_methods():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        bridge = L.MCPStdioBridge(ctx.mcp, "c1")
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "prompts/list",
        }))
        obj = json.loads(line)
        check("stdio prompts/list ok",
              "result" in obj and isinstance(obj["result"], list))
        check("stdio prompts/list contains daily_checkin",
              any(p["name"] == "daily_checkin" for p in obj["result"]))

        line2 = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "prompts/get",
            "params": {"name": "daily_checkin"},
        }))
        obj2 = json.loads(line2)
        check("stdio prompts/get ok",
              "result" in obj2 and "messages" in obj2["result"], f"got {obj2}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_stdio_bridge_prompts_unknown_returns_error():
    tmp = Path(tempfile.mkdtemp(prefix="sp21_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        bridge = L.MCPStdioBridge(ctx.mcp, "c1")
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "prompts/get",
            "params": {"name": "nope"},
        }))
        obj = json.loads(line)
        check("stdio surfaces unknown_prompt error",
              "error" in obj and "unknown_prompt" in obj["error"]["message"],
              f"got {obj}")
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
        test_prompts_attached_to_context,
        test_prompts_list_via_mcp,
        test_prompts_get_daily_checkin_renders,
        test_prompts_get_reflect_on_tension_uses_highest,
        test_prompts_get_reflect_on_tension_honors_explicit_domain,
        test_prompts_get_summarize_week_uses_continuity_tokens,
        test_prompts_get_propose_next_north_star,
        test_prompts_get_audit_my_engagement,
        test_prompts_get_review_my_north_stars,
        test_prompts_get_unknown_returns_error,
        test_prompts_get_missing_name_returns_error,
        test_prompts_get_unknown_consumer_denied,
        test_prompts_get_emits_audit_entry_when_denied_at_egress,
        test_stdio_bridge_translates_prompts_methods,
        test_stdio_bridge_prompts_unknown_returns_error,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 21 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
