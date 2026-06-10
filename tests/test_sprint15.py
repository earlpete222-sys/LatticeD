"""Sprint 15 - MCP stdio JSON-RPC bridge. Standalone."""
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


def _build_bridge():
    t = Path(tempfile.mkdtemp(prefix="sp15_"))
    store = L.IdentityStore(t / "id.json", user_id="test")
    audit = L.AccessAuditLog(t / "audit.jsonl")
    srv = L.MCPServer(store, audit)
    srv.register_consumer(
        L.Consumer("claude-desktop", "Claude Desktop"),
        L.ConsumerGrant("claude-desktop",
                        sensitivity_ceiling=L.Sensitivity.LOW.value,
                        allowed_destinations=["mcp"]),
    )
    return L.MCPStdioBridge(srv, "claude-desktop"), store, srv, t


# ---------- encode / decode helpers ----------
def test_encode_response_envelope():
    line = L.encode_jsonrpc_response(7, {"hello": "world"})
    obj = json.loads(line)
    check("envelope has jsonrpc=2.0", obj["jsonrpc"] == "2.0")
    check("envelope has id passthrough", obj["id"] == 7)
    check("envelope has result", obj["result"] == {"hello": "world"})


def test_encode_error_envelope():
    line = L.encode_jsonrpc_error(7, L.JSONRPC_METHOD_NOT_FOUND, "no such")
    obj = json.loads(line)
    check("error envelope has error key", "error" in obj)
    check("error has code", obj["error"]["code"] == L.JSONRPC_METHOD_NOT_FOUND)
    check("error has message", obj["error"]["message"] == "no such")


def test_decode_well_formed_request():
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
    method, rid, params, err = L.decode_jsonrpc_request(raw)
    check("decode method", method == "ping" and err is None)
    check("decode id", rid == 1)
    check("decode params", params == {})


def test_decode_notification_has_no_id():
    raw = json.dumps({"jsonrpc": "2.0", "method": "ping"})
    method, rid, params, err = L.decode_jsonrpc_request(raw)
    check("notification: method parsed", method == "ping" and err is None)
    check("notification: rid is None", rid is None)


def test_decode_parse_error():
    method, rid, params, err = L.decode_jsonrpc_request("{not json")
    check("malformed JSON yields parse error",
          err and err.startswith("parse_error"))


def test_decode_version_mismatch():
    raw = json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    _, _, _, err = L.decode_jsonrpc_request(raw)
    check("non-2.0 envelope rejected", err == "jsonrpc_version_mismatch")


# ---------- bridge dispatch ----------
def test_bridge_initialize_handshake():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        }))
        obj = json.loads(line)
        check("initialize returns result with serverInfo",
              "result" in obj and "serverInfo" in obj["result"], f"got {obj}")
        check("serverInfo has name",
              obj["result"]["serverInfo"]["name"] == "latticed-mcp")
        check("serverInfo has protocolVersion",
              "protocolVersion" in obj["result"]["serverInfo"])
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_ping_pong():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": "abc", "method": "ping"
        }))
        obj = json.loads(line)
        check("ping returns pong", obj["result"] == {"pong": True})
        check("id string preserved", obj["id"] == "abc")
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_tools_list_translates_to_server():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list"
        }))
        obj = json.loads(line)
        check("tools/list returns tool names",
              isinstance(obj["result"], list)
              and "add_fact" in obj["result"], f"got {obj}")
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_tools_call_add_fact():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "add_fact", "text": "I am a researcher."}
        }))
        obj = json.loads(line)
        check("add_fact response ok",
              obj.get("result", {}).get("ok") is True, f"got {obj}")
        check("fact persisted in store",
              any("researcher" in f.text for f in store.doc.facts))
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_resources_read():
    bridge, store, srv, t = _build_bridge()
    try:
        store.add_fact("I make pottery.", domain=L.LifeDomain.LIFESTYLE.value,
                        confidence=0.9)
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 5, "method": "resources/read",
            "params": {"uri": "identity://portrait"}
        }))
        obj = json.loads(line)
        check("resources/read returns portrait shape",
              "result" in obj and "one_line_summary" in obj["result"],
              f"got {obj}")
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_unknown_method_returns_method_not_found():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "nonsense"
        }))
        obj = json.loads(line)
        check("unknown method -> error",
              obj["error"]["code"] == L.JSONRPC_METHOD_NOT_FOUND,
              f"got {obj}")
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_invalid_json_returns_parse_error():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line("{this is not json")
        obj = json.loads(line)
        check("malformed input -> parse error",
              obj["error"]["code"] == L.JSONRPC_PARSE_ERROR,
              f"got {obj}")
        check("parse error has null id", obj["id"] is None)
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_notification_yields_empty_reply():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "method": "ping"   # no id -> notification
        }))
        check("notification suppresses response line", line == "",
              f"got {line!r}")
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_shutdown_sets_flag():
    bridge, store, srv, t = _build_bridge()
    try:
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 9, "method": "shutdown"
        }))
        obj = json.loads(line)
        check("shutdown returns ok", obj["result"] == {"ok": True})
        check("shutdown flag flipped", bridge.shutdown_requested)
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_bridge_denial_carries_audit_entry():
    """A grant without `mcp` in allowed_destinations -> dispatch denies
    with reason; bridge wraps that in a JSON-RPC error with audit data."""
    t = Path(tempfile.mkdtemp(prefix="sp15_"))
    try:
        store = L.IdentityStore(t / "id.json")
        audit = L.AccessAuditLog(t / "audit.jsonl")
        srv = L.MCPServer(store, audit)
        srv.register_consumer(
            L.Consumer("c1", "Constrained"),
            L.ConsumerGrant("c1",
                            sensitivity_ceiling=L.Sensitivity.LOW.value,
                            allowed_destinations=["remote_api"]),  # NOT mcp
        )
        bridge = L.MCPStdioBridge(srv, "c1")
        line = bridge.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "add_fact", "text": "test"}
        }))
        obj = json.loads(line)
        check("denied call returns error", "error" in obj)
        check("error data carries audit entry",
              obj["error"].get("data", {}).get("audit_entry") is not None,
              f"got {obj}")
    finally:
        shutil.rmtree(t, ignore_errors=True)


# ---------- serve loop ----------
def test_serve_blocking_loop_with_eof():
    bridge, store, srv, t = _build_bridge()
    try:
        inp = io.StringIO(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "ping"
        }) + "\n")
        out = io.StringIO()
        bridge.serve(inp, out)
        out.seek(0)
        lines = [l for l in out.read().splitlines() if l]
        check("serve emitted one response line", len(lines) == 1, f"got {lines}")
        check("response is the pong",
              json.loads(lines[0]).get("result") == {"pong": True})
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_serve_blocking_loop_processes_multiple_messages():
    bridge, store, srv, t = _build_bridge()
    try:
        inp = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown"}) + "\n"
        )
        out = io.StringIO()
        bridge.serve(inp, out)
        out.seek(0)
        lines = [l for l in out.read().splitlines() if l]
        check("three responses emitted", len(lines) == 3, f"got {len(lines)}")
        check("third response is shutdown",
              json.loads(lines[2])["result"] == {"ok": True})
        check("bridge stopped on shutdown flag", bridge.shutdown_requested)
    finally:
        shutil.rmtree(t, ignore_errors=True)


# ---------- regression ----------
def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_encode_response_envelope,
        test_encode_error_envelope,
        test_decode_well_formed_request,
        test_decode_notification_has_no_id,
        test_decode_parse_error,
        test_decode_version_mismatch,
        test_bridge_initialize_handshake,
        test_bridge_ping_pong,
        test_bridge_tools_list_translates_to_server,
        test_bridge_tools_call_add_fact,
        test_bridge_resources_read,
        test_bridge_unknown_method_returns_method_not_found,
        test_bridge_invalid_json_returns_parse_error,
        test_bridge_notification_yields_empty_reply,
        test_bridge_shutdown_sets_flag,
        test_bridge_denial_carries_audit_entry,
        test_serve_blocking_loop_with_eof,
        test_serve_blocking_loop_processes_multiple_messages,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 15 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
