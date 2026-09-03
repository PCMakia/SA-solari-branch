#!/usr/bin/env python3
"""Merge sleeper-agent-mcp into ~/.cursor/mcp.json (used by install_cursor_sleeper.ps1)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcp-path", required=True)
    parser.add_argument("--sleeper-home", required=True)
    parser.add_argument("--api-key", default="slr_live_YOUR_KEY_HERE")
    args = parser.parse_args()

    home = Path(args.sleeper_home).resolve()
    mcp_pkg = home / "packages" / "sleeper-mcp"
    daemon_pkg = home / "packages" / "sleeper-daemon"
    mcp_path = Path(args.mcp_path).expanduser()

    home_s = home.as_posix()
    mcp_s = mcp_pkg.as_posix()
    daemon_s = daemon_pkg.as_posix()
    pp = f"{mcp_s};{daemon_s}"

    entry = {
        "command": "python",
        "args": ["-m", "sleeper_agent_mcp.server"],
        "cwd": mcp_s,
        "env": {
            "SLEEPER_HOME": home_s,
            "PYTHONPATH": pp,
            "SLEEPER_BACKEND": "solari",
            "SOLARI_API_KEY": args.api_key,
            "SLEEPER_ORCHESTRATOR_TIMEOUT": "7200",
            "SLEEPER_TASK_TIMEOUT": "600",
            "SLEEPER_MAX_CONCURRENT": "2",
            "SLEEPER_MEMORY_THRESHOLD": "0.20",
            "SLEEPER_TASK_RAM": "4g",
            "SLEEPER_DOCKER_IMAGE": "python:3.11-slim",
            "SLEEPER_CURSOR_WINDOW_TITLE": "Cursor",
        },
    }

    config: dict = {"mcpServers": {}}
    if mcp_path.is_file():
        try:
            config = json.loads(mcp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = {"mcpServers": {}}
    if not isinstance(config.get("mcpServers"), dict):
        config["mcpServers"] = {}

    existing = config["mcpServers"].get("sleeper-agent-mcp") or {}
    existing_env = existing.get("env") if isinstance(existing, dict) else {}
    if isinstance(existing_env, dict):
        old_key = str(existing_env.get("SOLARI_API_KEY") or "").strip()
        if args.api_key.endswith("YOUR_KEY_HERE") and old_key and not old_key.endswith(
            "YOUR_KEY_HERE"
        ):
            entry["env"]["SOLARI_API_KEY"] = old_key

    # Never pin task workspace to the install.
    entry["env"].pop("SLEEPER_WORKSPACE", None)
    config["mcpServers"]["sleeper-agent-mcp"] = entry

    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {mcp_path}")
    print(f"SLEEPER_HOME={entry['env']['SLEEPER_HOME']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
