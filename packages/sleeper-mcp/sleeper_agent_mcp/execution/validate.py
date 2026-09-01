"""Command validation and failure path inference."""

from __future__ import annotations

import re
from pathlib import Path

from sleeper_agent_mcp.execution.types import WhitelistError
from sleeper_agent_mcp.state import resolve_path

ALLOWED_BINARIES = frozenset({"python", "python3", "pytest", "npm", "node"})


def validate_command(command: str) -> str:
    """Validate and normalize a command against the binary whitelist."""
    binary = Path(command).name
    if binary not in ALLOWED_BINARIES:
        raise WhitelistError(
            f"Binary '{binary}' is not allowed. "
            f"Allowed binaries: {', '.join(sorted(ALLOWED_BINARIES))}"
        )
    return binary


def validate_tasks(tasks: list[dict]) -> list[dict]:
    """Validate every task command in a sequence."""
    validated: list[dict] = []
    for task in tasks:
        command = validate_command(str(task["command"]))
        runtime = str(task.get("runtime", "sandbox")).strip().lower()
        if runtime not in {"sandbox", "browser"}:
            raise ValueError(
                f"Task '{task.get('id')}' has invalid runtime '{runtime}'. "
                "Use 'sandbox' or 'browser'."
            )
        url = task.get("url")
        if runtime == "browser" and not url:
            raise ValueError(
                f"Task '{task.get('id')}' uses runtime 'browser' but has no url."
            )
        validated.append(
            {
                "id": str(task["id"]),
                "command": command,
                "args": [str(a) for a in task.get("args", [])],
                "runtime": runtime,
                "url": str(url) if url else None,
            }
        )
    return validated


def infer_failing_file_path(
    workspace: str | Path, args: list[str], stderr: str
) -> str | None:
    """Best-effort extraction of the file path that caused a task failure."""
    workspace_path = resolve_path(workspace)

    for arg in args:
        candidate = Path(arg)
        if candidate.suffix in {".py", ".js", ".ts", ".jsx", ".tsx", ".json"}:
            resolved = (
                resolve_path(candidate)
                if candidate.is_absolute()
                else resolve_path(workspace_path / candidate)
            )
            if resolved.exists():
                return str(resolved)

    match = re.search(r'File "([^"]+)"', stderr)
    if match:
        return str(resolve_path(match.group(1)))

    match = re.search(r"([A-Za-z]:\\[^\s:]+\.py|/[^\s:]+\.py)", stderr)
    if match:
        return str(resolve_path(match.group(1)))

    return None
