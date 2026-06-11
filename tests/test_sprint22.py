"""Sprint 22 - activity timeline tests. Standalone."""
from __future__ import annotations
import json
import sys
import time
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
            "PROMPT_EVOLUTION_PATH", "SNAPSHOTS_PATH", "ACTIVITY_PATH"]
    orig = {k: getattr(L, k) for k in keys}
    for k in keys:
        if k == "AUDIT_LOG_PATH" or k == "ACTIVITY_PATH":
            suffix = ".jsonl"
        else:
            suffix = ".json"
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
                         sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
                         allowed_destinations=["mcp"]),
    )
    return ctx


def _call(ctx, method, params):
    return ctx.mcp.handle(L.MCPRequest(method=method, consumer_id="c1", params=params))


# ---------- log primitives ----------
def test_log_append_and_read():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    try:
        log = L.ActivityLog(tmp / "act.jsonl")
        log.append(L.ActivityEvent(kind=L.ActivityKind.FACT_ADDED.value,
                                     summary="added foo"))
        log.append(L.ActivityEvent(kind=L.ActivityKind.RULE_ADDED.value,
                                     summary="added bar"))
        rows = log.read_all()
        check("2 events persisted", len(rows) == 2)
        check("first event preserved",
              rows[0].kind == L.ActivityKind.FACT_ADDED.value)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_filter_by_kind():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    try:
        log = L.ActivityLog(tmp / "act.jsonl")
        log.append(L.ActivityEvent(kind=L.ActivityKind.FACT_ADDED.value,
                                     summary="a"))
        log.append(L.ActivityEvent(kind=L.ActivityKind.RULE_ADDED.value,
                                     summary="b"))
        log.append(L.ActivityEvent(kind=L.ActivityKind.FACT_ADDED.value,
                                     summary="c"))
        only_facts = log.filter(kinds=[L.ActivityKind.FACT_ADDED.value])
        check("kind filter returns 2 fact_added",
              len(only_facts) == 2,
              f"got {[e.kind for e in only_facts]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_filter_since():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    try:
        log = L.ActivityLog(tmp / "act.jsonl")
        old = L.ActivityEvent(kind=L.ActivityKind.BOOT.value,
                                summary="old", timestamp=time.time() - 3600)
        new = L.ActivityEvent(kind=L.ActivityKind.BOOT.value,
                                summary="new")
        log.append(old)
        log.append(new)
        recent = log.filter(since_seconds=600)
        check("since filter excludes >1h old events",
              len(recent) == 1 and recent[0].summary == "new")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_filter_sensitivity_ceiling():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    try:
        log = L.ActivityLog(tmp / "act.jsonl")
        log.append(L.ActivityEvent(kind="x", summary="low",
                                     sensitivity=L.Sensitivity.LOW.value))
        log.append(L.ActivityEvent(kind="x", summary="high",
                                     sensitivity=L.Sensitivity.HIGH.value))
        below_medium = log.filter(max_sensitivity=L.Sensitivity.MEDIUM.value)
        check("MEDIUM ceiling excludes HIGH events",
              len(below_medium) == 1 and below_medium[0].summary == "low")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_counts_by_kind():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    try:
        log = L.ActivityLog(tmp / "act.jsonl")
        for kind in [L.ActivityKind.FACT_ADDED.value] * 3 + \
                     [L.ActivityKind.RULE_ADDED.value]:
            log.append(L.ActivityEvent(kind=kind, summary="x"))
        counts = log.counts_by_kind()
        check("3 fact_added events",
              counts[L.ActivityKind.FACT_ADDED.value] == 3)
        check("1 rule_added event",
              counts[L.ActivityKind.RULE_ADDED.value] == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- auto-hooks via LatticeContext ----------
def test_add_fact_emits_event():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("I'm a designer.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.9)
        events = ctx.activity.read_all()
        check("activity log contains a fact_added event",
              any(e.kind == L.ActivityKind.FACT_ADDED.value for e in events),
              f"kinds={[e.kind for e in events]}")
        fact_evt = next(e for e in events
                         if e.kind == L.ActivityKind.FACT_ADDED.value)
        check("fact event carries the text",
              "designer" in fact_evt.summary)
        check("fact event tagged with domain",
              fact_evt.domain == L.LifeDomain.CAREER.value)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_add_fact_dup_emits_fact_updated_event():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("I run twice a week.",
                              domain=L.LifeDomain.HEALTH.value, confidence=0.9)
        ctx.identity.add_fact("I run twice a week.",
                              domain=L.LifeDomain.HEALTH.value, confidence=0.95)
        events = ctx.activity.read_all()
        kinds = [e.kind for e in events]
        check("fact_added once",
              kinds.count(L.ActivityKind.FACT_ADDED.value) == 1)
        check("fact_updated once",
              kinds.count(L.ActivityKind.FACT_UPDATED.value) == 1,
              f"got {kinds}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_add_north_star_and_rule_emit_events():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_north_star("Be present.",
                                     domain=L.LifeDomain.RELATIONSHIPS.value, weight=1.5)
        ctx.identity.add_rule("Tell the truth.", priority=300)
        events = ctx.activity.read_all()
        kinds = {e.kind for e in events}
        check("north_star_added emitted",
              L.ActivityKind.NORTH_STAR_ADDED.value in kinds)
        check("rule_added emitted",
              L.ActivityKind.RULE_ADDED.value in kinds)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_business_register_emits_events():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.business.register(L.BusinessProfile(business_id="acme",
                                                  display_name="Acme Co",
                                                  role="founder"),
                                set_active=True)
        kinds = [e.kind for e in ctx.activity.read_all()]
        check("business_registered emitted",
              L.ActivityKind.BUSINESS_REGISTERED.value in kinds, f"got {kinds}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_snapshot_put_emits_event():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("I cook on weekends.",
                              domain=L.LifeDomain.LIFESTYLE.value, confidence=0.85)
        ctx.snapshots.put("t0", L.capture_present(ctx.identity, label="t0"))
        kinds = [e.kind for e in ctx.activity.read_all()]
        check("snapshot_captured emitted",
              L.ActivityKind.SNAPSHOT_CAPTURED.value in kinds, f"got {kinds}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_curiosity_question_ask_and_answer_emit_events():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        sel = ctx.curiosity.select_next_question()
        q, gap, gain = sel
        ctx.curiosity.record_question_asked(q, gap, gain)
        ctx.curiosity.record_response(q, answered=True, response_excerpt="Sure.")
        kinds = [e.kind for e in ctx.activity.read_all()]
        check("question_asked emitted",
              L.ActivityKind.QUESTION_ASKED.value in kinds)
        check("question_answered emitted",
              L.ActivityKind.QUESTION_ANSWERED.value in kinds)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_boot_event_recorded():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        kinds = [e.kind for e in ctx.activity.read_all()]
        check("boot event emitted",
              L.ActivityKind.BOOT.value in kinds, f"got {kinds}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- MCP wiring ----------
def test_get_recent_activity_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("Hello world.",
                              domain=L.LifeDomain.LIFESTYLE.value, confidence=0.8)
        ctx.identity.add_rule("Speak plainly.", priority=100)
        resp = _call(ctx, "tools/call",
                     {"name": "get_recent_activity", "limit": 5})
        check("get_recent_activity ok",
              resp.ok and resp.result["ok"], f"got {resp.error or resp.result}")
        check("events surfaced",
              resp.result["count"] >= 2)
        check("payload includes the fact",
              any("Hello world" in (e["summary"] or "")
                  for e in resp.result["events"]))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_get_recent_activity_kind_filter():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("foo.", confidence=0.8)
        ctx.identity.add_rule("bar.", priority=100)
        resp = _call(ctx, "tools/call",
                     {"name": "get_recent_activity",
                      "kinds": [L.ActivityKind.RULE_ADDED.value]})
        check("filter only rule_added",
              all(e["kind"] == L.ActivityKind.RULE_ADDED.value
                  for e in resp.result["events"]),
              f"got {[e['kind'] for e in resp.result['events']]}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_activity_summary_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for i in range(3):
            ctx.identity.add_fact(f"Fact {i}.", confidence=0.9)
        ctx.identity.add_rule("Be brief.", priority=200)
        resp = _call(ctx, "tools/call",
                     {"name": "activity_summary"})
        check("activity_summary ok", resp.ok and resp.result["ok"])
        cbk = resp.result["counts_by_kind"]
        check("3 fact_added counted",
              cbk.get(L.ActivityKind.FACT_ADDED.value, 0) == 3,
              f"got {cbk}")
        check("1 rule_added counted",
              cbk.get(L.ActivityKind.RULE_ADDED.value, 0) == 1)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_activity_recent_resource():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("walked the dog.", confidence=0.8)
        resp = _call(ctx, "resources/read", {"uri": "activity://recent"})
        check("activity://recent ok",
              resp.ok and resp.result["ok"])
        check("includes the recently added fact",
              any("walked the dog" in (e["summary"] or "")
                  for e in resp.result["events"]),
              f"got {resp.result['events']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_activity_summary_resource():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("x.", confidence=0.9)
        resp = _call(ctx, "resources/read", {"uri": "activity://summary"})
        check("activity://summary ok",
              resp.ok and resp.result["ok"])
        check("counts_by_kind exposed",
              "counts_by_kind" in resp.result)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_tools_list_includes_activity_tools():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "tools/list", {})
        names = set(resp.result)
        check("get_recent_activity registered",
              "get_recent_activity" in names)
        check("activity_summary registered",
              "activity_summary" in names)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- HIGH-sensitivity exclusion ----------
def test_recent_activity_excludes_high_sensitivity_by_default():
    tmp = Path(tempfile.mkdtemp(prefix="sp22_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        # SSN auto-classifies as HIGH.
        ctx.identity.add_fact("My SSN is 999-88-7777.", confidence=0.9)
        resp = _call(ctx, "tools/call", {"name": "get_recent_activity"})
        events = resp.result["events"]
        check("HIGH-sensitivity event NOT in default response",
              all("999-88-7777" not in (e["summary"] or "")
                  for e in events),
              f"got {[e['summary'] for e in events]}")
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
        test_log_append_and_read,
        test_log_filter_by_kind,
        test_log_filter_since,
        test_log_filter_sensitivity_ceiling,
        test_log_counts_by_kind,
        test_add_fact_emits_event,
        test_add_fact_dup_emits_fact_updated_event,
        test_add_north_star_and_rule_emit_events,
        test_business_register_emits_events,
        test_snapshot_put_emits_event,
        test_curiosity_question_ask_and_answer_emit_events,
        test_boot_event_recorded,
        test_get_recent_activity_tool,
        test_get_recent_activity_kind_filter,
        test_activity_summary_tool,
        test_activity_recent_resource,
        test_activity_summary_resource,
        test_tools_list_includes_activity_tools,
        test_recent_activity_excludes_high_sensitivity_by_default,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 22 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
