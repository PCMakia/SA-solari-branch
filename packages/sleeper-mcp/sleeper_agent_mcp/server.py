"""MCP SDK v2 server registration and tool entrypoints for sleeper-agent-mcp."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

from mcp.server.mcpserver import MCPServer

from sleeper_agent_mcp.backends import get_execution_backend
from sleeper_agent_mcp.local_control import (
    active_background_queue_ids,
    orchestrator_thread_alive,
    start_afk_background,
)
from sleeper_agent_mcp.orchestrator import run_afk_orchestrator
from sleeper_agent_mcp.overseer_controls import (
    clear_stop_request,
    failure_file_path,
    is_stop_requested,
    request_stop,
    resolve_orchestrator_timeout,
    stop_file_path,
)
from sleeper_agent_mcp.runner import (
    can_spawn_concurrent_worker,
    get_resource_plan,
    get_system_resource_snapshot,
    run_task,
    validate_tasks,
)
from sleeper_agent_mcp.state import (
    DEFAULT_MAX_RETRIES,
    HistoryEntry,
    QueueStatus,
    StateManager,
    StreamMode,
    TaskSpec,
    resolve_path,
)
from sleeper_agent_mcp.mcp_config import (
    apply_global_mcp_env_on_startup,
    consume_reload_request_if_present,
    get_last_mcp_env_reload,
    global_mcp_config_path,
    reload_global_mcp_env,
    write_reload_status,
)
from sleeper_agent_mcp.sleeper_events import EVENT_QUEUE_STARTED, append_event
from sleeper_agent_mcp.sleeper_paths import resolve_task_workspace, sleeper_home
from sleeper_agent_mcp.workspace_scope import resolve_target_workspace

mcp = MCPServer("sleeper-agent-mcp")

# Mandatory: hydrate process env from global ~/.cursor/mcp.json on every MCP start.
_STARTUP_MCP_ENV = apply_global_mcp_env_on_startup()

# Bump when changing tool schemas so you can confirm Cursor loaded new code.
SERVER_BUILD = "2026-09-03-global-install-any-project-v1"

_state = StateManager()


def _default_workspace() -> str:
    """
    Task workspace for tools that omit ``workspace``.

    Must be the user's open project — never the Sleeper install / MCP cwd.
    Raises WorkspaceScopeError when unknown (callers should pass workspace).
    """
    return str(resolve_task_workspace(None))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_status_payload() -> dict[str, Any]:
    plan = get_resource_plan()
    active_workers = _state.active_worker_count()
    return {
        "active_workers": active_workers,
        "max_workers": plan.max_workers,
        "active_worker_queue_ids": _state.active_worker_ids(),
        "container_memory_limit": plan.per_task_memory_limit,
        "per_task_ram_gb": plan.per_task_ram_gb,
        "allocatable_ram_gb": round(plan.allocatable_ram_gb, 2),
    }


def _record_history_entry(result, status: str) -> HistoryEntry:
    return HistoryEntry(
        task_id=result.task_id,
        status=status,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        timestamp=_utc_now(),
    )


def _failure_payload(record, result, retries: int) -> dict[str, Any]:
    remaining = max(0, record.max_retries - retries + 1)
    payload: dict[str, Any] = {
        "queue_id": record.id,
        "failed_task_id": result.task_id,
        "retry_count": retries,
        "max_retries": record.max_retries,
        "agent_repair_attempts_remaining": remaining,
        "traceback": result.traceback(),
        "workspace": result.workspace,
        "failing_file_path": result.failing_file_path,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "memory_limit": result.memory_limit,
        "oom_killed": result.oom_killed,
        "next_action": (
            "Sleeper daemon should post the error into Cursor chat for a local fix, "
            "then call resume_queue when edits are complete."
        ),
    }
    if result.error:
        payload["error"] = result.error
    if result.recommendation:
        payload["recommendation"] = result.recommendation
    return payload


def _run_from_current_step(queue_id: str) -> dict[str, Any]:
    record = _state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    if record.status == QueueStatus.COMPLETED:
        return {
            "status": "COMPLETED",
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": "Queue already completed.",
        }

    if record.status == QueueStatus.ABORTED:
        return {
            "status": "ABORTED",
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": "Queue aborted after exceeding max retries.",
        }

    _state.register_worker(queue_id)
    try:
        record.status = QueueStatus.RUNNING
        _state.update_queue(record)

        while True:
            record = _state.get_queue(queue_id)
            if record is None:
                return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

            if record.current_step_index >= len(record.tasks):
                break

            task = record.tasks[record.current_step_index]
            result = run_task(
                task_id=task.id,
                command=task.command,
                args=task.args,
                workspace=record.workspace,
                runtime=task.runtime,
                url=task.url,
            )

            if result.succeeded:
                record.history.append(_record_history_entry(result, "success"))
                record.current_step_index += 1
                record.last_error = None
                _state.update_queue(record)
                continue

            retries = record.retry_counts.get(task.id, 0) + 1
            record.retry_counts[task.id] = retries
            record.history.append(_record_history_entry(result, "failed"))
            record.last_error = {
                "task_id": task.id,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "traceback": result.traceback(),
                "retry_count": retries,
                "workspace": result.workspace,
                "failing_file_path": result.failing_file_path,
                "memory_limit": result.memory_limit,
                "oom_killed": result.oom_killed,
                "error": result.error,
                "recommendation": result.recommendation,
            }

            if retries > record.max_retries:
                record.status = QueueStatus.ABORTED
                _state.update_queue(record)
                return {
                    "status": "ABORTED",
                    **_failure_payload(record, result, retries),
                }

            record.status = QueueStatus.NEEDS_REPAIR
            _state.update_queue(record)
            return {
                "status": "NEEDS_REPAIR",
                **_failure_payload(record, result, retries),
            }

        record.status = QueueStatus.COMPLETED
        record.last_error = None
        _state.update_queue(record)
        return {
            "status": "COMPLETED",
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": "All tasks completed successfully.",
            "completed_steps": len(record.tasks),
            "workers": _worker_status_payload(),
        }
    finally:
        # Always release worker slot even if execution aborts mid-loop.
        _state.unregister_worker(queue_id)


def _run_afk_orchestrator_loop(queue_id: str) -> dict[str, Any]:
    return run_afk_orchestrator(_state, queue_id, utc_now=_utc_now)


def _start_background_execution(queue_id: str, *, autonomous: bool = False) -> None:
    if autonomous:
        start_afk_background(_state, queue_id, utc_now=_utc_now)
        return

    def _worker() -> None:
        try:
            _run_from_current_step(queue_id)
        finally:
            pass

    thread = threading.Thread(
        target=_worker, name=f"sleeper-{queue_id[:8]}", daemon=True
    )
    thread.start()


def _maybe_apply_pending_env_reload() -> dict[str, Any] | None:
    result = consume_reload_request_if_present()
    return result.to_dict() if result else None


def _overseer_health_payload() -> dict[str, Any]:
    api_key = os.environ.get("SOLARI_API_KEY", "").strip()
    masked = None
    if api_key:
        masked = f"{api_key[:12]}...{api_key[-4:]}" if len(api_key) > 16 else "***"
    try:
        task_ws: str | None = _default_workspace()
    except Exception:  # noqa: BLE001 - health must not fail
        task_ws = None
    return {
        "backend": get_execution_backend(),
        "solari_api_key_set": bool(api_key),
        "solari_api_key_preview": masked,
        "repair_mode": "local_cursor_daemon",
        "orchestrator_timeout_seconds_default": resolve_orchestrator_timeout(),
        "sleeper_home": str(sleeper_home()),
        "workspace": task_ws,
        "cwd": os.getcwd(),
        "server_build": SERVER_BUILD,
        "global_mcp_config_path": str(global_mcp_config_path()),
        "global_mcp_env_reload": get_last_mcp_env_reload(),
    }


def _orchestrator_thread_alive(queue_id: str) -> bool:
    return orchestrator_thread_alive(queue_id)


@mcp.tool()
def start_afk_overseer(
    tasks: list[dict],
    workspace: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    label: str | None = None,
    orchestrator_timeout_seconds: int | None = None,
) -> dict:
    """
    Start a local Cursor overseer: enqueue tasks and run a background orchestrator.

    ``workspace`` must be the absolute path of the project currently open in Cursor
    (Agent window or IDE). Sleeper is installed once globally (SLEEPER_HOME); do not
    pass the Solari/Sleeper clone unless that repo is the project under edit.

    On step failure the orchestrator emits `.sleeper/events.jsonl` events and pauses
    in NEEDS_REPAIR. The local `sleeper_daemon` watch (auto-started) drives Cursor
    chat for repairs and calls `resume_queue` when edits are complete. After
    max_retries (default 3) per failing step, the queue aborts and
    `.overseer_failure.md` is written.

    Place `.overseer.stop` in the workspace root to halt gracefully.
    orchestrator_timeout_seconds defaults to SLEEPER_ORCHESTRATOR_TIMEOUT (7200s).

    Each task dict supports: id, command, args, runtime ('sandbox'|'browser'), url.
    """
    if not tasks:
        raise ValueError("tasks must be a non-empty list")

    validated = validate_tasks(tasks)
    task_specs = [TaskSpec.from_dict(t) for t in validated]
    try:
        ws = str(resolve_task_workspace(workspace))
    except Exception as err:
        raise ValueError(str(err)) from err
    session_label = label or "afk-session"
    orchestrator_timeout = resolve_orchestrator_timeout(orchestrator_timeout_seconds)

    removed = _state.prune_non_running_queues()
    record = _state.create_queue(
        tasks=task_specs,
        workspace=ws,
        max_retries=max_retries,
        stream_mode=StreamMode.SEQUENTIAL,
        label=session_label,
        orchestrator_timeout_seconds=orchestrator_timeout,
        afk_mode=True,
    )
    append_event(
        ws,
        EVENT_QUEUE_STARTED,
        {"queue_id": record.id, "label": session_label, "task_count": len(tasks)},
    )
    _start_background_execution(record.id, autonomous=True)

    sleeper_watch: dict = {"status": "SKIPPED"}
    try:
        from sleeper_agent_mcp.sleeper_watch import ensure_sleeper_watch

        # Auto-start local watch so repair prompts paste without a manual terminal.
        # Uses workspace folder name as window-title when SLEEPER_CURSOR_WINDOW_TITLE unset.
        sleeper_watch = ensure_sleeper_watch(ws)
    except Exception as err:  # noqa: BLE001 - overseer must still start
        sleeper_watch = {"status": "ERROR", "error": str(err), "workspace": ws}

    return {
        "status": "OVERSEER_STARTED",
        "queue_id": record.id,
        "label": session_label,
        "pruned_queues": removed,
        "backend": get_execution_backend(),
        "workspace": ws,
        "resolved_workspace": ws,
        "task_count": len(tasks),
        "max_retries": max_retries,
        "orchestrator_timeout_seconds": orchestrator_timeout,
        "server_build": SERVER_BUILD,
        "overseer_health": _overseer_health_payload(),
        "sleeper_watch": sleeper_watch,
        "message": (
            "Local Cursor overseer running in background. "
            "Sleeper watch is auto-started when possible so repairs paste into Cursor. "
            "Create .overseer.stop to halt."
        ),
        "workers": _worker_status_payload(),
    }


@mcp.tool()
def enqueue_sequence(
    tasks: list[dict],
    workspace: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> str:
    """
    Register a primary ordered task list for sequential execution.

    Each task must be a dict with keys: id, command, args.
    Optional: runtime ('sandbox'|'browser'), url (required for browser).
    Commands are validated against the binary whitelist
    (python, pytest, npm, node). Returns queue_id.
    """
    if not tasks:
        raise ValueError("tasks must be a non-empty list")

    validated = validate_tasks(tasks)
    task_specs = [TaskSpec.from_dict(t) for t in validated]
    try:
        ws = str(resolve_task_workspace(workspace))
    except Exception as err:
        raise ValueError(str(err)) from err

    record = _state.create_queue(
        tasks=task_specs,
        workspace=ws,
        max_retries=max_retries,
        stream_mode=StreamMode.SEQUENTIAL,
    )
    return record.id


@mcp.tool()
def schedule_tasks(queue_id: str, tasks: list[dict], mode: str = "append") -> dict:
    """
    Dynamically inject tasks into an existing queue.

    mode='append': append tasks to run sequentially after the active queue.
    mode='concurrent': spawn a parallel background stream when worker slots and
    free memory permit; otherwise automatically downgrades to append mode.
    """
    if not tasks:
        raise ValueError("tasks must be a non-empty list")

    parent = _state.get_queue(queue_id)
    if parent is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    validated = validate_tasks(tasks)
    task_specs = [TaskSpec.from_dict(t) for t in validated]
    requested_mode = mode.strip().lower()
    plan = get_resource_plan()
    active_workers = _state.active_worker_count()
    workers = _worker_status_payload()

    if requested_mode == "concurrent":
        allowed, downgrade_reason = can_spawn_concurrent_worker(active_workers)
        if allowed:
            child = _state.create_queue(
                tasks=task_specs,
                workspace=parent.workspace,
                max_retries=parent.max_retries,
                parent_queue_id=queue_id,
                stream_mode=StreamMode.CONCURRENT,
            )
            _start_background_execution(child.id, autonomous=False)
            return {
                "status": "SCHEDULED",
                "mode": "concurrent",
                "parent_queue_id": queue_id,
                "child_queue_id": child.id,
                "workspace": child.workspace,
                "scheduled_tasks": len(task_specs),
                "downgraded_to_append": False,
                "workers": workers,
                "container_memory_limit": plan.per_task_memory_limit,
                "system": get_system_resource_snapshot(),
            }

        updated = _state.append_tasks(queue_id, task_specs)
        if updated is None:
            return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

        return {
            "status": "SCHEDULED",
            "mode": "append",
            "queue_id": queue_id,
            "workspace": updated.workspace,
            "scheduled_tasks": len(task_specs),
            "downgraded_to_append": True,
            "downgrade_reason": downgrade_reason,
            "workers": workers,
            "container_memory_limit": plan.per_task_memory_limit,
            "system": get_system_resource_snapshot(),
        }

    updated = _state.append_tasks(queue_id, task_specs)
    if updated is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    return {
        "status": "SCHEDULED",
        "mode": "append",
        "queue_id": queue_id,
        "workspace": updated.workspace,
        "scheduled_tasks": len(task_specs),
        "downgraded_to_append": False,
        "workers": workers,
        "container_memory_limit": plan.per_task_memory_limit,
        "system": get_system_resource_snapshot(),
    }


@mcp.tool()
def execute_queue(queue_id: str) -> dict:
    """
    Execute queued tasks sequentially on the active backend (docker or solari).

    On failure returns NEEDS_REPAIR with normalized paths, full stderr, and
    OOM-specific diagnostics for Docker exit code 137.
    """
    record = _state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    if record.status in {QueueStatus.COMPLETED, QueueStatus.ABORTED}:
        return {
            "status": record.status.value,
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": f"Queue is already {record.status.value}.",
        }

    if record.status == QueueStatus.NEEDS_REPAIR:
        return {
            "status": "NEEDS_REPAIR",
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": (
                "Queue is waiting for repair. Use resume_queue after "
                "fixing files on disk."
            ),
            "last_error": record.last_error,
            "workers": _worker_status_payload(),
        }

    result = _run_from_current_step(queue_id)
    result["workers"] = _worker_status_payload()
    result["container_memory_limit"] = get_resource_plan().per_task_memory_limit
    return result


@mcp.tool()
def get_overseer_status(queue_id: str) -> dict:
    """
    Return AFK orchestrator status for a queue: thread liveness, resolved
    workspace path, kill-switch state, failure artifact, timeouts, and repair history.
    """
    record = _state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    workspace_cwd = str(resolve_target_workspace(record.workspace))
    return {
        "status": "OK",
        "queue_id": queue_id,
        "server_build": SERVER_BUILD,
        "resolved_workspace": workspace_cwd,
        "orchestrator_thread_alive": _orchestrator_thread_alive(queue_id),
        "stop_file_present": is_stop_requested(workspace_cwd),
        "stop_file_path": str(stop_file_path(workspace_cwd)),
        "failure_artifact_present": failure_file_path(workspace_cwd).is_file(),
        "failure_artifact_path": str(failure_file_path(workspace_cwd)),
        "repair_mode": "local_cursor_daemon",
        "orchestrator_timeout_seconds": resolve_orchestrator_timeout(
            record.orchestrator_timeout_seconds
        ),
        "queue": _state.get_status_snapshot(queue_id),
        "workers": _worker_status_payload(),
    }


@mcp.tool()
def stop_overseer(queue_id: str, reason: str = "") -> dict:
    """
    Request graceful halt of an AFK overseer by writing `.overseer.stop`
    to the queue workspace root. The orchestrator checks this file before
    each step and repair attempt.
    """
    record = _state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    workspace_cwd = str(resolve_target_workspace(record.workspace))
    path = request_stop(workspace_cwd, reason=reason)
    return {
        "status": "STOP_REQUESTED",
        "queue_id": queue_id,
        "workspace": workspace_cwd,
        "stop_file_path": str(path),
        "orchestrator_thread_alive": _orchestrator_thread_alive(queue_id),
        "message": (
            "Kill-switch file written. The orchestrator will halt on its next "
            "step or repair boundary."
        ),
    }


@mcp.tool()
def clear_overseer_stop(queue_id: str) -> dict:
    """
    Remove `.overseer.stop` from the queue workspace so a halted overseer
    can be started again in a new session.
    """
    record = _state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    workspace_cwd = str(resolve_target_workspace(record.workspace))
    removed = clear_stop_request(workspace_cwd)
    return {
        "status": "CLEARED" if removed else "NOT_PRESENT",
        "queue_id": queue_id,
        "workspace": workspace_cwd,
        "stop_file_path": str(stop_file_path(workspace_cwd)),
        "removed": removed,
    }


@mcp.tool()
def restart_mcp() -> dict:
    """
    Reload overseer environment from the global Cursor config at ~/.cursor/mcp.json.

    Always reads the sleeper-agent-mcp server entry (mandatory source of truth)
    and applies its env block to this MCP process. Use after editing mcp.json
    instead of killing Python processes manually.

    Does not respawn the MCP host process — call this tool, or restart MCP from
    Cursor settings, after changing global env.
    """
    result = reload_global_mcp_env(apply=True)
    write_reload_status(result)
    payload = result.to_dict()
    payload["server_build"] = SERVER_BUILD
    payload["overseer_health"] = _overseer_health_payload()
    payload["message"] = (
        "Reloaded env from global ~/.cursor/mcp.json."
        if result.status != "ERROR"
        else "Failed to reload env from global ~/.cursor/mcp.json."
    )
    return payload


@mcp.tool()
def get_queue_status(queue_id: str = "") -> dict:
    """
    Return queue state, all-queue summary, and overseer_health (API key status).

    Pass queue_id="" (empty string) for a health check without a specific queue.
    """
    pending_reload = _maybe_apply_pending_env_reload()
    payload: dict[str, Any] = {
        "server_build": SERVER_BUILD,
        "all_queues": _state.get_all_queues_summary(),
        "background_threads": active_background_queue_ids(),
        "workers": _worker_status_payload(),
        "system": get_system_resource_snapshot(),
        "backend": get_execution_backend(),
        "overseer_health": _overseer_health_payload(),
    }
    if pending_reload:
        payload["pending_env_reload_applied"] = pending_reload

    if not queue_id.strip():
        payload["status"] = "OK"
        payload["message"] = (
            "Health check only. Pass a queue_id to inspect a specific queue."
        )
        return payload

    try:
        payload["queue"] = _state.get_status_snapshot(queue_id)
    except KeyError:
        payload["status"] = "ERROR"
        payload["message"] = f"Queue not found: {queue_id}"
        return payload

    return payload


@mcp.tool()
def resume_queue(queue_id: str) -> dict:
    """
    Resume execution at the failing task step after local Cursor repair.

    Used by Sleeper daemon after Cursor edits files on disk. AFK overseer queues
    restart the background orchestrator thread; manual execute_queue sessions run
    synchronously in this call.
    """
    record = _state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    if record.status == QueueStatus.COMPLETED:
        return {
            "status": "COMPLETED",
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": "Queue already completed.",
        }

    if record.status == QueueStatus.ABORTED:
        return {
            "status": "ABORTED",
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": "Queue aborted after exceeding max retries.",
        }

    if record.status not in {
        QueueStatus.NEEDS_REPAIR,
        QueueStatus.PENDING,
        QueueStatus.RUNNING,
    }:
        return {
            "status": "ERROR",
            "queue_id": queue_id,
            "message": f"Cannot resume queue in state {record.status.value}.",
        }

    if record.status == QueueStatus.NEEDS_REPAIR and record.last_error:
        task_id = record.last_error.get("task_id")
        if task_id and record.retry_counts.get(task_id, 0) > record.max_retries:
            record.status = QueueStatus.ABORTED
            _state.update_queue(record)
            return {
                "status": "ABORTED",
                "queue_id": queue_id,
                "workspace": record.workspace,
                "failed_task_id": task_id,
                "retry_count": record.retry_counts[task_id],
                "max_retries": record.max_retries,
                "message": "Max retries exceeded.",
            }

    if record.afk_mode:
        if _orchestrator_thread_alive(queue_id):
            return {
                "status": "RUNNING",
                "queue_id": queue_id,
                "workspace": record.workspace,
                "message": "AFK orchestrator thread is already running.",
            }
        _start_background_execution(queue_id, autonomous=True)
        return {
            "status": "RESUMED",
            "queue_id": queue_id,
            "workspace": record.workspace,
            "message": "AFK orchestrator restarted in background.",
            "workers": _worker_status_payload(),
            "container_memory_limit": get_resource_plan().per_task_memory_limit,
        }

    result = _run_from_current_step(queue_id)
    result["workers"] = _worker_status_payload()
    result["container_memory_limit"] = get_resource_plan().per_task_memory_limit
    return result


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

