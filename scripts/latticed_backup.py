#!/usr/bin/env python3
"""
latticed_backup.py -- export/import the LatticeD identity bundle.

Usage:
    python scripts/latticed_backup.py export <out_path> [--ceiling low|medium|high]
                                              [--no-business] [--no-snapshots]
    python scripts/latticed_backup.py import <in_path> [--conflict merge|overwrite|skip]

Examples:
    # Share-safe (LOW only) export
    python scripts/latticed_backup.py export ~/latticed-low.json --ceiling low

    # Full local backup (HIGH and below; SECRET is always excluded)
    python scripts/latticed_backup.py export ~/latticed-full.json --ceiling high

    # Restore from a bundle, merging with existing identity
    python scripts/latticed_backup.py import ~/latticed-full.json --conflict merge

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


def cmd_export(args: argparse.Namespace) -> int:
    ctx = L.LatticeContext.boot(
        user_id=os.environ.get("LATTICED_USER_ID", "local"),
        tier_override=os.environ.get("LATTICED_TIER") or None,
    )
    bundle = L.build_identity_export(
        ctx,
        ceiling=args.ceiling,
        include_business=not args.no_business,
        include_snapshots=not args.no_snapshots,
    )
    out = Path(args.out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(bundle.to_json(), encoding="utf-8")
    print(f"export wrote {out}")
    print(f"  facts        : {len(bundle.facts)}")
    print(f"  north_stars  : {len(bundle.north_stars)}")
    print(f"  rules        : {len(bundle.rules)}")
    print(f"  businesses   : {len(bundle.businesses)}")
    print(f"  snapshots    : {len(bundle.snapshots)}")
    print(f"  ceiling      : {bundle.sensitivity_ceiling}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    src = Path(args.in_path).expanduser().resolve()
    if not src.exists():
        print(f"import: file not found: {src}", file=sys.stderr)
        return 2
    try:
        bundle = L.IdentityExport.from_json(src.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"import: failed to parse bundle: {e}", file=sys.stderr)
        return 3

    ctx = L.LatticeContext.boot(
        user_id=os.environ.get("LATTICED_USER_ID", "local"),
        tier_override=os.environ.get("LATTICED_TIER") or None,
    )
    rep = L.apply_identity_import(ctx, bundle, conflict=args.conflict)
    ctx.save_all()
    print(f"import applied: {rep.summary()}")
    for w in rep.warnings:
        print(f"  WARN: {w}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LatticeD identity backup tool.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="Export identity bundle to a JSON file.")
    ex.add_argument("out_path")
    ex.add_argument("--ceiling", choices=["low", "medium", "high"], default="low")
    ex.add_argument("--no-business", action="store_true")
    ex.add_argument("--no-snapshots", action="store_true")
    ex.set_defaults(func=cmd_export)

    im = sub.add_parser("import", help="Apply an identity bundle from a JSON file.")
    im.add_argument("in_path")
    im.add_argument("--conflict", choices=["merge", "overwrite", "skip"], default="merge")
    im.set_defaults(func=cmd_import)

    args = ap.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as e:
        print(f"fatal: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
