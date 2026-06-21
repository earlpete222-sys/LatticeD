"""Sprint 45 — Installer/packaging tests.

The installers themselves are OS-side scripts (PowerShell + bash) and can't
sensibly run their full flow in a unit test (winget, brew, ollama pull are
all heavyweight). Instead we lock down what can break silently:

- requirements.txt parses cleanly, has no duplicates, every name we depend on
  in latticed.py source is represented
- Install-LatticeD.ps1 and install.sh exist, have the expected shape, and
  contain the self-heal secret-generation logic + model-pull commands
- Start-LatticeD.ps1 picked up the Sprint 45 secret self-heal
- README points at the new installer paths
- MOBILE.md still references the pairing flow
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

results: list[tuple[str, str, str]] = []


def check(n: str, c: bool, d: str = "") -> None:
    results.append((n, "PASS" if c else "FAIL", d))


# ── requirements.txt ────────────────────────────────────────────────────────
def test_requirements_parses_no_dupes():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = [
        ln.strip() for ln in reqs.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    # Extract just the project name (before any version specifier).
    names = [re.split(r"[<>=!~\[]", ln, 1)[0].strip().lower() for ln in lines]
    check("at least 8 dependencies", len(names) >= 8, f"got {len(names)}")
    check("no duplicate requirements",
          len(names) == len(set(names)),
          f"dupes: {[n for n in names if names.count(n) > 1]}")
    # Spot-check the load-bearing libs. Strip extras so "uvicorn[standard]"
    # matches "uvicorn" — extras are a packaging detail, not a dependency.
    base_names = {n.split("[", 1)[0] for n in names}
    must = {"fastapi", "uvicorn", "pydantic", "langgraph",
            "langchain-ollama", "chromadb", "sentence-transformers"}
    missing = must - base_names
    check("core dependencies present", not missing, f"missing {missing}")


# ── Windows installer ───────────────────────────────────────────────────────
def test_install_ps1_exists_and_shape():
    p = ROOT / "Install-LatticeD.ps1"
    check("Install-LatticeD.ps1 exists", p.exists())
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    check("pins Python 3.12 minimum",
          "PYTHON_MIN_MINOR = 12" in src or "3.12" in src)
    check("uses winget for Python",
          "winget install" in src and "Python.Python.3.12" in src)
    check("installs Ollama via winget",
          "Ollama.Ollama" in src)
    check("pulls both required models",
          "deepseek-r1:1.5b" in src and "qwen2.5-coder:1.5b" in src)
    check("generates a base64 secret",
          "RandomNumberGenerator" in src and "ToBase64String" in src)
    check("writes desktop shortcut",
          "CreateShortcut" in src and "LatticeD.lnk" in src)
    check("idempotent skip flags declared",
          "[switch]$SkipModels" in src and "[switch]$Force" in src)


# ── Bash installer ──────────────────────────────────────────────────────────
def test_install_sh_exists_and_shape():
    p = ROOT / "install.sh"
    check("install.sh exists", p.exists())
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    check("bash shebang", src.startswith("#!/usr/bin/env bash"))
    check("strict mode", "set -euo pipefail" in src)
    check("detects mac vs linux", "Darwin" in src and "Linux" in src)
    check("brew fallback on mac", "brew install" in src)
    check("apt fallback on linux", "apt-get" in src)
    check("ollama install via curl script",
          "https://ollama.com/install.sh" in src)
    check("pulls both models", "deepseek-r1:1.5b" in src and "qwen2.5-coder:1.5b" in src)
    check("base64 secret via python -c",
          "base64.b64encode" in src and "os.urandom(32)" in src)
    check("writes .env mode 600", "chmod 600" in src and ".env" in src)
    check("writes start.sh launcher",
          "start.sh" in src and "chmod +x" in src)
    check("LAN flag wired",
          "--lan" in src and "LATTICED_HOST=0.0.0.0" in src)


# ── Start-LatticeD.ps1 self-heal ───────────────────────────────────────────
def test_start_script_self_heals_secret():
    p = ROOT / "Start-LatticeD.ps1"
    check("Start-LatticeD.ps1 exists", p.exists())
    if not p.exists():
        return
    src = p.read_text(encoding="utf-8")
    check("self-heals default secret",
          "local_dev_secret_123" in src and "RandomNumberGenerator" in src,
          "Sprint 45 self-heal block missing")
    check("persists to User scope",
          "SetEnvironmentVariable(\"LATTICED_SECRET\"" in src and "\"User\"" in src)


# ── README / MOBILE.md cross-references ────────────────────────────────────
def test_readme_advertises_installer():
    r = (ROOT / "README.md").read_text(encoding="utf-8")
    check("README references Install-LatticeD.ps1", "Install-LatticeD.ps1" in r)
    check("README references install.sh", "install.sh" in r)
    check("README references start.sh", "start.sh" in r)
    check("README links to MOBILE.md", "MOBILE.md" in r)
    check("README has One-click install heading",
          "One-click install" in r)


def test_mobile_md_still_intact():
    m = (ROOT / "MOBILE.md").read_text(encoding="utf-8")
    check("MOBILE.md mentions Tailscale", "Tailscale" in m)
    check("MOBILE.md mentions LATTICED_HOST=0.0.0.0",
          "LATTICED_HOST" in m and "0.0.0.0" in m)
    check("MOBILE.md mentions pairing", "pair" in m.lower() and "code" in m.lower())


# ── Secret strength contract ───────────────────────────────────────────────
def test_secret_generator_strength_contract():
    """The shape of the generated secret is locked: 32 bytes of urandom,
    base64-encoded with padding stripped — produces a 43-character token.
    Both installers must use this contract so the LATTICED_SECRET strength
    doesn't silently degrade in a future edit."""
    import base64
    import os
    sample = base64.b64encode(os.urandom(32)).decode().rstrip("=")
    check("contract produces 43-char token",
          len(sample) == 43, f"got {len(sample)}")
    # Confirm both installers emit this contract literally.
    ps_src = (ROOT / "Install-LatticeD.ps1").read_text(encoding="utf-8")
    sh_src = (ROOT / "install.sh").read_text(encoding="utf-8")
    check("PS1 uses 32-byte random",
          "New-Object byte[] 32" in ps_src or "byte[] 32" in ps_src)
    check("SH uses os.urandom(32)",
          "os.urandom(32)" in sh_src)


# ── Runner ─────────────────────────────────────────────────────────────────
TESTS = [
    test_requirements_parses_no_dupes,
    test_install_ps1_exists_and_shape,
    test_install_sh_exists_and_shape,
    test_start_script_self_heals_secret,
    test_readme_advertises_installer,
    test_mobile_md_still_intact,
    test_secret_generator_strength_contract,
]


def main() -> int:
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            results.append((fn.__name__, "FAIL", f"raised {type(exc).__name__}: {exc}"))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"\n{passed}/{passed + failed} Sprint 45 tests passed.")
    for name, status, detail in results:
        mark = "PASS" if status == "PASS" else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
