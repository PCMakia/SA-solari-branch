"""Kill-switch, failure artifacts, and cache hygiene for the AFK overseer."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sleeper_agent_mcp.workspace_scope import resolve_target_workspace

STOP_FILE_NAME = ".overseer.stop"
FAILURE_FILE_NAME = ".overseer_failure.md"
FAILURE_JSON_LEGACY = ".overseer_failure.json"

DEFAULT_REPAIR_TIMEOUT_SECONDS = int(os.environ.get("SLEEPER_REPAIR_TIMEOUT", "900"))
DEFAULT_ORCHESTRATOR_TIMEOUT_SECONDS = int(
    os.environ.get("SLEEPER_ORCHESTRATOR_TIMEOUT", "7200")
)

TRANSIENT_CACHE_DIRS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".hypothesis",
        ".tox",
        ".nox",
    }
)


def resolve_repair_timeout(override: int | None = None) -> int:
    if override is not None:
        return max(1, int(override))
    return max(1, DEFAULT_REPAIR_TIMEOUT_SECONDS)


def resolve_orchestrator_timeout(override: int | None = None) -> int:
    if override is not None:
        return max(1, int(override))
    return max(1, DEFAULT_ORCHESTRATOR_TIMEOUT_SECONDS)


def stop_file_path(workspace: str | Path) -> Path:
    return resolve_target_workspace(workspace) / STOP_FILE_NAME


def failure_file_path(workspace: str | Path) -> Path:
    return resolve_target_workspace(workspace) / FAILURE_FILE_NAME


def is_stop_requested(workspace: str | Path) -> bool:
    return stop_file_path(workspace).is_file()


def request_stop(workspace: str | Path, *, reason: str = "") -> Path:
    """Create the physical kill-switch file in the target workspace root."""
    path = stop_file_path(workspace)
    payload = {
        "reason": reason or "user_request",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def clear_stop_request(workspace: str | Path) -> bool:
    """Remove the kill-switch file if present. Returns True when removed."""
    path = stop_file_path(workspace)
    if path.is_file():
        path.unlink()
        return True
    return False


def clear_transient_caches(workspace: str | Path) -> list[str]:
    """Remove transient build/test caches under workspace before a retry."""
    root = resolve_target_workspace(workspace)
    if not root.is_dir():
        return []

    removed: list[str] = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        if path.name not in TRANSIENT_CACHE_DIRS:
            continue
        try:
            rel = str(path.relative_to(root))
            shutil.rmtree(path, ignore_errors=True)
            removed.append(rel)
        except OSError:
            continue
    return removed


def write_failure_artifact(
    workspace: str | Path,
    *,
    queue_id: str,
    label: str | None,
    failed_task_id: str,
    retry_count: int,
    max_retries: int,
    last_error: dict[str, Any] | None,
    repair_history: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> Path:
    """Persist terminal failure state to `.overseer_failure.md`."""
    path = failure_file_path(workspace)
    timestamp = datetime.now(timezone.utc).isoformat()
    last_error = last_error or {}
    command = last_error.get("execution_command") or last_error.get("command")
    if not command and tasks:
        for task in tasks:
            if task.get("id") == failed_task_id:
                args = task.get("args") or []
                command = " ".join([str(task.get("command", "")), *[str(a) for a in args]]).strip()
                break

    lines = [
        "# Overseer Failure Report",
        "",
        f"- **Status:** ABORTED",
        f"- **Timestamp:** {timestamp}",
        f"- **Queue ID:** `{queue_id}`",
        f"- **Label:** {label or '(none)'}",
        f"- **Failed step:** `{failed_task_id}`",
        f"- **Command:** `{command or '(unknown)'}`",
        f"- **Repair attempts:** {retry_count} / {max_retries}",
        "",
        "## Error traceback",
        "",
        "```",
        str(last_error.get("traceback") or last_error.get("stderr") or "(no traceback)"),
        "```",
        "",
        "## Repair history",
        "",
    ]
    history = repair_history or []
    if not history:
        lines.append("_No Cursor repair attempts recorded._")
    else:
        for index, entry in enumerate(history, start=1):
            lines.extend(
                [
                    f"### Attempt {index}",
                    "",
                    f"- **Task:** `{entry.get('task_id', failed_task_id)}`",
                    f"- **Timestamp:** {entry.get('timestamp', '(unknown)')}",
                    f"- **Cursor response excerpt:**",
                    "",
                    "```",
                    str(entry.get("cursor_response") or entry.get("message") or "(empty)"),
                    "```",
                    "",
                ]
            )

    lines.extend(
        [
            "## Workspace state",
            "",
            f"- **Workspace:** `{resolve_target_workspace(workspace)}`",
            f"- **Stop file present:** `{is_stop_requested(workspace)}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_stop_artifact(
    workspace: str | Path,
    *,
    queue_id: str,
    label: str | None,
    step_index: int,
) -> Path:
    path = failure_file_path(workspace)
    payload = {
        "status": "STOPPED_BY_USER",
        "queue_id": queue_id,
        "label": label,
        "active_step_index": step_index,
        "stop_file": STOP_FILE_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
