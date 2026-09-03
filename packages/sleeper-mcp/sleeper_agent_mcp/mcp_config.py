"""Load overseer env from the global Cursor MCP config (~/.cursor/mcp.json)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PREFERRED_SERVER_KEYS = (
    "sleeper-agent-mcp",
    "sleeper-overseer-mcp",
)
SLEEPER_MODULE_MARKER = "sleeper_agent_mcp.server"
REQUIRED_ENV_KEYS: tuple[str, ...] = ()
SOLARI_BACKEND_ENV_KEYS = ("SOLARI_API_KEY",)

_last_reload: dict[str, Any] | None = None


@dataclass(frozen=True)
class McpEnvReloadResult:
    status: str
    config_path: str
    server_key: str | None = None
    applied_keys: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()
    cursor_api_key_set: bool = False
    solari_api_key_set: bool = False
    backend: str = "docker"
    error: str | None = None
    reloaded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "config_path": self.config_path,
            "server_key": self.server_key,
            "applied_keys": list(self.applied_keys),
            "missing_required": list(self.missing_required),
            "cursor_api_key_set": self.cursor_api_key_set,
            "solari_api_key_set": self.solari_api_key_set,
            "backend": self.backend,
            "error": self.error,
            "reloaded_at": self.reloaded_at,
        }


def global_mcp_config_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def reload_request_path() -> Path:
    return Path.home() / ".sleeper_agent" / "reload_mcp.request"


def reload_status_path() -> Path:
    return Path.home() / ".sleeper_agent" / "mcp_reload_status.json"


def _find_sleeper_server(
    servers: dict[str, Any],
    *,
    preferred_key: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    if preferred_key and preferred_key in servers:
        return preferred_key, servers[preferred_key]

    for key in PREFERRED_SERVER_KEYS:
        if key in servers:
            return key, servers[key]

    for key, config in servers.items():
        if not isinstance(config, dict):
            continue
        args = config.get("args") or []
        joined = " ".join(str(part) for part in args)
        if SLEEPER_MODULE_MARKER in joined:
            return key, config

    return None, None


def _missing_required_keys(env: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_ENV_KEYS:
        if not env.get(key, "").strip():
            missing.append(key)

    backend = env.get("SLEEPER_BACKEND", os.environ.get("SLEEPER_BACKEND", "docker"))
    if backend.strip().lower() == "solari":
        for key in SOLARI_BACKEND_ENV_KEYS:
            if not env.get(key, "").strip():
                missing.append(key)

    return missing


def reload_global_mcp_env(
    *,
    apply: bool = True,
    preferred_server_key: str | None = None,
) -> McpEnvReloadResult:
    """
    Read ~/.cursor/mcp.json and apply the sleeper-agent-mcp env block.

    Global config is the source of truth on startup and on restart_mcp.
    """
    global _last_reload

    config_path = global_mcp_config_path()
    if not config_path.is_file():
        result = McpEnvReloadResult(
            status="ERROR",
            config_path=str(config_path),
            error=f"Global MCP config not found: {config_path}",
            missing_required=tuple(REQUIRED_ENV_KEYS),
        )
        _last_reload = result.to_dict()
        return result

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = McpEnvReloadResult(
            status="ERROR",
            config_path=str(config_path),
            error=f"Failed to read {config_path}: {exc}",
            missing_required=tuple(REQUIRED_ENV_KEYS),
        )
        _last_reload = result.to_dict()
        return result

    servers = raw.get("mcpServers") or {}
    if not isinstance(servers, dict):
        result = McpEnvReloadResult(
            status="ERROR",
            config_path=str(config_path),
            error="mcpServers must be an object in global mcp.json",
            missing_required=tuple(REQUIRED_ENV_KEYS),
        )
        _last_reload = result.to_dict()
        return result

    server_key, server_config = _find_sleeper_server(
        servers, preferred_key=preferred_server_key
    )
    if server_config is None:
        result = McpEnvReloadResult(
            status="ERROR",
            config_path=str(config_path),
            error=(
                "No sleeper-agent-mcp server entry found in global mcp.json. "
                f"Expected one of {PREFERRED_SERVER_KEYS} or args containing "
                f"{SLEEPER_MODULE_MARKER!r}."
            ),
            missing_required=tuple(REQUIRED_ENV_KEYS),
        )
        _last_reload = result.to_dict()
        return result

    env_block = server_config.get("env") or {}
    if not isinstance(env_block, dict):
        result = McpEnvReloadResult(
            status="ERROR",
            config_path=str(config_path),
            server_key=server_key,
            error="env must be an object on the sleeper MCP server entry",
            missing_required=tuple(REQUIRED_ENV_KEYS),
        )
        _last_reload = result.to_dict()
        return result

    normalized_env = {str(key): str(value) for key, value in env_block.items()}
    if apply:
        for key, value in normalized_env.items():
            os.environ[key] = value

    missing = _missing_required_keys(normalized_env)
    backend = normalized_env.get(
        "SLEEPER_BACKEND", os.environ.get("SLEEPER_BACKEND", "docker")
    )
    result = McpEnvReloadResult(
        status="RELOADED" if not missing else "RELOADED_WITH_WARNINGS",
        config_path=str(config_path),
        server_key=server_key,
        applied_keys=tuple(sorted(normalized_env)),
        missing_required=tuple(missing),
        cursor_api_key_set=bool(normalized_env.get("CURSOR_API_KEY", "").strip()),
        solari_api_key_set=bool(normalized_env.get("SOLARI_API_KEY", "").strip()),
        backend=backend,
        error=(
            f"Missing required env keys in global mcp.json: {', '.join(missing)}"
            if missing
            else None
        ),
    )
    _last_reload = result.to_dict()
    return result


def get_last_mcp_env_reload() -> dict[str, Any] | None:
    return _last_reload


def apply_global_mcp_env_on_startup() -> McpEnvReloadResult:
    """Mandatory startup hook: always hydrate process env from ~/.cursor/mcp.json."""
    return reload_global_mcp_env(apply=True)


def request_mcp_env_reload(*, reason: str = "dashboard") -> Path:
    """Write a reload request consumed by the running MCP server."""
    path = reload_request_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_reload_status(result: McpEnvReloadResult) -> None:
    path = reload_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def consume_reload_request_if_present() -> McpEnvReloadResult | None:
    """Apply a pending reload request from the dashboard or CLI."""
    path = reload_request_path()
    if not path.is_file():
        return None
    try:
        path.unlink()
    except OSError:
        pass
    result = reload_global_mcp_env(apply=True)
    write_reload_status(result)
    return result
