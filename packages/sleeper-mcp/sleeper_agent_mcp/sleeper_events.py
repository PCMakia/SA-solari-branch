"""File-based event queue for MCP ↔ Sleeper daemon IPC."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sleeper_agent_mcp.workspace_scope import resolve_target_workspace

SLEEPER_DIR_NAME = ".sleeper"
EVENTS_FILE_NAME = "events.jsonl"
CURSOR_RESPONSE_FILE = "cursor_last_response.txt"
DAEMON_COMMANDS_FILE = "daemon_commands.jsonl"

EVENT_QUEUE_STARTED = "QUEUE_STARTED"
EVENT_STEP_PASSED = "STEP_PASSED"
EVENT_STEP_FAILED = "STEP_FAILED"
EVENT_NEEDS_REPAIR = "NEEDS_REPAIR"
EVENT_AWAITING_DAEMON = "AWAITING_DAEMON"
EVENT_QUEUE_COMPLETED = "QUEUE_COMPLETED"
EVENT_QUEUE_ABORTED = "QUEUE_ABORTED"
EVENT_QUEUE_STOPPED = "QUEUE_STOPPED"


def sleeper_dir(workspace: str | Path) -> Path:
    root = resolve_target_workspace(workspace)
    path = root / SLEEPER_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_path(workspace: str | Path) -> Path:
    return sleeper_dir(workspace) / EVENTS_FILE_NAME


def cursor_response_path(workspace: str | Path) -> Path:
    return sleeper_dir(workspace) / CURSOR_RESPONSE_FILE


def append_event(
    workspace: str | Path,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one JSON line to `.sleeper/events.jsonl`."""
    record = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }
    path = events_path(workspace)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_events(workspace: str | Path) -> list[dict[str, Any]]:
    path = events_path(workspace)
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def read_events_after(
    workspace: str | Path,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return events from `offset` onward and the new offset."""
    all_events = read_events(workspace)
    if offset < 0:
        offset = 0
    chunk = all_events[offset:]
    return chunk, offset + len(chunk)


def clear_events(workspace: str | Path) -> None:
    path = events_path(workspace)
    if path.is_file():
        path.unlink()
