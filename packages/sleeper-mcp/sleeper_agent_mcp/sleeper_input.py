"""Parse Sleeper-call payloads and format Cursor chat prompts."""

from __future__ import annotations

import json
import re
from typing import Any

SLEEPER_CALL_RE = re.compile(
    r'"""?\s*Sleeper-call\s*(?P<body>[\s\S]*?)\s*"""?',
    re.IGNORECASE,
)
TASK_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```",
    re.IGNORECASE,
)


def extract_sleeper_call_body(text: str) -> str:
    match = SLEEPER_CALL_RE.search(text)
    if match:
        return match.group("body").strip()
    return text.strip()


def _normalize_task_dict(raw: dict[str, Any]) -> dict[str, Any]:
    task_id = raw.get("id") or raw.get("task_id") or raw.get("name")
    command = raw.get("command")
    if not task_id or not command:
        raise ValueError(f"Task missing id or command: {raw}")
    return {
        "id": str(task_id),
        "command": str(command),
        "args": [str(a) for a in raw.get("args", [])],
        "runtime": str(raw.get("runtime", "sandbox")),
        **({"url": str(raw["url"])} if raw.get("url") else {}),
    }


def parse_tasks_from_payload(payload: str) -> list[dict[str, Any]] | None:
    """
    Try to extract structured MCP tasks from Sleeper-call body.

    Accepts embedded JSON array/object, fenced ```json blocks, or a bare JSON body.
    """
    candidates: list[str] = []
    for match in TASK_JSON_BLOCK_RE.finditer(payload):
        candidates.append(match.group(1).strip())
    stripped = payload.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        candidates.append(stripped)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "tasks" in parsed:
            parsed = parsed["tasks"]
        if not isinstance(parsed, list):
            continue
        tasks = [_normalize_task_dict(item) for item in parsed if isinstance(item, dict)]
        if tasks:
            return tasks
    return None


def tasks_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    def norm(task: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": task["id"],
            "command": task["command"],
            "args": list(task.get("args", [])),
            "runtime": task.get("runtime", "sandbox"),
            "url": task.get("url"),
        }

    return [norm(t) for t in left] == [norm(t) for t in right]


def format_kickoff_prompt(
    *,
    workspace: str,
    payload: str,
    tasks: list[dict[str, Any]] | None = None,
    label: str = "sleeper-session",
    dashboard_url: str | None = None,
) -> str:
    if tasks:
        task_block = json.dumps(
            {
                "tasks": tasks,
                "workspace": workspace,
                "label": label,
                "max_retries": 3,
            },
            indent=2,
        )
    else:
        task_block = payload
    dash = (dashboard_url or "http://localhost:3000/").strip()
    return (
        "Sleeper overseer kickoff.\n\n"
        "Sleeper is installed globally. This run's workspace is the project you have "
        f"open — use exactly: `{workspace}` (do not substitute the Solari/Sleeper "
        "install path).\n\n"
        "1. If the classic IDE for this workspace is not already open with the Agent "
        "panel, open it (Agents → Open IDE for this folder). Do NOT run "
        "`cursor --classic` if the IDE+Agent panel is already open.\n"
        "2. Call the MCP tool `start_afk_overseer` with this exact payload "
        "(it auto-starts `sleeper_daemon watch` for this workspace when needed), "
        "then end your turn (do not wait for task completion):\n\n"
        f"```json\n{task_block}\n```\n\n"
        "3. Also open the Overseer dashboard in the Cursor IDE browser (not Chrome): "
        f"use `open_resource` (or Simple Browser) with `{dash}`.\n\n"
        "If sleeper watch did not start, run this in an IDE terminal (background):\n"
        f"`python -m sleeper_daemon.cli watch --workspace {workspace} "
        "--window-title Cursor`\n\n"
        "After starting the overseer, also write your full response to "
        f"`{workspace}/.sleeper/cursor_last_response.txt` for the Sleeper daemon."
    )


def format_repair_prompt(
    *,
    workspace: str,
    error_message: str,
    task_id: str,
    queue_id: str,
) -> str:
    return (
        f"Process encountered error on step `{task_id}` (queue `{queue_id}`).\n\n"
        "Fix the error in the workspace, then either:\n"
        "1. If the retry steps are unchanged, say `resume unchanged` and call "
        "`resume_queue` with the same queue_id.\n"
        "2. If steps changed, output the updated task list as JSON and call "
        "`start_afk_overseer` or update tasks as appropriate.\n\n"
        f"Error output:\n```\n{error_message}\n```\n\n"
        "Write your full response to "
        f"`{workspace}/.sleeper/cursor_last_response.txt` when done."
    )
