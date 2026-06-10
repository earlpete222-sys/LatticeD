"""
Sprint 1 — Persistent Identity Foundation + Privacy Seeds regression tests.

Standalone (no server, no Ollama). Exit code 0 = all pass.

Usage:
    python tests/test_sprint1.py
"""

from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "latticed"))

import latticed as L  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, PASS if cond else FAIL, detail))


# ---------------------------------------------------------------------
# LifeDomain / classifier
# ---------------------------------------------------------------------
def test_classify_domain_financial() -> None:
    d = L.classify_domain("I need to figure out my budget for next month — rent, savings, debt.")
    check("financial keywords -> FINANCIAL", d == L.LifeDomain.FINANCIAL.value, f"got {d}")


def test_classify_domain_relationships() -> None:
    d = L.classify_domain("My wife and I are arguing more lately.")
    check("relationship keywords -> RELATIONSHIPS",
          d == L.LifeDomain.RELATIONSHIPS.value, f"got {d}")


def test_classify_domain_uncategorized() -> None:
    d = L.classify_domain("The sky is blue.")
    check("no signal -> UNCATEGORIZED",
          d == L.LifeDomain.UNCATEGORIZED.value, f"got {d}")


def test_classify_domain_career_vs_business() -> None:
    career  = L.classify_domain("My boss gave me a raise after my performance review.")
    biz     = L.classify_domain("Our startup closed its first client contract this quarter.")
    check("career signal -> CAREER",   career == L.LifeDomain.CAREER.value,   f"got {career}")
    check("business signal -> BUSINESS", biz    == L.LifeDomain.BUSINESS.value, f"got {biz}")


# ---------------------------------------------------------------------
# SensitivityRouter
# ---------------------------------------------------------------------
def test_sensitivity_classify_high_ssn() -> None:
    s = L.SensitivityRouter.classify_text("My SSN is 123-45-6789.")
    check("SSN-pattern flagged HIGH", s == L.Sensitivity.HIGH.value, f"got {s}")


def test_sensitivity_classify_high_medical() -> None:
    s = L.SensitivityRouter.classify_text("My therapist prescribed a new dosage this week.")
    check("medical/therapist flagged HIGH",
          s == L.Sensitivity.HIGH.value, f"got {s}")


def test_sensitivity_classify_medium_financial() -> None:
    s = L.SensitivityRouter.classify_text("My salary is okay but my debt is rising.")
    check("salary/debt language flagged MEDIUM",
          s == L.Sensitivity.MEDIUM.value, f"got {s}")


def test_sensitivity_classify_low_default() -> None:
    s = L.SensitivityRouter.classify_text("It rained today.")
    check("benign text classified LOW",
          s == L.Sensitivity.LOW.value, f"got {s}")


def test_egress_secret_blocked_everywhere() -> None:
    for dest in ("remote_api", "public_search", "user_export"):
        allowed, _ = L.SensitivityRouter.allow_egress(L.Sensitivity.SECRET.value, dest)
        check(f"SECRET -> {dest} blocked", not allowed)


def test_egress_high_blocked_from_search_and_api() -> None:
    a1, _ = L.SensitivityRouter.allow_egress(L.Sensitivity.HIGH.value, "remote_api")
    a2, _ = L.SensitivityRouter.allow_egress(L.Sensitivity.HIGH.value, "public_search")
    a3, _ = L.SensitivityRouter.allow_egress(L.Sensitivity.HIGH.value, "user_export")
    check("HIGH blocked from remote_api",    not a1)
    check("HIGH blocked from public_search", not a2)
    check("HIGH allowed to user_export (with confirmation)", a3)


def test_egress_medium_routing() -> None:
    a_api,    _ = L.SensitivityRouter.allow_egress(L.Sensitivity.MEDIUM.value, "remote_api")
    a_search, _ = L.SensitivityRouter.allow_egress(L.Sensitivity.MEDIUM.value, "public_search")
    check("MEDIUM allowed to remote_api",       a_api)
    check("MEDIUM blocked from public_search",  not a_search)


def test_egress_low_passthrough() -> None:
    for dest in ("remote_api", "public_search", "user_export"):
        allowed, _ = L.SensitivityRouter.allow_egress(L.Sensitivity.LOW.value, dest)
        check(f"LOW -> {dest} allowed", allowed)


def test_egress_local_always_allowed() -> None:
    for tag in (L.Sensitivity.LOW.value, L.Sensitivity.HIGH.value, L.Sensitivity.SECRET.value):
        allowed, _ = L.SensitivityRouter.allow_egress(tag, "local")
        check(f"{tag} -> local always allowed", allowed)


# ---------------------------------------------------------------------
# IdentityStore + IdentityDocument
# ---------------------------------------------------------------------
def _tmp_store() -> tuple[L.IdentityStore, Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix="sprint1_"))
    store = L.IdentityStore(path=tmpdir / "identity.json", user_id="test_user")
    return store, tmpdir


def test_identity_roundtrip() -> None:
    store, tmp = _tmp_store()
    try:
        store.add_fact("I have two kids.", confidence=0.9)
        store.add_north_star("Be a present father.", weight=1.5)
        store.add_rule("Never lie to me about money.", priority=200)
        store.save()
        # Reload from disk
        store2 = L.IdentityStore(path=store.path).load()
        check("round-trip: 1 fact persisted",
              len(store2.doc.facts) == 1, f"got {len(store2.doc.facts)} facts")
        check("round-trip: north star persisted",
              len(store2.doc.north_stars) == 1)
        check("round-trip: constitutional rule persisted",
              len(store2.doc.constitutional_rules) == 1)
        check("round-trip: user_id preserved",
              store2.doc.user_id == "test_user", f"got {store2.doc.user_id}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_identity_dedup_increments_seen_count() -> None:
    store, tmp = _tmp_store()
    try:
        store.add_fact("I work in healthcare.")
        store.add_fact("  i WORK in healthcare.  ")     # same fact, different case + spacing
        check("identical normalized fact deduped",
              len(store.doc.facts) == 1, f"got {len(store.doc.facts)}")
        check("seen_count incremented", store.doc.facts[0].seen_count == 2,
              f"got seen_count={store.doc.facts[0].seen_count}")
        check("confidence bumped on repeat",
              store.doc.facts[0].confidence > 0.7)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_identity_facts_for_domain() -> None:
    store, tmp = _tmp_store()
    try:
        store.add_fact("My salary is $90k.")            # financial
        store.add_fact("My wife is a teacher.")          # relationships
        store.add_fact("I work out three times a week.") # health
        fin = store.facts_for_domain(L.LifeDomain.FINANCIAL.value)
        rel = store.facts_for_domain(L.LifeDomain.RELATIONSHIPS.value)
        hlt = store.facts_for_domain(L.LifeDomain.HEALTH.value)
        check("financial fact bucketed", len(fin) == 1, f"got {[f.text for f in fin]}")
        check("relationships fact bucketed", len(rel) == 1, f"got {[f.text for f in rel]}")
        check("health fact bucketed", len(hlt) == 1, f"got {[f.text for f in hlt]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_identity_sensitivity_auto_tag() -> None:
    store, tmp = _tmp_store()
    try:
        f1 = store.add_fact("My SSN is 999-88-7777.")
        f2 = store.add_fact("I drink coffee.")
        check("auto-tag SSN as HIGH", f1.sensitivity == L.Sensitivity.HIGH.value, f"got {f1.sensitivity}")
        check("auto-tag benign fact as LOW", f2.sensitivity == L.Sensitivity.LOW.value, f"got {f2.sensitivity}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_identity_facts_above_sensitivity_filter() -> None:
    store, tmp = _tmp_store()
    try:
        store.add_fact("My SSN is 999-88-7777.")                # HIGH
        store.add_fact("My salary is $90k.")                    # MEDIUM
        store.add_fact("I drink coffee in the mornings.")       # LOW
        high_plus = store.facts_above_sensitivity(L.Sensitivity.HIGH.value)
        med_plus  = store.facts_above_sensitivity(L.Sensitivity.MEDIUM.value)
        check("filter >= HIGH returns 1", len(high_plus) == 1, f"got {[f.text for f in high_plus]}")
        check("filter >= MEDIUM returns 2", len(med_plus) == 2, f"got {[f.text for f in med_plus]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_north_stars_sorted_by_weight() -> None:
    store, tmp = _tmp_store()
    try:
        store.add_north_star("Stay curious.", weight=0.5)
        store.add_north_star("Be a present father.", weight=1.5)
        store.add_north_star("Financial independence by 50.", weight=1.0)
        ns = store.active_north_stars()
        check("north stars sorted by weight desc",
              ns[0].weight == 1.5 and ns[-1].weight == 0.5,
              f"order={[n.weight for n in ns]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_constitutional_rules_sorted_by_priority() -> None:
    store, tmp = _tmp_store()
    try:
        store.add_rule("Be brief by default.", priority=50)
        store.add_rule("Never lie about money.", priority=200)
        store.add_rule("Don't refer to me by my last name.", priority=120)
        rules = store.active_rules()
        check("rules sorted by priority desc",
              rules[0].priority == 200 and rules[-1].priority == 50,
              f"order={[r.priority for r in rules]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_missing_file_is_noop() -> None:
    store, tmp = _tmp_store()
    try:
        # Don't save first - load should be a clean noop
        store.load()
        check("load on missing path leaves doc empty",
              len(store.doc.facts) == 0 and len(store.doc.north_stars) == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_save_no_partial_file() -> None:
    store, tmp = _tmp_store()
    try:
        store.add_fact("My budget needs work.")
        store.save()
        # The tmp file should not linger after a successful save
        assert not store.path.with_suffix(store.path.suffix + ".tmp").exists(), \
            "stale .tmp file from atomic save"
        check("atomic save cleans up .tmp file", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------
# Biographer agent registration
# ---------------------------------------------------------------------
def test_biographer_registered() -> None:
    reg = L.AgentFactoryRegistry().registry
    check("biographer present in registry",
          "biographer" in reg, f"agents: {sorted(reg.keys())}")
    bio = reg["biographer"]
    check("biographer has structured_output capability",
          L.Capability.STRUCTURED_OUTPUT.value in bio.capabilities_required)
    check("biographer avoids creative_generation",
          L.Capability.CREATIVE_GENERATION.value in bio.capabilities_avoid)


def test_biographer_does_not_break_sprint0_validation() -> None:
    """Adding the biographer agent must NOT regress Sprint 0 validator."""
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU profile still validates with biographer present",
          rep.valid, f"errors={rep.errors}")
    check("agent count is 12 (11 + biographer)",
          len(reg) == 12, f"got {len(reg)}")


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------
def main() -> int:
    tests = [
        test_classify_domain_financial,
        test_classify_domain_relationships,
        test_classify_domain_uncategorized,
        test_classify_domain_career_vs_business,
        test_sensitivity_classify_high_ssn,
        test_sensitivity_classify_high_medical,
        test_sensitivity_classify_medium_financial,
        test_sensitivity_classify_low_default,
        test_egress_secret_blocked_everywhere,
        test_egress_high_blocked_from_search_and_api,
        test_egress_medium_routing,
        test_egress_low_passthrough,
        test_egress_local_always_allowed,
        test_identity_roundtrip,
        test_identity_dedup_increments_seen_count,
        test_identity_facts_for_domain,
        test_identity_sensitivity_auto_tag,
        test_identity_facts_above_sensitivity_filter,
        test_north_stars_sorted_by_weight,
        test_constitutional_rules_sorted_by_priority,
        test_load_missing_file_is_noop,
        test_atomic_save_no_partial_file,
        test_biographer_registered,
        test_biographer_does_not_break_sprint0_validation,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            results.append((t.__name__, FAIL, f"EXC {type(e).__name__}: {e}"))

    pass_count = sum(1 for _, s, _ in results if s == PASS)
    total = len(results)
    for name, status, detail in results:
        marker = "[OK]  " if status == PASS else "[XX]  "
        line = f"{marker}{name}"
        if detail:
            line += f"   - {detail}"
        print(line)
    print(f"\n{pass_count}/{total} Sprint 1 tests passed.")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
