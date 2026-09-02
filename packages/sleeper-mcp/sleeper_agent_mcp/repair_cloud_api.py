"""Cloud repair via Cursor Cloud Agents REST API (no local SDK bridge)."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

CURSOR_API_BASE = "https://api.cursor.com"
TERMINAL_RUN_STATUSES = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})
POLL_INTERVAL_SECONDS = 5.0


@dataclass(frozen=True)
class CloudApiRunResult:
    agent_id: str
    run_id: str
    status: str
    result: str | None
    git: dict[str, Any] | None


class CloudApiError(RuntimeError):
    pass


def _basic_auth_header(api_key: str) -> str:
    token = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request_json(
    *,
    method: str,
    path: str,
    api_key: str,
    body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    url = f"{CURSOR_API_BASE}{path}"
    data = None
    headers = {
        "Authorization": _basic_auth_header(api_key),
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise CloudApiError(f"HTTP {err.code} {method} {path}: {detail}") from err
    except urllib.error.URLError as err:
        raise CloudApiError(f"Network error {method} {path}: {err}") from err

    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise CloudApiError(f"Invalid JSON from {method} {path}: {err}") from err
    if not isinstance(parsed, dict):
        raise CloudApiError(f"Unexpected JSON type from {method} {path}")
    return parsed


def _build_create_payload(
    *,
    prompt: str,
    repo_url: str,
    starting_ref: str | None,
    model: str,
) -> dict[str, Any]:
    repo_entry: dict[str, Any] = {"url": repo_url}
    if starting_ref:
        repo_entry["startingRef"] = starting_ref

    payload: dict[str, Any] = {
        "prompt": {"text": prompt},
        "repos": [repo_entry],
        "workOnCurrentBranch": True,
        "autoCreatePR": False,
        "skipReviewerRequest": True,
        "mode": "agent",
    }
    if model and model.lower() != "auto":
        payload["model"] = {"id": model}
    return payload


def _poll_run(
    *,
    agent_id: str,
    run_id: str,
    api_key: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        run = _request_json(
            method="GET",
            path=f"/v1/agents/{agent_id}/runs/{run_id}",
            api_key=api_key,
        )
        status = str(run.get("status", "")).upper()
        if status in TERMINAL_RUN_STATUSES:
            return run
        time.sleep(POLL_INTERVAL_SECONDS)

    raise CloudApiError(
        f"Cloud repair run {run_id} did not finish within {timeout_seconds}s"
    )


def run_cloud_repair_via_api(
    *,
    prompt: str,
    repo_url: str,
    starting_ref: str | None,
    api_key: str,
    model: str,
    timeout_seconds: int,
) -> CloudApiRunResult:
    """Create a cloud agent, wait for the initial run, and return terminal state."""
    created = _request_json(
        method="POST",
        path="/v1/agents",
        api_key=api_key,
        body=_build_create_payload(
            prompt=prompt,
            repo_url=repo_url,
            starting_ref=starting_ref,
            model=model,
        ),
        timeout=120.0,
    )
    agent = created.get("agent") or {}
    run = created.get("run") or {}
    agent_id = str(agent.get("id") or "")
    run_id = str(run.get("id") or agent.get("latestRunId") or "")
    if not agent_id or not run_id:
        raise CloudApiError(f"Cloud API create response missing agent/run ids: {created}")

    terminal = _poll_run(
        agent_id=agent_id,
        run_id=run_id,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    git = terminal.get("git")
    return CloudApiRunResult(
        agent_id=agent_id,
        run_id=run_id,
        status=str(terminal.get("status", "unknown")).upper(),
        result=terminal.get("result"),
        git=git if isinstance(git, dict) else None,
    )


def git_info_from_api(git_payload: dict[str, Any] | None) -> Any:
    """Adapt REST git payload to the shape expected by sync_cloud_repair_to_workspace."""
    if not git_payload:
        return None
    branches = []
    for item in git_payload.get("branches") or []:
        if not isinstance(item, dict):
            continue
        branches.append(
            type(
                "BranchInfo",
                (),
                {
                    "repo_url": item.get("repoUrl") or item.get("repo_url"),
                    "branch": item.get("branch"),
                    "pr_url": item.get("prUrl") or item.get("pr_url"),
                },
            )()
        )
    return type("RunGitInfo", (), {"branches": branches})()
