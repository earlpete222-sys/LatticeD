#!/usr/bin/env python3
"""
latticed_mcp_server.py -- runnable MCP stdio entry point.

Boots a LatticeContext (Sprint 14), registers a single consumer with a
configurable grant, and serves JSON-RPC 2.0 lines over stdin/stdout
(Sprint 15).  Drop this into a Claude Desktop MCP config:

  {
    "mcpServers": {
      "latticed": {
        "command": "python",
        "args": ["/abs/path/to/scripts/latticed_mcp_server.py"],
        "env": {
          "LATTICED_USER_ID": "earl",
          "LATTICED_CONSUMER_ID": "claude-desktop",
          "LATTICED_CONSUMER_CEILING": "low",
          "LATTICED_CONSUMER_DOMAINS": "career,financial,growth",
          "LATTICED_TIER": "minimal_gpu"
        }
      }
    }
  }

Environment variables (all optional):
  LATTICED_USER_ID            identity user_id; default 'local'
  LATTICED_TIER               hardware tier override; default auto-detect
  LATTICED_CONSUMER_ID        external consumer id;    default 'mcp-client'
  LATTICED_CONSUMER_NAME      display name;            default 'MCP Client'
  LATTICED_CONSUMER_CEILING   sensitivity ceiling;     default 'low'
  LATTICED_CONSUMER_DOMAINS   comma-separated allowed life domains;
                              empty = all (default)
  LATTICED_LOG_BOOT           if '1', emits one stderr line at boot

Exit codes:
  0  clean shutdown (EOF on stdin, or explicit shutdown method)
  1  fatal exception (printed to stderr)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "latticed"))

import latticed as L  # noqa: E402


def build_grant(consumer_id: str) -> L.ConsumerGrant:
    ceiling = (os.environ.get("LATTICED_CONSUMER_CEILING") or "low").strip().lower()
    if ceiling not in {s.value for s in L.Sensitivity}:
        ceiling = L.Sensitivity.LOW.value

    domains_env = (os.environ.get("LATTICED_CONSUMER_DOMAINS") or "").strip()
    if domains_env:
        valid = {d.value for d in L.LifeDomain}
        allowed = [d.strip() for d in domains_env.split(",") if d.strip()]
        allowed = [d for d in allowed if d in valid]
    else:
        allowed = []   # empty -> all domains allowed (per ConsumerGrant semantics)

    return L.ConsumerGrant(
        consumer_id=consumer_id,
        allowed_domains=allowed,
        sensitivity_ceiling=ceiling,
        allowed_destinations=["mcp"],   # required for the in-process server to dispatch
    )


def main() -> int:
    try:
        user_id     = (os.environ.get("LATTICED_USER_ID") or "local").strip() or "local"
        tier        = (os.environ.get("LATTICED_TIER") or "").strip() or None
        consumer_id = (os.environ.get("LATTICED_CONSUMER_ID") or "mcp-client").strip()
        cname       = (os.environ.get("LATTICED_CONSUMER_NAME") or "MCP Client").strip()

        ctx = L.LatticeContext.boot(user_id=user_id, tier_override=tier)
        ctx.mcp.register_consumer(L.Consumer(consumer_id, cname), build_grant(consumer_id))

        if os.environ.get("LATTICED_LOG_BOOT") == "1":
            sys.stderr.write(
                f"[latticed-mcp] booted user={user_id} tier={ctx.profile.tier} "
                f"agents={len(ctx.factory.registry)} valid={ctx.validation.valid} "
                f"consumer={consumer_id}\n"
            )
            sys.stderr.flush()

        bridge = L.MCPStdioBridge(ctx.mcp, consumer_id)
        try:
            bridge.serve(sys.stdin, sys.stdout)
        finally:
            # Best-effort persistence on exit.
            try:
                ctx.save_all()
            except Exception as e:
                sys.stderr.write(f"[latticed-mcp] save_all failed: {e}\n")
        return 0
    except Exception as e:
        sys.stderr.write(f"[latticed-mcp] fatal: {type(e).__name__}: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
