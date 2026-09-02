#!/usr/bin/env python3
"""Reload sleeper MCP env from global ~/.cursor/mcp.json (CLI helper)."""

from __future__ import annotations

import json
import sys

from sleeper_agent_mcp.mcp_config import reload_global_mcp_env


def main() -> int:
    result = reload_global_mcp_env(apply=True)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.status != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
