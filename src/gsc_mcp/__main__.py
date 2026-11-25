"""CLI: `gsc-mcp-server` (stdio MCP server) or `gsc-mcp-server auth` (one-time OAuth consent)."""
from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        from .auth import AuthError, run_consent_flow

        try:
            path = run_consent_flow()
        except AuthError as e:
            sys.exit(str(e))
        print(f"Authorized (read-only). Token stored at {path}")
        return
    if len(sys.argv) > 1 and sys.argv[1] not in ("serve",):
        sys.exit("Usage: gsc-mcp-server [auth|serve]")
    from .server import mcp

    mcp.run()  # stdio


if __name__ == "__main__":
    main()
