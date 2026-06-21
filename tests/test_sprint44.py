"""Sprint 44 — Mobile-ready: device pairing, PWA manifest, auth integration.

Unit tests that exercise the pairing backend against a temporary SQLite store
and the PWA endpoints via FastAPI's TestClient. No phone, no Tailscale, no
live Ollama needed.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
sys.path.insert(0, str(HERE.parent))

import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


# ── Test fixture: point runtime at a fresh temp DB and init schema ───────────
_TMP = tempfile.TemporaryDirectory()
_TMP_PATH = Path(_TMP.name)
L.ROOT_DIR    = _TMP_PATH
L.STORAGE_DIR = _TMP_PATH / "storage"
L.DB_PATH     = L.STORAGE_DIR / "end_game.db"
L.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
# init_db reads runtime.open_db() which uses module-level DB_PATH.
L.runtime.init_db()


def _run(coro):
    """Run an async function from sync test code without nesting loops."""
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Helpers ──────────────────────────────────────────────────────────────────
def test_pairing_code_format():
    code = L._generate_pairing_code()
    check("code is 7 chars (NNN-NNN)", len(code) == 7, f"got {code!r}")
    check("code is XXX-XXX", code[3] == "-" and code.replace("-", "").isdigit(),
          f"got {code!r}")
    # 100 generations should be all digits + dash
    bad = [c for c in (L._generate_pairing_code() for _ in range(100))
           if not (len(c) == 7 and c[3] == "-" and c.replace("-", "").isdigit())]
    check("100 generations well-formed", not bad, f"{len(bad)} malformed")


def test_device_token_format():
    t = L._generate_device_token()
    check("token has ltd_ prefix", t.startswith(L.DEVICE_TOKEN_PREFIX))
    check("token is long (>=40 chars)", len(t) >= 40, f"len={len(t)}")
    # Two tokens differ
    check("two tokens unique", L._generate_device_token() != L._generate_device_token())


# ── Pairing flow end-to-end ──────────────────────────────────────────────────
def test_pairing_flow_happy_path():
    # Reset in-memory codes.
    L._pairing_codes.clear()

    # 1. Authenticated caller (home machine) requests a code.
    req = L.PairingCodeRequest(label_hint="phone-test")
    code_resp = _run(L.create_pairing_code(req, user_id=L.INTERNAL_USER_ID))
    code = code_resp["code"]
    check("/api/pair/code returns 7-char code", len(code) == 7)
    check("/api/pair/code returns expires_in", code_resp["expires_in"] == L.PAIRING_CODE_TTL)
    check("code stored in memory map", code in L._pairing_codes)

    # 2. Unauthenticated phone exchanges the code for a token.
    claim = L.PairingClaimRequest(code=code, label="Test Phone")
    claim_resp = _run(L.claim_pairing_code(claim))
    token = claim_resp["token"]
    check("/api/pair returns ltd_ token", token.startswith(L.DEVICE_TOKEN_PREFIX))
    check("/api/pair returns label", claim_resp["label"] == "Test Phone")
    check("code consumed (single-use)", code not in L._pairing_codes)

    # 3. Token authenticates against get_authenticated_user.
    uid = L.get_authenticated_user(x_api_key=token)
    check("token grants auth", uid == L.INTERNAL_USER_ID)

    # 4. Token is listed in /api/devices.
    listing = _run(L.list_devices(user_id=L.INTERNAL_USER_ID))
    labels = [d["label"] for d in listing["devices"]]
    check("token shows up in /api/devices", "Test Phone" in labels)
    prefix = next(d["token_prefix"] for d in listing["devices"] if d["label"] == "Test Phone")
    check("device entry has truncated prefix", prefix.endswith("..."))

    # 5. Revoking by prefix invalidates the token.
    bare_prefix = prefix[:-3]   # strip the trailing "..."
    revoke_resp = _run(L.revoke_device(token_prefix=bare_prefix, user_id=L.INTERNAL_USER_ID))
    check("revoke returns ok", revoke_resp["ok"] is True)
    check("revoked count >= 1", revoke_resp["deleted"] >= 1)

    # 6. Auth now rejects the revoked token.
    try:
        L.get_authenticated_user(x_api_key=token)
        check("revoked token rejected", False, "auth still accepted token")
    except L.HTTPException as e:
        check("revoked token rejected", e.status_code == 401, f"got {e.status_code}")


def test_pairing_unknown_code_404():
    L._pairing_codes.clear()
    claim = L.PairingClaimRequest(code="999-999", label="nope")
    try:
        _run(L.claim_pairing_code(claim))
        check("unknown code 404", False, "no exception raised")
    except L.HTTPException as e:
        check("unknown code 404", e.status_code == 404, f"got {e.status_code}")


def test_pairing_expired_code_410():
    L._pairing_codes.clear()
    code = "123-456"
    # Insert with an already-past expiry.
    L._pairing_codes[code] = (0.0, "old")
    claim = L.PairingClaimRequest(code=code, label="late")
    try:
        _run(L.claim_pairing_code(claim))
        check("expired code 410", False, "no exception raised")
    except L.HTTPException as e:
        # The code was popped before the expiry check, so it returns 410 once
        # it sees the timestamp is past.
        check("expired code 410", e.status_code == 410, f"got {e.status_code}")


def test_pairing_code_single_use():
    L._pairing_codes.clear()
    code_resp = _run(L.create_pairing_code(
        L.PairingCodeRequest(label_hint="single-use"),
        user_id=L.INTERNAL_USER_ID,
    ))
    code = code_resp["code"]

    # First claim succeeds.
    _run(L.claim_pairing_code(L.PairingClaimRequest(code=code, label="first")))

    # Second claim with the same code is rejected as not-found (it was popped).
    try:
        _run(L.claim_pairing_code(L.PairingClaimRequest(code=code, label="second")))
        check("second claim rejected", False)
    except L.HTTPException as e:
        check("second claim rejected", e.status_code == 404)


def test_shared_secret_auth_still_works():
    uid = L.get_authenticated_user(x_api_key=L.ACTIVE_SECRET)
    check("shared secret still grants auth (no regression)",
          uid == L.INTERNAL_USER_ID)

    try:
        L.get_authenticated_user(x_api_key="totally_wrong_key")
        check("garbage key rejected", False)
    except L.HTTPException as e:
        check("garbage key rejected", e.status_code == 401)


def test_revoke_invalid_prefix_400():
    try:
        _run(L.revoke_device(token_prefix="not_an_ltd_token",
                             user_id=L.INTERNAL_USER_ID))
        check("non-ltd prefix rejected", False)
    except L.HTTPException as e:
        check("non-ltd prefix rejected", e.status_code == 400)


def test_revoke_unknown_prefix_404():
    try:
        _run(L.revoke_device(
            token_prefix=L.DEVICE_TOKEN_PREFIX + "deadbeefcafe",
            user_id=L.INTERNAL_USER_ID,
        ))
        check("unknown prefix 404", False)
    except L.HTTPException as e:
        check("unknown prefix 404", e.status_code == 404)


# ── PWA surface ──────────────────────────────────────────────────────────────
def test_pwa_manifest_shape():
    m = L._PWA_MANIFEST
    check("manifest has standalone display", m["display"] == "standalone")
    check("manifest has start_url", m["start_url"] == "/")
    check("manifest has icons", len(m["icons"]) >= 2)
    check("manifest icons reference /static/", all(i["src"].startswith("/static/")
                                                    for i in m["icons"]))
    # Round-trip via JSON to confirm it's serializable.
    s = json.dumps(m)
    check("manifest is JSON-serializable", isinstance(s, str) and len(s) > 0)


def test_service_worker_contents():
    sw = L._SERVICE_WORKER_JS
    check("sw registers install + activate + fetch",
          "install" in sw and "activate" in sw and "fetch" in sw)
    check("sw never caches /api/ or /ws",
          "/api/" in sw and "/ws" in sw)
    check("sw caches the shell", "'/'," in sw or "'/'\n" in sw)


def test_icon_endpoints_return_svg():
    base = _run(L.pwa_icon_any())
    mask = _run(L.pwa_icon_maskable())
    check("base icon is SVG", b"<svg" in base.body)
    check("maskable icon is SVG", b"<svg" in mask.body)
    check("maskable icon has 80% scale group",
          b"scale(0.8)" in mask.body)


# ── Auth integration: pairing token works on WS-style path too ──────────────
def test_token_validity_lookup_bumps_last_seen():
    L._pairing_codes.clear()
    code_resp = _run(L.create_pairing_code(
        L.PairingCodeRequest(label_hint="last-seen-test"),
        user_id=L.INTERNAL_USER_ID,
    ))
    claim_resp = _run(L.claim_pairing_code(
        L.PairingClaimRequest(code=code_resp["code"], label="LastSeenTest")
    ))
    token = claim_resp["token"]

    # Before lookup: last_seen_at should be NULL
    with L.runtime.open_db() as conn:
        row = conn.execute(
            "SELECT last_seen_at FROM device_tokens WHERE token = ?", (token,)
        ).fetchone()
    check("freshly issued token has no last_seen", row[0] is None)

    # Validate the token (this triggers the bump)
    check("token validates", L._is_device_token_valid(token))

    with L.runtime.open_db() as conn:
        row = conn.execute(
            "SELECT last_seen_at FROM device_tokens WHERE token = ?", (token,)
        ).fetchone()
    check("last_seen_at bumped after validation", row[0] is not None)


def test_token_validity_rejects_garbage():
    check("empty string rejected", not L._is_device_token_valid(""))
    check("non-ltd prefix rejected", not L._is_device_token_valid("xyz_abc"))
    check("ltd-prefix but unknown rejected",
          not L._is_device_token_valid(L.DEVICE_TOKEN_PREFIX + "unknown"))


# ── Runner ───────────────────────────────────────────────────────────────────
TESTS = [
    test_pairing_code_format,
    test_device_token_format,
    test_pairing_flow_happy_path,
    test_pairing_unknown_code_404,
    test_pairing_expired_code_410,
    test_pairing_code_single_use,
    test_shared_secret_auth_still_works,
    test_revoke_invalid_prefix_400,
    test_revoke_unknown_prefix_404,
    test_pwa_manifest_shape,
    test_service_worker_contents,
    test_icon_endpoints_return_svg,
    test_token_validity_lookup_bumps_last_seen,
    test_token_validity_rejects_garbage,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 44 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
