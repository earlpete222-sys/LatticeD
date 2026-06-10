#!/usr/bin/env python3
"""
latticed_status.py -- print a LatticeD self-introspection report.

Usage:
    python scripts/latticed_status.py [--json] [--section SECTION ...]

Sections (use with --section, repeatable):
    boot perf audit_24h identity engagement voice tension business encryption

Environment:
    LATTICED_USER_ID, LATTICED_TIER, LATTICED_PASSPHRASE  -- same semantics
    as scripts/latticed_mcp_server.py.

Exit codes: 0 on success, non-zero on failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "latticed"))

import latticed as L  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LatticeD status report.")
    ap.add_argument("--json", action="store_true",
                    help="emit the full snapshot as JSON instead of text")
    ap.add_argument("--section", action="append", default=[],
                    help="restrict to one section (repeatable)")
    args = ap.parse_args(argv)

    try:
        ctx = L.LatticeContext.boot(
            user_id=os.environ.get("LATTICED_USER_ID", "local"),
            tier_override=os.environ.get("LATTICED_TIER") or None,
        )
    except Exception as e:
        print(f"latticed_status: boot failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    diag = ctx.diagnostics

    if args.section:
        avail = {
            "boot":       ctx.boot_report,
            "perf":       diag.perf_summary,
            "audit_24h":  diag.audit_summary,
            "identity":   diag.identity_summary,
            "engagement": diag.engagement_summary,
            "voice":      diag.voice_summary,
            "tension":    diag.tension_summary,
            "business":   diag.business_summary,
            "encryption": diag.encryption_status,
        }
        snap = {}
        for s in args.section:
            if s in avail:
                snap[s] = avail[s]()
            else:
                print(f"unknown section: {s}", file=sys.stderr)
                return 2
        print(json.dumps(snap, indent=2, default=str))
        return 0

    if args.json:
        print(json.dumps(diag.snapshot(), indent=2, default=str))
        return 0

    print(diag.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
