"""Sprint 8 - MCP Privacy Foundation tests. Standalone."""
from __future__ import annotations
import sys, time, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp():
    return Path(tempfile.mkdtemp(prefix="sprint8_"))


# ---------- Envelope ----------
def test_envelope_roundtrip():
    e = L.PrivacyEnvelope.seal("hello world",
                               L.Sensitivity.MEDIUM.value,
                               L.LifeDomain.FINANCIAL.value,
                               key=b"abc123")
    check("envelope payload obfuscated (not plaintext)",
          "hello world" not in e.payload_b64)
    opened = e.open(b"abc123")
    check("envelope opens with same key", opened == "hello world", f"got {opened!r}")


def test_envelope_wrong_key_returns_garbage():
    e = L.PrivacyEnvelope.seal("secret payload",
                               L.Sensitivity.HIGH.value,
                               L.LifeDomain.HEALTH.value,
                               key=b"the right key")
    bad = e.open(b"other key entirely")
    check("wrong key does NOT yield original text",
          bad != "secret payload")


# ---------- Grants ----------
def test_grant_active_until_expiry():
    g = L.ConsumerGrant(consumer_id="c1", sensitivity_ceiling=L.Sensitivity.LOW.value)
    check("no expiry -> always active", g.is_active())
    g2 = L.ConsumerGrant(consumer_id="c1", expires_at=time.time() + 60)
    check("future expiry -> active", g2.is_active())
    g3 = L.ConsumerGrant(consumer_id="c1", expires_at=time.time() - 60)
    check("past expiry -> inactive", not g3.is_active())


# ---------- Audit log ----------
def test_audit_log_append_and_read():
    tmp = _tmp()
    try:
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        log.append(L.AccessAuditEntry(consumer_id="c1", decision="allow", reason="ok"))
        log.append(L.AccessAuditEntry(consumer_id="c2", decision="deny", reason="blocked"))
        rows = log.read_all()
        check("2 rows persisted", len(rows) == 2)
        check("row decision preserved", rows[0].decision == "allow")
    finally: shutil.rmtree(tmp, ignore_errors=True)


def test_audit_log_filter():
    tmp = _tmp()
    try:
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        log.append(L.AccessAuditEntry(consumer_id="c1", decision="allow"))
        log.append(L.AccessAuditEntry(consumer_id="c1", decision="deny"))
        log.append(L.AccessAuditEntry(consumer_id="c2", decision="deny"))
        c1_denies = log.filter(consumer_id="c1", decision="deny")
        check("filter narrows to c1 denies", len(c1_denies) == 1,
              f"got {len(c1_denies)}")
    finally: shutil.rmtree(tmp, ignore_errors=True)


# ---------- Audited egress ----------
def test_egress_secret_always_denied():
    tmp = _tmp()
    try:
        consumer = L.Consumer(consumer_id="c1", display_name="Test")
        grant = L.ConsumerGrant(
            consumer_id="c1",
            sensitivity_ceiling=L.Sensitivity.SECRET.value,
            allowed_destinations=["remote_api"],
        )
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        ok, reason, _ = L.audited_egress(
            "My password is hunter2.", consumer, grant, "remote_api", log,
        )
        check("SECRET content denied even with ceiling=SECRET (router veto)",
              not ok, f"reason={reason}")
        check("audit log captured the denial", len(log.read_all()) == 1)
    finally: shutil.rmtree(tmp, ignore_errors=True)


def test_egress_domain_scope_enforced():
    tmp = _tmp()
    try:
        consumer = L.Consumer(consumer_id="c1", display_name="Test")
        grant = L.ConsumerGrant(
            consumer_id="c1",
            allowed_domains=[L.LifeDomain.FINANCIAL.value],
            sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
            allowed_destinations=["remote_api"],
        )
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        ok, reason, _ = L.audited_egress(
            "My wife is a teacher.", consumer, grant, "remote_api", log,
        )
        check("relationships content denied (not in financial scope)",
              not ok and "domain" in reason, f"reason={reason}")
    finally: shutil.rmtree(tmp, ignore_errors=True)


def test_egress_sensitivity_ceiling_enforced():
    tmp = _tmp()
    try:
        consumer = L.Consumer(consumer_id="c1", display_name="Test")
        grant = L.ConsumerGrant(
            consumer_id="c1",
            sensitivity_ceiling=L.Sensitivity.LOW.value,
            allowed_destinations=["remote_api"],
        )
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        ok, reason, _ = L.audited_egress(
            "My salary is $90k.", consumer, grant, "remote_api", log,
        )
        check("MEDIUM-tagged text denied under LOW ceiling",
              not ok and "ceiling" in reason, f"reason={reason}")
    finally: shutil.rmtree(tmp, ignore_errors=True)


def test_egress_destination_grant_enforced():
    tmp = _tmp()
    try:
        consumer = L.Consumer(consumer_id="c1", display_name="Test")
        grant = L.ConsumerGrant(
            consumer_id="c1",
            sensitivity_ceiling=L.Sensitivity.LOW.value,
            allowed_destinations=["remote_api"],   # NOT user_export
        )
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        ok, reason, _ = L.audited_egress(
            "It rained today.", consumer, grant, "user_export", log,
        )
        check("destination not in grant -> denied",
              not ok and "destination" in reason, f"reason={reason}")
    finally: shutil.rmtree(tmp, ignore_errors=True)


def test_egress_allow_path():
    tmp = _tmp()
    try:
        consumer = L.Consumer(consumer_id="c1", display_name="Test")
        grant = L.ConsumerGrant(
            consumer_id="c1",
            sensitivity_ceiling=L.Sensitivity.LOW.value,
            allowed_destinations=["remote_api"],
        )
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        ok, reason, entry = L.audited_egress(
            "It rained today.", consumer, grant, "remote_api", log,
        )
        check("LOW content in scope -> allowed", ok, f"reason={reason}")
        check("audit captures allow with digest, not payload",
              entry.decision == "allow"
              and entry.payload_chars > 0
              and len(entry.payload_digest) == 12
              and "rained" not in entry.payload_digest)
    finally: shutil.rmtree(tmp, ignore_errors=True)


def test_egress_expired_grant_denied():
    tmp = _tmp()
    try:
        consumer = L.Consumer(consumer_id="c1", display_name="Test")
        grant = L.ConsumerGrant(
            consumer_id="c1",
            sensitivity_ceiling=L.Sensitivity.LOW.value,
            allowed_destinations=["remote_api"],
            expires_at=time.time() - 60,
        )
        log = L.AccessAuditLog(tmp / "audit.jsonl")
        ok, reason, _ = L.audited_egress(
            "It rained today.", consumer, grant, "remote_api", log,
        )
        check("expired grant denied", not ok and reason == "grant_expired",
              f"reason={reason}")
    finally: shutil.rmtree(tmp, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_envelope_roundtrip,
        test_envelope_wrong_key_returns_garbage,
        test_grant_active_until_expiry,
        test_audit_log_append_and_read,
        test_audit_log_filter,
        test_egress_secret_always_denied,
        test_egress_domain_scope_enforced,
        test_egress_sensitivity_ceiling_enforced,
        test_egress_destination_grant_enforced,
        test_egress_allow_path,
        test_egress_expired_grant_denied,
        test_no_regression,
    ]
    for t in tests:
        try: t()
        except Exception as e: results.append((t.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 8 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
