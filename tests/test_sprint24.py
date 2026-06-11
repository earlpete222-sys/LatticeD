"""Sprint 24 - goal tracking + milestones tests. Standalone."""
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
            "PROMPT_EVOLUTION_PATH", "SNAPSHOTS_PATH", "ACTIVITY_PATH",
            "MOODS_PATH", "MILESTONES_PATH"]
    orig = {k: getattr(L, k) for k in keys}
    for k in keys:
        if k in ("AUDIT_LOG_PATH", "ACTIVITY_PATH", "MOODS_PATH"):
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


# ---------- store primitives ----------
def test_add_milestone():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m = s.add("Lead first cross-team project",
                   north_star_ref="Lead a team within 3 years.")
        check("milestone id assigned", m.id.startswith("ms_"))
        check("milestone status defaults to OPEN",
              m.status == L.MilestoneStatus.OPEN.value)
        check("domain inferred",
              m.domain in {"career", "uncategorized"}, f"got {m.domain}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_add_milestone_empty_text_raises():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        try:
            s.add("")
            check("empty text raises", False, "no exception")
        except ValueError:
            check("empty text raises ValueError", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_milestone_roundtrip():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m = s.add("Ship the v1 launch", north_star_ref="Ship the SaaS in 2026.")
        s.save()
        s2 = L.MilestoneStore(tmp / "m.json").load()
        check("1 milestone reloaded", len(s2.milestones) == 1)
        check("text preserved",
              next(iter(s2.milestones.values())).text == "Ship the v1 launch")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- state machine ----------
def test_valid_transition_open_to_in_progress():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m = s.add("step")
        m2, err = s.update_status(m.id, L.MilestoneStatus.IN_PROGRESS.value)
        check("OPEN -> IN_PROGRESS valid", err is None and m2 is not None,
              f"err={err}")
        check("status updated",
              m.status == L.MilestoneStatus.IN_PROGRESS.value)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_done_sets_completed_at():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m = s.add("step")
        s.update_status(m.id, L.MilestoneStatus.DONE.value)
        check("completed_at populated on DONE",
              m.completed_at is not None and m.completed_at > 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_invalid_transition_rejected():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m = s.add("step", status=L.MilestoneStatus.PROPOSED.value)
        m2, err = s.update_status(m.id, L.MilestoneStatus.DONE.value)
        check("PROPOSED -> DONE rejected",
              m2 is None and err and "invalid_transition" in err,
              f"got err={err}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reopen_done_milestone():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m = s.add("step")
        s.update_status(m.id, L.MilestoneStatus.DONE.value)
        m2, err = s.update_status(m.id, L.MilestoneStatus.OPEN.value)
        check("DONE -> OPEN allowed (reopen)",
              err is None and m.status == L.MilestoneStatus.OPEN.value,
              f"err={err}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_update_unknown_id():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        _, err = s.update_status("ms_nope", L.MilestoneStatus.DONE.value)
        check("unknown id -> error",
              err == "unknown_milestone_id", f"got {err}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- queries ----------
def test_list_filters():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        s.add("a", north_star_ref="NS1")
        s.add("b", north_star_ref="NS2")
        s.add("c", north_star_ref="NS1")
        a = s.list(north_star_ref="NS1")
        check("NS1 filter returns 2", len(a) == 2, f"got {[m.text for m in a]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_progress_calculation():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m1 = s.add("a", north_star_ref="goal")
        m2 = s.add("b", north_star_ref="goal")
        m3 = s.add("c", north_star_ref="goal")
        m4 = s.add("d", north_star_ref="goal")
        s.update_status(m1.id, L.MilestoneStatus.DONE.value)
        s.update_status(m2.id, L.MilestoneStatus.DONE.value)
        s.update_status(m3.id, L.MilestoneStatus.IN_PROGRESS.value)
        # m4 stays OPEN
        p = s.progress_for("goal")
        check("total=4 done=2 in_progress=1 open=1",
              p["total"] == 4 and p["done"] == 2
              and p["in_progress"] == 1 and p["open"] == 1,
              f"got {p}")
        check("percent = 50.0", p["percent"] == 50.0, f"got {p['percent']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_progress_excludes_dropped_from_denominator():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m1 = s.add("a", north_star_ref="goal")
        m2 = s.add("b", north_star_ref="goal")
        m3 = s.add("c", north_star_ref="goal")
        s.update_status(m1.id, L.MilestoneStatus.DONE.value)
        s.update_status(m2.id, L.MilestoneStatus.DROPPED.value)
        p = s.progress_for("goal")
        # 1 done out of 2 active -> 50%
        check("dropped excluded from active denominator",
              p["active"] == 2 and p["percent"] == 50.0, f"got {p}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_progress_zero_milestones():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        p = s.progress_for("unknown_goal")
        check("zero milestones -> 0%",
              p["total"] == 0 and p["percent"] == 0.0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_stale_detection():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m_old = s.add("ancient", north_star_ref="goal")
        m_old.updated = time.time() - 45 * 86400
        s.add("fresh", north_star_ref="goal")
        stale = s.stale(window_seconds=30 * 86400)
        check("only ancient milestone is stale", len(stale) == 1
              and stale[0].id == m_old.id,
              f"got {[m.text for m in stale]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_stale_excludes_done():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    try:
        s = L.MilestoneStore(tmp / "m.json")
        m_done = s.add("done one", north_star_ref="goal")
        m_done.updated = time.time() - 100 * 86400
        s.update_status(m_done.id, L.MilestoneStatus.OPEN.value)  # noop
        m_done.updated = time.time() - 100 * 86400
        s.update_status(m_done.id, L.MilestoneStatus.DONE.value)
        stale = s.stale(window_seconds=30 * 86400)
        check("DONE milestones not flagged stale",
              all(m.id != m_done.id for m in stale))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- LatticeContext integration ----------
def test_ctx_milestones_attached():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        check("ctx.milestones is MilestoneStore",
              isinstance(ctx.milestones, L.MilestoneStore))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_save_all_persists_milestones():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.milestones.add("Ship the prototype", north_star_ref="Build a SaaS.")
        ctx.save_all()
        check("milestone file written",
              L.MILESTONES_PATH.exists())
        ctx2 = _boot()
        check("reload sees the milestone",
              any("prototype" in m.text for m in ctx2.milestones.milestones.values()))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- MCP tools ----------
def test_add_milestone_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "tools/call",
                     {"name": "add_milestone",
                      "text": "Ship the v1 launch",
                      "north_star": "Reach $100k ARR by Q4."})
        check("add_milestone ok",
              resp.ok and resp.result["ok"], f"got {resp.error}")
        check("milestone shows up in store",
              any("v1 launch" in m.text
                  for m in ctx.milestones.milestones.values()))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_update_milestone_status_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("step", north_star_ref="goal")
        resp = _call(ctx, "tools/call",
                     {"name": "update_milestone_status",
                      "id": m.id,
                      "status": L.MilestoneStatus.IN_PROGRESS.value})
        check("update ok", resp.ok and resp.result["ok"])
        check("status now IN_PROGRESS",
              m.status == L.MilestoneStatus.IN_PROGRESS.value)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_invalid_transition_tool_returns_error():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("step", status=L.MilestoneStatus.PROPOSED.value)
        resp = _call(ctx, "tools/call",
                     {"name": "update_milestone_status",
                      "id": m.id,
                      "status": L.MilestoneStatus.DONE.value})
        check("PROPOSED->DONE rejected via MCP",
              resp.ok and resp.result["ok"] is False
              and "invalid_transition" in resp.result["error"])
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_list_and_progress_tools():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m1 = ctx.milestones.add("a", north_star_ref="ns")
        m2 = ctx.milestones.add("b", north_star_ref="ns")
        ctx.milestones.update_status(m1.id, L.MilestoneStatus.DONE.value)

        list_resp = _call(ctx, "tools/call",
                          {"name": "list_milestones",
                           "north_star": "ns"})
        check("list returns 2", list_resp.result["count"] == 2)

        prog_resp = _call(ctx, "tools/call",
                          {"name": "get_north_star_progress",
                           "north_star": "ns"})
        check("progress tool ok", prog_resp.ok and prog_resp.result["ok"])
        check("progress = 50.0%",
              prog_resp.result["progress"]["percent"] == 50.0,
              f"got {prog_resp.result['progress']}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_stale_milestones_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("ancient", north_star_ref="ns")
        m.updated = time.time() - 45 * 86400
        resp = _call(ctx, "tools/call",
                     {"name": "get_stale_milestones",
                      "window_seconds": 30 * 86400})
        check("stale tool ok",
              resp.ok and resp.result["ok"])
        check("ancient surfaces", resp.result["count"] == 1)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_milestones_resource():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.milestones.add("alpha", north_star_ref="x")
        resp = _call(ctx, "resources/read",
                     {"uri": "goals://milestones"})
        check("resource ok", resp.ok and resp.result["ok"])
        check("alpha milestone present",
              any("alpha" in m["text"] for m in resp.result["milestones"]))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_progress_resource_with_suffix():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("alpha", north_star_ref="reach goal")
        ctx.milestones.update_status(m.id, L.MilestoneStatus.DONE.value)
        resp = _call(ctx, "resources/read",
                     {"uri": "goals://progress/reach goal"})
        check("progress resource ok",
              resp.ok and resp.result["ok"], f"got {resp.error}")
        check("percent = 100.0",
              resp.result["progress"]["percent"] == 100.0)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_tools_list_includes_milestone_tools():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "tools/list", {})
        names = set(resp.result)
        for needed in ["add_milestone", "update_milestone_status",
                        "list_milestones", "get_north_star_progress",
                        "get_stale_milestones"]:
            check(f"tools/list contains {needed}", needed in names,
                  f"got {sorted(names)}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- activity emission ----------
def test_milestone_add_emits_activity_event():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _call(ctx, "tools/call",
              {"name": "add_milestone",
               "text": "alpha milestone",
               "north_star": "goal"})
        kinds = [e.kind for e in ctx.activity.read_all()]
        check("milestone_added activity event present",
              "milestone_added" in kinds, f"got {kinds}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_milestone_done_emits_completed_event():
    tmp = Path(tempfile.mkdtemp(prefix="sp24_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        m = ctx.milestones.add("alpha")
        _call(ctx, "tools/call",
              {"name": "update_milestone_status",
               "id": m.id,
               "status": L.MilestoneStatus.DONE.value})
        kinds = [e.kind for e in ctx.activity.read_all()]
        check("milestone_completed event emitted",
              "milestone_completed" in kinds, f"got {kinds}")
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
        test_add_milestone,
        test_add_milestone_empty_text_raises,
        test_milestone_roundtrip,
        test_valid_transition_open_to_in_progress,
        test_done_sets_completed_at,
        test_invalid_transition_rejected,
        test_reopen_done_milestone,
        test_update_unknown_id,
        test_list_filters,
        test_progress_calculation,
        test_progress_excludes_dropped_from_denominator,
        test_progress_zero_milestones,
        test_stale_detection,
        test_stale_excludes_done,
        test_ctx_milestones_attached,
        test_save_all_persists_milestones,
        test_add_milestone_tool,
        test_update_milestone_status_tool,
        test_invalid_transition_tool_returns_error,
        test_list_and_progress_tools,
        test_stale_milestones_tool,
        test_milestones_resource,
        test_progress_resource_with_suffix,
        test_tools_list_includes_milestone_tools,
        test_milestone_add_emits_activity_event,
        test_milestone_done_emits_completed_event,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 24 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
