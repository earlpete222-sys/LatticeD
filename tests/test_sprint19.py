"""Sprint 19 - encryption at rest tests. Standalone."""
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


def _disable_encryption_for_test_isolation():
    """Module-level test isolation: ensure no encryption hooks leak in."""
    L.install_encrypted_persistence(None)


# ---------- payload primitives ----------
def test_envelope_roundtrip():
    env = L.encrypt_payload('{"hello": "world"}', "secret-pass")
    pt  = L.decrypt_payload(env, "secret-pass")
    check("encrypt/decrypt roundtrip", pt == '{"hello": "world"}', f"got {pt!r}")


def test_envelope_envelope_shape():
    env_raw = L.encrypt_payload('payload', "pw")
    env = json.loads(env_raw)
    check("envelope is JSON dict", isinstance(env, dict))
    check("envelope has schema=1", env.get("schema") == 1)
    check("envelope has ciphertext", "ciphertext" in env and len(env["ciphertext"]) > 0)
    check("envelope alg is recognized",
          env.get("alg") in ("fernet", "xor-sha256"), f"got {env.get('alg')}")


def test_decrypt_wrong_passphrase_raises():
    env = L.encrypt_payload('secret stuff', "right")
    try:
        L.decrypt_payload(env, "wrong")
        check("wrong passphrase raises DecryptError", False, "no exception")
    except L.DecryptError:
        check("wrong passphrase raises DecryptError", True)
    except Exception as e:
        check("wrong passphrase raises DecryptError", False,
              f"got {type(e).__name__}: {e}")


def test_encrypt_empty_passphrase_rejected():
    try:
        L.encrypt_payload("data", "")
        check("empty passphrase rejected", False, "no exception")
    except ValueError:
        check("empty passphrase rejected", True)


def test_envelope_round_trip_long_text():
    big = "x" * 200_000
    env = L.encrypt_payload(big, "pw")
    out = L.decrypt_payload(env, "pw")
    check("200k roundtrip preserves content", out == big)


# ---------- file helpers ----------
def test_atomic_write_then_read_encrypted():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    try:
        path = tmp / "data.json"
        L.atomic_write_encrypted(path, '{"a":1}', "secret")
        # On disk, the file is an envelope, NOT the plaintext.
        raw = path.read_text(encoding="utf-8")
        check("on-disk file is encrypted envelope", L._looks_like_envelope(raw),
              f"got: {raw[:120]!r}")
        check("plaintext NOT visible on disk", '"a":1' not in raw, f"got: {raw[:120]!r}")
        pt = L.atomic_read_encrypted(path, "secret")
        check("read returns original plaintext", pt == '{"a":1}', f"got {pt!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_read_legacy_plain_file_is_passed_through():
    """Backward compat: existing plain JSON files keep loading."""
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    try:
        path = tmp / "data.json"
        path.write_text('{"plain":true}', encoding="utf-8")
        pt = L.atomic_read_encrypted(path, "any-pp")
        check("plain JSON returned verbatim", pt == '{"plain":true}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_read_missing_returns_empty():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    try:
        pt = L.atomic_read_encrypted(tmp / "nope.json", "pp")
        check("missing file -> empty string", pt == "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- IdentityStore with encryption ----------
def test_encrypted_identity_store_roundtrip():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence("my-passphrase")
        s = L.IdentityStore(L.IDENTITY_PATH, user_id="enc")
        s.add_fact("I work as a designer.", domain=L.LifeDomain.CAREER.value,
                    confidence=0.9)
        s.add_north_star("Lead a team.", domain=L.LifeDomain.CAREER.value, weight=1.5)
        s.add_rule("Be direct.", priority=200)
        s.save()

        raw = L.IDENTITY_PATH.read_text(encoding="utf-8")
        check("on-disk identity is an encrypted envelope",
              L._looks_like_envelope(raw), f"raw[:120]={raw[:120]!r}")
        check("designer plaintext NOT visible on disk",
              "designer" not in raw, f"raw[:200]={raw[:200]!r}")

        # Reload with same passphrase.
        s2 = L.IdentityStore(L.IDENTITY_PATH, user_id="enc").load()
        check("decrypted store recovers fact",
              any("designer" in f.text for f in s2.doc.facts))
        check("decrypted store recovers north star",
              any("lead a team" in n.text.lower() for n in s2.doc.north_stars))
        check("decrypted store recovers rule",
              any("direct" in r.text.lower() for r in s2.doc.constitutional_rules))
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_encrypted_store_wrong_passphrase_yields_empty_doc():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence("correct-pp")
        s = L.IdentityStore(L.IDENTITY_PATH, user_id="enc")
        s.add_fact("Plaintext data here.")
        s.save()

        L.install_encrypted_persistence("wrong-pp")
        s2 = L.IdentityStore(L.IDENTITY_PATH, user_id="enc").load()
        check("wrong passphrase yields empty fact list",
              len(s2.doc.facts) == 0,
              f"got {len(s2.doc.facts)} facts")
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- BusinessStore + Snapshots + Continuity + Voice + Prompt evo + Ledger ----------
def test_encryption_applies_to_business_store():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence("pp")
        bs = L.BusinessStore(L.BUSINESS_PATH)
        bs.register(L.BusinessProfile(business_id="acme", display_name="Acme Co",
                                        role="founder"),
                     set_active=True)
        bs.save()
        raw = L.BUSINESS_PATH.read_text(encoding="utf-8")
        check("business file is encrypted",
              L._looks_like_envelope(raw)
              and "Acme Co" not in raw,
              f"raw[:120]={raw[:120]!r}")
        bs2 = L.BusinessStore(L.BUSINESS_PATH).load()
        check("business store reload recovers profile",
              "acme" in bs2.profiles and bs2.active_id == "acme")
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_encryption_applies_to_snapshot_store():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence("pp")
        store = L.IdentityStore(L.IDENTITY_PATH, user_id="t")
        store.add_fact("hello world.", domain=L.LifeDomain.LIFESTYLE.value, confidence=0.8)
        snap = L.SnapshotStore(L.SNAPSHOTS_PATH)
        snap.put("t0", L.capture_present(store))
        snap.save()
        raw = L.SNAPSHOTS_PATH.read_text(encoding="utf-8")
        check("snapshot file is encrypted", L._looks_like_envelope(raw))
        snap2 = L.SnapshotStore(L.SNAPSHOTS_PATH).load()
        check("snapshot reload recovers label",
              "t0" in snap2.snapshots)
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_encryption_applies_to_ledger():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence("pp")
        ledger = L.EngagementLedger(L.CURIOSITY_PATH)
        ledger.add(L.CuriosityEngagement(
            question="q?", domain=L.LifeDomain.CAREER.value,
            gap_type=L.GapType.LOW_COVERAGE.value, answered=True,
        ))
        ledger.save()
        raw = L.CURIOSITY_PATH.read_text(encoding="utf-8")
        check("ledger file is encrypted",
              L._looks_like_envelope(raw) and "q?" not in raw)
        ledger2 = L.EngagementLedger(L.CURIOSITY_PATH).load()
        check("ledger reload recovers entry",
              len(ledger2.entries) == 1 and ledger2.entries[0].question == "q?")
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_encryption_applies_to_continuity_and_voice_and_prompt_evo():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        L.install_encrypted_persistence("pp")
        cs = L.ContinuityStore(L.CONTINUITY_PATH)
        cs.add(L.ContinuityToken(session_id="s1", summary="signed deal"))
        cs.save()
        check("continuity file is encrypted",
              L._looks_like_envelope(L.CONTINUITY_PATH.read_text(encoding="utf-8")))

        v = L.VoiceEvolutionEngine(L.VOICE_PROFILES_PATH)
        v.record_interaction(L.EngagementSignal(
            agent_id="fast_mentor", output_chars=80, user_explicit_positive=True,
        ))
        v.save()
        check("voice file is encrypted",
              L._looks_like_envelope(L.VOICE_PROFILES_PATH.read_text(encoding="utf-8")))

        pe = L.PromptEvolutionEngine(L.PROMPT_EVOLUTION_PATH)
        pe.seed("fast_mentor", "Be warm.")
        pe.save()
        check("prompt evo file is encrypted",
              L._looks_like_envelope(L.PROMPT_EVOLUTION_PATH.read_text(encoding="utf-8")))

        # And all three reload cleanly.
        cs2 = L.ContinuityStore(L.CONTINUITY_PATH).load()
        check("continuity reload",
              len(cs2.tokens) == 1 and cs2.tokens[0].summary == "signed deal")
        v2 = L.VoiceEvolutionEngine(L.VOICE_PROFILES_PATH).load()
        check("voice reload", "fast_mentor" in v2.profiles)
        pe2 = L.PromptEvolutionEngine(L.PROMPT_EVOLUTION_PATH).load()
        check("prompt evo reload", "fast_mentor" in pe2.populations)
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- backward-compat migration ----------
def test_legacy_plain_file_loads_under_encryption():
    """An existing plain JSON file (from before encryption was enabled)
    should still load - giving users a one-shot migration path."""
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        # Write plain identity.json BEFORE enabling encryption.
        s = L.IdentityStore(L.IDENTITY_PATH, user_id="legacy")
        s.add_fact("This existed before encryption was turned on.",
                   domain=L.LifeDomain.LIFESTYLE.value, confidence=0.9)
        s.save()
        plain_on_disk = L.IDENTITY_PATH.read_text(encoding="utf-8")
        check("legacy file written as plain JSON",
              not L._looks_like_envelope(plain_on_disk))

        # Now turn encryption on and load.
        L.install_encrypted_persistence("pp")
        s2 = L.IdentityStore(L.IDENTITY_PATH, user_id="legacy").load()
        check("legacy plain JSON loads cleanly with encryption enabled",
              any("before encryption" in f.text for f in s2.doc.facts))

        # Saving will re-write it as an encrypted envelope.
        s2.save()
        check("subsequent save writes encrypted envelope",
              L._looks_like_envelope(L.IDENTITY_PATH.read_text(encoding="utf-8")))
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- LatticeContext integration ----------
def test_lattice_context_encrypt_at_rest_flag():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot(
            user_id="enc-ctx",
            tier_override="minimal_gpu",
            encrypt_at_rest=True,
            passphrase="boot-pp",
        )
        ctx.identity.add_fact("I drink iced coffee daily.",
                              domain=L.LifeDomain.LIFESTYLE.value, confidence=0.9)
        ctx.save_all()
        on_disk = L.IDENTITY_PATH.read_text(encoding="utf-8")
        check("ctx-boot encryption hides plaintext on disk",
              L._looks_like_envelope(on_disk) and "iced coffee" not in on_disk)
    finally:
        L.install_encrypted_persistence(None)
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_lattice_context_env_passphrase_auto_enables():
    import os
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    os.environ["LATTICED_PASSPHRASE"] = "envvar-pp"
    try:
        ctx = L.LatticeContext.boot(user_id="env-ctx", tier_override="minimal_gpu")
        ctx.identity.add_fact("envvar fact.", confidence=0.9)
        ctx.save_all()
        on_disk = L.IDENTITY_PATH.read_text(encoding="utf-8")
        check("LATTICED_PASSPHRASE env auto-enables encryption",
              L._looks_like_envelope(on_disk) and "envvar fact" not in on_disk,
              f"got {on_disk[:200]}")
    finally:
        L.install_encrypted_persistence(None)
        del os.environ["LATTICED_PASSPHRASE"]
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


def test_lattice_context_no_passphrase_is_plain():
    tmp = Path(tempfile.mkdtemp(prefix="sp19_"))
    orig = _redirect_paths(tmp)
    try:
        ctx = L.LatticeContext.boot(user_id="plain", tier_override="minimal_gpu")
        ctx.identity.add_fact("This stays plain.", confidence=0.9)
        ctx.save_all()
        on_disk = L.IDENTITY_PATH.read_text(encoding="utf-8")
        check("no passphrase keeps plain JSON",
              "This stays plain." in on_disk)
    finally:
        _restore(orig); shutil.rmtree(tmp, ignore_errors=True)


# ---------- regression ----------
def test_no_regression():
    _disable_encryption_for_test_isolation()
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_envelope_roundtrip,
        test_envelope_envelope_shape,
        test_decrypt_wrong_passphrase_raises,
        test_encrypt_empty_passphrase_rejected,
        test_envelope_round_trip_long_text,
        test_atomic_write_then_read_encrypted,
        test_atomic_read_legacy_plain_file_is_passed_through,
        test_atomic_read_missing_returns_empty,
        test_encrypted_identity_store_roundtrip,
        test_encrypted_store_wrong_passphrase_yields_empty_doc,
        test_encryption_applies_to_business_store,
        test_encryption_applies_to_snapshot_store,
        test_encryption_applies_to_ledger,
        test_encryption_applies_to_continuity_and_voice_and_prompt_evo,
        test_legacy_plain_file_loads_under_encryption,
        test_lattice_context_encrypt_at_rest_flag,
        test_lattice_context_env_passphrase_auto_enables,
        test_lattice_context_no_passphrase_is_plain,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 19 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
