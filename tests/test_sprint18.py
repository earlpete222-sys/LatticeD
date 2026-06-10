"""Sprint 18 - identity export/import tests. Standalone."""
from __future__ import annotations
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
    return L.LatticeContext.boot(user_id="t", tier_override="minimal_gpu")


def _populate(ctx):
    """Populate the context with mixed-sensitivity facts."""
    ctx.identity.add_fact("I work as a designer.",
                           domain=L.LifeDomain.CAREER.value,
                           sensitivity=L.Sensitivity.LOW.value, confidence=0.9)
    ctx.identity.add_fact("My salary is $90k.",
                           domain=L.LifeDomain.FINANCIAL.value,
                           sensitivity=L.Sensitivity.MEDIUM.value, confidence=0.9)
    ctx.identity.add_fact("My SSN is 999-88-7777.",
                           domain=L.LifeDomain.UNCATEGORIZED.value,
                           sensitivity=L.Sensitivity.HIGH.value, confidence=0.95)
    ctx.identity.add_fact("My password is hunter2.",
                           sensitivity=L.Sensitivity.SECRET.value, confidence=0.99)
    ctx.identity.add_north_star("Be a present partner.",
                                 domain=L.LifeDomain.RELATIONSHIPS.value, weight=1.5)
    ctx.identity.add_rule("Be direct with bad news.", priority=200)


# ---------- export filtering ----------
def test_export_low_ceiling_only_includes_low():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _populate(ctx)
        bundle = L.build_identity_export(ctx, ceiling=L.Sensitivity.LOW.value)
        sensitivities = {f["sensitivity"] for f in bundle.facts}
        check("only LOW facts present in LOW-ceiling export",
              sensitivities == {L.Sensitivity.LOW.value},
              f"got {sensitivities}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_export_medium_ceiling_includes_low_and_medium():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _populate(ctx)
        bundle = L.build_identity_export(ctx, ceiling=L.Sensitivity.MEDIUM.value)
        sens = {f["sensitivity"] for f in bundle.facts}
        check("LOW + MEDIUM facts present",
              sens == {L.Sensitivity.LOW.value, L.Sensitivity.MEDIUM.value},
              f"got {sens}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_export_secret_is_never_emitted():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _populate(ctx)
        # Even at SECRET ceiling, SECRET facts are excluded.
        bundle = L.build_identity_export(ctx, ceiling=L.Sensitivity.SECRET.value)
        for f in bundle.facts:
            check(f"fact '{f['text'][:30]}' is not SECRET",
                  f["sensitivity"] != L.Sensitivity.SECRET.value)
        # Bundle ceiling field downgraded to HIGH.
        check("bundle ceiling downgraded from SECRET to HIGH",
              bundle.sensitivity_ceiling == L.Sensitivity.HIGH.value)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_export_with_consumer_routes_through_audit():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _populate(ctx)
        consumer = L.Consumer("auditor", "Auditor")
        grant    = L.ConsumerGrant("auditor",
                                     sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
                                     allowed_destinations=["user_export"])
        bundle = L.build_identity_export(
            ctx, ceiling=L.Sensitivity.MEDIUM.value,
            consumer=consumer, grant=grant,
        )
        rows = ctx.audit.read_all()
        check("audit log received >= 1 entry from export",
              len(rows) >= 1, f"got {len(rows)}")
        check("all logged entries used destination=user_export",
              all(r.destination == "user_export" for r in rows))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_export_no_business_no_snapshots_flags():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.business.register(L.BusinessProfile(business_id="b1", display_name="B1"),
                                set_active=True)
        ctx.snapshots.put("t0", L.capture_present(ctx.identity))
        bundle = L.build_identity_export(ctx,
                                          include_business=False,
                                          include_snapshots=False)
        check("include_business=False -> 0 businesses", len(bundle.businesses) == 0)
        check("include_snapshots=False -> 0 snapshots", len(bundle.snapshots) == 0)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- import ----------
def test_roundtrip_export_then_import_fresh_context():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx_src = _boot()
        _populate(ctx_src)
        bundle = L.build_identity_export(ctx_src, ceiling=L.Sensitivity.HIGH.value)

        # Wipe and reload to a clean context.
        for p in tmp.iterdir():
            if p.is_file():
                p.unlink()
        ctx_dst = _boot()
        check("destination starts with 0 facts",
              len(ctx_dst.identity.doc.facts) == 0)

        rep = L.apply_identity_import(ctx_dst, bundle, conflict="merge")
        check("import reports >=2 facts added",
              rep.facts_added >= 2, f"got {rep.facts_added}")
        check("imported north stars present",
              any("present partner" in n.text.lower()
                  for n in ctx_dst.identity.doc.north_stars))
        check("imported rules present",
              any("direct" in r.text.lower()
                  for r in ctx_dst.identity.doc.constitutional_rules))
        check("SECRET fact NOT imported",
              not any("hunter2" in f.text for f in ctx_dst.identity.doc.facts))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_import_merge_increments_seen_count():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        f = ctx.identity.add_fact("I work as a designer.",
                                    domain=L.LifeDomain.CAREER.value,
                                    confidence=0.7)
        before = f.seen_count
        bundle = L.IdentityExport(
            facts=[{"text": "I work as a designer.",
                    "domain": "career",
                    "sensitivity": L.Sensitivity.LOW.value,
                    "confidence": 0.9,
                    "seen_count": 3}],
        )
        rep = L.apply_identity_import(ctx, bundle, conflict="merge")
        check("merge updated 1 fact", rep.facts_updated == 1)
        check("seen_count incremented", f.seen_count > before)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_import_skip_leaves_existing_untouched():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("I work as a designer.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.7)
        bundle = L.IdentityExport(
            facts=[{"text": "I work as a designer.",
                    "domain": "career",
                    "sensitivity": L.Sensitivity.LOW.value,
                    "confidence": 0.99}],
        )
        rep = L.apply_identity_import(ctx, bundle, conflict="skip")
        check("skip reports 1 skipped, 0 updated, 0 added",
              rep.facts_skipped == 1
              and rep.facts_updated == 0
              and rep.facts_added == 0,
              f"got {rep}")
        f = ctx.identity.doc.facts[0]
        check("existing confidence unchanged at skip",
              abs(f.confidence - 0.7) < 0.01, f"got {f.confidence}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_import_overwrite_replaces_confidence():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.identity.add_fact("I work as a designer.",
                              domain=L.LifeDomain.CAREER.value, confidence=0.5)
        bundle = L.IdentityExport(
            facts=[{"text": "I work as a designer.",
                    "domain": "career",
                    "sensitivity": L.Sensitivity.LOW.value,
                    "confidence": 0.99}],
        )
        L.apply_identity_import(ctx, bundle, conflict="overwrite")
        f = ctx.identity.doc.facts[0]
        check("overwrite raised confidence to 0.99",
              abs(f.confidence - 0.99) < 1e-6, f"got {f.confidence}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_import_never_accepts_secret_via_bundle():
    """An attacker-crafted bundle setting sensitivity=SECRET must be
    downgraded by the importer (re-classified by the heuristic)."""
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        bundle = L.IdentityExport(
            facts=[{"text": "I love hiking on weekends.",
                    "domain": "lifestyle",
                    "sensitivity": L.Sensitivity.SECRET.value,
                    "confidence": 0.9}],
        )
        L.apply_identity_import(ctx, bundle)
        f = ctx.identity.doc.facts[0]
        check("imported fact's sensitivity is NOT SECRET",
              f.sensitivity != L.Sensitivity.SECRET.value,
              f"got {f.sensitivity}")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_import_businesses_and_snapshots():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx_src = _boot()
        ctx_src.business.register(
            L.BusinessProfile(business_id="acme", display_name="Acme Co",
                              legal_entity="LLC", role="founder"),
            set_active=True,
        )
        ctx_src.snapshots.put("baseline", L.capture_present(ctx_src.identity))
        bundle = L.build_identity_export(ctx_src)

        for p in tmp.iterdir():
            if p.is_file(): p.unlink()
        ctx_dst = _boot()
        rep = L.apply_identity_import(ctx_dst, bundle)
        check("1 business imported", rep.businesses_added == 1)
        check("1 snapshot imported", rep.snapshots_added == 1)
        check("acme registered", "acme" in ctx_dst.business.profiles)
        check("baseline snapshot label restored",
              "baseline" in ctx_dst.snapshots.snapshots)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- MCP wrapper ----------
def test_export_tool_via_mcp():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        _populate(ctx)
        ctx.mcp.register_consumer(
            L.Consumer("c1", "Test"),
            L.ConsumerGrant("c1",
                             sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
                             allowed_destinations=["mcp"]),
        )
        resp = ctx.mcp.handle(L.MCPRequest(
            method="tools/call", consumer_id="c1",
            params={"name": "export_identity",
                    "ceiling": L.Sensitivity.LOW.value},
        ))
        check("export_identity tool ok", resp.ok and resp.result["ok"],
              f"got {resp.error or resp.result}")
        check("stats.facts > 0", resp.result["stats"]["facts"] >= 1)
        check("bundle ceiling = LOW",
              resp.result["bundle"]["sensitivity_ceiling"] == "low")
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_import_tool_via_mcp():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.mcp.register_consumer(
            L.Consumer("c1", "Test"),
            L.ConsumerGrant("c1",
                             sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
                             allowed_destinations=["mcp"]),
        )
        bundle = {
            "schema_version": 1,
            "facts": [{"text": "I cook on weekends.",
                       "domain": "lifestyle",
                       "sensitivity": "low",
                       "confidence": 0.8}],
            "north_stars": [],
            "rules": [],
            "businesses": [],
            "snapshots": {},
        }
        resp = ctx.mcp.handle(L.MCPRequest(
            method="tools/call", consumer_id="c1",
            params={"name": "import_identity",
                    "bundle": bundle, "conflict": "merge"},
        ))
        check("import_identity ok", resp.ok and resp.result["ok"],
              f"got {resp.error or resp.result}")
        check("imported fact in store",
              any("cook" in f.text.lower() for f in ctx.identity.doc.facts))
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_import_tool_rejects_missing_bundle():
    tmp = Path(tempfile.mkdtemp(prefix="sp18_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = _boot()
        ctx.mcp.register_consumer(
            L.Consumer("c1", "Test"),
            L.ConsumerGrant("c1",
                             sensitivity_ceiling=L.Sensitivity.LOW.value,
                             allowed_destinations=["mcp"]),
        )
        resp = ctx.mcp.handle(L.MCPRequest(
            method="tools/call", consumer_id="c1",
            params={"name": "import_identity"},
        ))
        check("missing bundle -> ok:False with error",
              resp.ok and not resp.result["ok"]
              and resp.result["error"] == "missing_bundle",
              f"got {resp.result}")
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
        test_export_low_ceiling_only_includes_low,
        test_export_medium_ceiling_includes_low_and_medium,
        test_export_secret_is_never_emitted,
        test_export_with_consumer_routes_through_audit,
        test_export_no_business_no_snapshots_flags,
        test_roundtrip_export_then_import_fresh_context,
        test_import_merge_increments_seen_count,
        test_import_skip_leaves_existing_untouched,
        test_import_overwrite_replaces_confidence,
        test_import_never_accepts_secret_via_bundle,
        test_import_businesses_and_snapshots,
        test_export_tool_via_mcp,
        test_import_tool_via_mcp,
        test_import_tool_rejects_missing_bundle,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 18 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
