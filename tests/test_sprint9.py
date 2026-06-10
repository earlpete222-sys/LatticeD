"""Sprint 9 - MCP Server tests. Standalone."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


def _build_server():
    t = Path(tempfile.mkdtemp(prefix="sprint9_"))
    store = L.IdentityStore(t/"id.json", user_id="test")
    audit = L.AccessAuditLog(t/"audit.jsonl")
    srv = L.MCPServer(store, audit)
    return srv, store, audit, t


def test_unknown_consumer_denied():
    srv, store, audit, t = _build_server()
    try:
        resp = srv.handle(L.MCPRequest(method="tools/list", consumer_id="ghost"))
        check("unknown consumer -> error", not resp.ok)
        check("error tag is unknown_consumer", resp.error == "unknown_consumer")
        rows = audit.read_all()
        check("denial audited", len(rows) == 1 and rows[0].reason == "unknown_consumer")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_tools_list_visible_to_consumer():
    srv, store, audit, t = _build_server()
    try:
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(method="tools/list", consumer_id="c1"))
        check("tools/list ok", resp.ok)
        check("built-in tools present",
              set(["add_fact", "list_facts_in_domain", "ask_curiosity_question"]).issubset(set(resp.result)),
              f"got {resp.result}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_resources_list_visible():
    srv, store, audit, t = _build_server()
    try:
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(method="resources/list", consumer_id="c1"))
        check("resources/list ok", resp.ok)
        check("identity://portrait registered",
              "identity://portrait" in resp.result, f"got {resp.result}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_add_fact_tool_call():
    srv, store, audit, t = _build_server()
    try:
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(
            method="tools/call", consumer_id="c1",
            params={"name": "add_fact",
                    "text": "I work as an analyst.",
                    "domain": L.LifeDomain.CAREER.value,
                    "confidence": 0.9},
        ))
        check("add_fact ok", resp.ok and resp.result.get("ok"),
              f"resp={resp.error or resp.result}")
        check("fact persisted in store",
              any("analyst" in f.text for f in store.doc.facts))
    finally: shutil.rmtree(t, ignore_errors=True)


def test_portrait_resource_read():
    srv, store, audit, t = _build_server()
    try:
        store.add_fact("I'm a designer at a startup.",
                       domain=L.LifeDomain.CAREER.value, confidence=0.9)
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(
            method="resources/read", consumer_id="c1",
            params={"uri": "identity://portrait"},
        ))
        check("portrait read ok", resp.ok)
        check("portrait shows career domain count",
              resp.result["domain_counts"].get(L.LifeDomain.CAREER.value, 0) == 1,
              f"counts={resp.result.get('domain_counts')}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_summary_resource_with_suffix():
    srv, store, audit, t = _build_server()
    try:
        store.add_fact("I work as a manager.",
                       domain=L.LifeDomain.CAREER.value, confidence=0.9)
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(
            method="resources/read", consumer_id="c1",
            params={"uri": "identity://summary/career"},
        ))
        check("summary read with suffix ok", resp.ok, f"err={resp.error}")
        check("narrative includes the domain tag",
              "[career]" in resp.result["narrative"].lower(),
              resp.result.get("narrative"))
    finally: shutil.rmtree(t, ignore_errors=True)


def test_unknown_tool_returns_error():
    srv, store, audit, t = _build_server()
    try:
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(
            method="tools/call", consumer_id="c1",
            params={"name": "no_such_tool"},
        ))
        check("unknown tool -> error", not resp.ok)
        check("error is unknown_tool tag", "unknown_tool" in resp.error)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_unknown_method_returns_error():
    srv, store, audit, t = _build_server()
    try:
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(method="nonsense", consumer_id="c1"))
        check("unknown method -> error", not resp.ok and "unknown_method" in resp.error)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_grant_destination_must_include_mcp():
    """A grant without 'mcp' in allowed_destinations blocks tool calls."""
    srv, store, audit, t = _build_server()
    try:
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["remote_api"]),   # NOT mcp
        )
        resp = srv.handle(L.MCPRequest(
            method="tools/call", consumer_id="c1",
            params={"name": "add_fact", "text": "test"},
        ))
        check("grant without mcp destination blocks tools/call",
              not resp.ok, f"resp={resp.error or resp.result}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_curiosity_tool_runs():
    t = Path(tempfile.mkdtemp(prefix="sprint9_"))
    try:
        store  = L.IdentityStore(t/"id.json", user_id="test")
        audit  = L.AccessAuditLog(t/"audit.jsonl")
        ledger = L.EngagementLedger(t/"cur.json")
        cur    = L.CuriosityEngine(store, ledger, max_per_hour=99, max_per_day=99)
        srv    = L.MCPServer(store, audit, curiosity=cur)
        srv.register_consumer(
            L.Consumer("c1", "Client"),
            L.ConsumerGrant("c1", sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["mcp"]),
        )
        resp = srv.handle(L.MCPRequest(
            method="tools/call", consumer_id="c1",
            params={"name": "ask_curiosity_question"},
        ))
        check("curiosity tool ok", resp.ok)
        check("curiosity question returned",
              resp.result.get("question") and len(resp.result["question"]) > 5,
              f"result={resp.result}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_unknown_consumer_denied,
        test_tools_list_visible_to_consumer,
        test_resources_list_visible,
        test_add_fact_tool_call,
        test_portrait_resource_read,
        test_summary_resource_with_suffix,
        test_unknown_tool_returns_error,
        test_unknown_method_returns_error,
        test_grant_destination_must_include_mcp,
        test_curiosity_tool_runs,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 9 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
