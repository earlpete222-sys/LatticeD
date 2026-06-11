"""Sprint 23 - mood tracking + pattern detection tests. Standalone."""
from __future__ import annotations
import datetime as dt
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
            "MOODS_PATH"]
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


# ---------- classifier ----------
def test_classify_mood_light():
    sig, conf, _ = L.classify_mood("Had a great day, fun trip to the park.")
    check("light keywords -> LIGHT signal",
          sig == L.MoodSignal.LIGHT.value, f"got {sig} conf={conf}")
    check("confidence > 0.5", conf > 0.5)


def test_classify_mood_heavy():
    sig, _, _ = L.classify_mood("Tough week. I've been struggling and feel down.")
    check("heavy keywords -> HEAVY signal",
          sig == L.MoodSignal.HEAVY.value, f"got {sig}")


def test_classify_mood_drained():
    sig, _, _ = L.classify_mood("Long day. Exhausted and worn out.")
    check("drained keywords -> DRAINED signal",
          sig == L.MoodSignal.DRAINED.value, f"got {sig}")


def test_classify_mood_neutral_when_no_signal():
    sig, conf, _ = L.classify_mood("Bought groceries.")
    check("benign text -> NEUTRAL",
          sig == L.MoodSignal.NEUTRAL.value, f"got {sig}")
    check("low confidence on neutral",
          conf < 0.5)


def test_classify_mood_mixed_on_tied_signals():
    sig, _, _ = L.classify_mood(
        "Good day overall but I also feel tough and broken.")
    check("competing signals -> MIXED",
          sig == L.MoodSignal.MIXED.value, f"got {sig}")


def test_classify_mood_empty_string():
    sig, conf, counts = L.classify_mood("")
    check("empty input -> NEUTRAL", sig == L.MoodSignal.NEUTRAL.value)
    check("empty input -> 0 confidence", conf == 0.0)
    check("empty input -> empty counts", counts == {})


# ---------- MoodTracker I/O ----------
def test_tracker_observe_and_recent():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    try:
        t = L.MoodTracker(tmp / "moods.jsonl")
        t.observe("Excited about the launch, we shipped!")
        t.observe("Rough morning, feel heavy and lost.")
        recent = t.recent(window_seconds=3600)
        check("two observations persisted", len(recent) == 2,
              f"got {len(recent)}")
        signals = {o.signal for o in recent}
        check("excited -> ENERGIZED in signals",
              L.MoodSignal.ENERGIZED.value in signals, f"got {signals}")
        check("heavy -> HEAVY in signals",
              L.MoodSignal.HEAVY.value in signals, f"got {signals}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tracker_dominant_signal():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    try:
        t = L.MoodTracker(tmp / "moods.jsonl")
        for _ in range(4):
            t.observe("Long day, tired and exhausted.")
        for _ in range(2):
            t.observe("Productive deep work session.")
        sig, share = t.dominant_signal(window_seconds=3600)
        check("dominant = DRAINED",
              sig == L.MoodSignal.DRAINED.value, f"got {sig}")
        check("share ~= 4/6", abs(share - 4/6) < 0.01, f"got {share}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mood_curve_bucket_count():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    try:
        t = L.MoodTracker(tmp / "moods.jsonl")
        t.observe("Smooth great day.")
        curve = t.mood_curve(buckets=5, window_seconds=86400)
        check("curve has 5 buckets", len(curve) == 5)
        check("each bucket has 'dominant' key",
              all("dominant" in b for b in curve))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_weekday_pattern():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    try:
        t = L.MoodTracker(tmp / "moods.jsonl")
        # Forge timestamps on different weekdays.
        now = time.time()
        base = dt.datetime.now()
        for days_back, text in [(0, "Light easy day."),
                                  (1, "Drained and tired."),
                                  (7, "Light easy day.")]:
            obs = L.MoodObservation(
                signal=L.classify_mood(text)[0],
                confidence=0.7,
                timestamp=now - days_back * 86400.0,
                source_text=text,
            )
            (tmp / "moods.jsonl").open("a", encoding="utf-8").write(
                json.dumps(L.asdict(obs), default=str) + "\n")
        pattern = t.weekday_pattern()
        check("pattern has entries for at least one weekday",
              len(pattern) >= 1, f"got {pattern}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_domain_mood_correlation():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    try:
        t = L.MoodTracker(tmp / "moods.jsonl")
        t.observe("My boss is supportive, good week.",
                   domain=L.LifeDomain.CAREER.value)
        t.observe("Boss change has me feeling rough.",
                   domain=L.LifeDomain.CAREER.value)
        t.observe("Long run today, energized.",
                   domain=L.LifeDomain.HEALTH.value)
        corr = t.domain_mood_correlation()
        check("career has correlation entries",
              L.LifeDomain.CAREER.value in corr)
        check("health has correlation entries",
              L.LifeDomain.HEALTH.value in corr, f"got {corr}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mood_to_warmth_adjustment_range():
    for sig in [s.value for s in L.MoodSignal]:
        adj = L.mood_to_warmth_adjustment(sig)
        check(f"warmth adjustment for {sig} in [-0.3, +0.3]",
              -0.3 <= adj <= 0.3, f"got {adj}")
    check("HEAVY produces positive warmth bump",
          L.mood_to_warmth_adjustment(L.MoodSignal.HEAVY.value) > 0)


# ---------- LatticeContext integration ----------
def test_ctx_mood_attached_and_observable():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        check("ctx.mood is a MoodTracker", isinstance(ctx.mood, L.MoodTracker))
        ctx.mood.observe("Energized and ready to ship.")
        recent = ctx.mood.recent(window_seconds=3600)
        check("observation persisted", len(recent) == 1)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_capture_continuity_auto_fills_mood():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for _ in range(3):
            ctx.mood.observe("Excited and pumped about the demo.")
        token = ctx.capture_continuity(session_id="s1",
                                          summary="Demo prep complete.")
        check("mood_signal auto-filled when not provided",
              token.mood_signal == L.MoodSignal.ENERGIZED.value,
              f"got {token.mood_signal}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_capture_continuity_respects_explicit_mood():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for _ in range(3):
            ctx.mood.observe("Drained and worn out today.")
        token = ctx.capture_continuity(session_id="s2",
                                          summary="...",
                                          mood_signal=L.MoodSignal.FOCUSED.value)
        check("explicit mood_signal wins over auto-fill",
              token.mood_signal == L.MoodSignal.FOCUSED.value)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- MCP tools ----------
def test_observe_mood_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "tools/call",
                     {"name": "observe_mood",
                      "text": "Long week, feeling drained."})
        check("observe_mood ok",
              resp.ok and resp.result["ok"], f"got {resp.error or resp.result}")
        check("classified as DRAINED",
              resp.result["signal"] == L.MoodSignal.DRAINED.value,
              f"got {resp.result}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_observe_mood_tool_empty_text():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "tools/call",
                     {"name": "observe_mood", "text": ""})
        check("empty text -> ok:False",
              resp.ok and resp.result["ok"] is False
              and resp.result["error"] == "empty_text")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_dominant_mood_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        for _ in range(3):
            ctx.mood.observe("Productive deep work focused day.")
        resp = _call(ctx, "tools/call", {"name": "get_dominant_mood"})
        check("dominant mood tool ok", resp.ok)
        check("signal = FOCUSED",
              resp.result["signal"] == L.MoodSignal.FOCUSED.value,
              f"got {resp.result}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mood_curve_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.mood.observe("Great smooth day.")
        resp = _call(ctx, "tools/call",
                     {"name": "get_mood_curve",
                      "buckets": 4, "window_seconds": 86400})
        check("mood curve tool ok", resp.ok)
        check("4 buckets returned", len(resp.result["buckets"]) == 4)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mood_patterns_tool():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.mood.observe("Long week, tired.",
                          domain=L.LifeDomain.CAREER.value)
        ctx.mood.observe("Excited about the workout class.",
                          domain=L.LifeDomain.HEALTH.value)
        resp = _call(ctx, "tools/call", {"name": "get_mood_patterns"})
        check("patterns tool ok", resp.ok)
        check("weekday present", "weekday" in resp.result)
        check("domain_correlation present",
              "domain_correlation" in resp.result)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_mood_resources():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.mood.observe("Excited about the new role.")
        r1 = _call(ctx, "resources/read", {"uri": "mood://recent"})
        r2 = _call(ctx, "resources/read", {"uri": "mood://dominant"})
        check("mood://recent ok", r1.ok and r1.result["ok"])
        check("mood://dominant ok", r2.ok and r2.result["ok"])
        check("dominant returns a signal string",
              isinstance(r2.result["signal"], str))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_tools_list_includes_mood_tools():
    tmp = Path(tempfile.mkdtemp(prefix="sp23_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        resp = _call(ctx, "tools/list", {})
        names = set(resp.result)
        for needed in ["observe_mood", "get_dominant_mood",
                        "get_mood_curve", "get_mood_patterns"]:
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
        test_classify_mood_light,
        test_classify_mood_heavy,
        test_classify_mood_drained,
        test_classify_mood_neutral_when_no_signal,
        test_classify_mood_mixed_on_tied_signals,
        test_classify_mood_empty_string,
        test_tracker_observe_and_recent,
        test_tracker_dominant_signal,
        test_mood_curve_bucket_count,
        test_weekday_pattern,
        test_domain_mood_correlation,
        test_mood_to_warmth_adjustment_range,
        test_ctx_mood_attached_and_observable,
        test_capture_continuity_auto_fills_mood,
        test_capture_continuity_respects_explicit_mood,
        test_observe_mood_tool,
        test_observe_mood_tool_empty_text,
        test_dominant_mood_tool,
        test_mood_curve_tool,
        test_mood_patterns_tool,
        test_mood_resources,
        test_tools_list_includes_mood_tools,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 23 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
