"""Long-lived push orchestrator: run steps, pause for local Cursor repair via Sleeper daemon."""

from __future__ import annotations

import time
from typing import Any, Callable

from sleeper_agent_mcp.overseer_controls import (
    clear_transient_caches,
    is_stop_requested,
    resolve_orchestrator_timeout,
    write_failure_artifact,
    write_stop_artifact,
)
from sleeper_agent_mcp.runner import run_task
from sleeper_agent_mcp.sleeper_events import (
    EVENT_AWAITING_DAEMON,
    EVENT_NEEDS_REPAIR,
    EVENT_QUEUE_ABORTED,
    EVENT_QUEUE_COMPLETED,
    EVENT_QUEUE_STOPPED,
    EVENT_STEP_FAILED,
    EVENT_STEP_PASSED,
    append_event,
)
from sleeper_agent_mcp.state import HistoryEntry, QueueRecord, QueueStatus, StateManager
from sleeper_agent_mcp.workspace_scope import resolve_target_workspace, scope_failing_file_path


def _execution_command(task) -> str:
    parts = [task.command, *task.args]
    return " ".join(parts)


def _record_history_entry(result, status: str, timestamp: str) -> HistoryEntry:
    return HistoryEntry(
        task_id=result.task_id,
        status=status,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        timestamp=timestamp,
    )


def _build_last_error(record: QueueRecord, result, retries: int) -> dict[str, Any]:
    workspace_cwd = str(resolve_target_workspace(record.workspace))
    scoped_path = scope_failing_file_path(
        workspace_cwd,
        result.failing_file_path,
        stderr=result.stderr,
    )
    task = record.tasks[record.current_step_index]
    return {
        "task_id": result.task_id,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "traceback": result.traceback(),
        "retry_count": retries,
        "workspace": workspace_cwd,
        "failing_file_path": scoped_path or result.failing_file_path,
        "memory_limit": result.memory_limit,
        "oom_killed": result.oom_killed,
        "error": result.error,
        "recommendation": result.recommendation,
        "execution_command": _execution_command(task),
    }


def _failure_payload(record: QueueRecord, result, retries: int) -> dict[str, Any]:
    remaining = max(0, record.max_retries - retries + 1)
    workspace_cwd = str(resolve_target_workspace(record.workspace))
    payload: dict[str, Any] = {
        "queue_id": record.id,
        "failed_task_id": result.task_id,
        "retry_count": retries,
        "max_retries": record.max_retries,
        "daemon_repair_attempts_remaining": remaining,
        "traceback": result.traceback(),
        "workspace": workspace_cwd,
        "failing_file_path": scope_failing_file_path(
            workspace_cwd, result.failing_file_path, stderr=result.stderr
        )
        or result.failing_file_path,
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


def _halt_for_stop(
    state: StateManager,
    record: QueueRecord,
    *,
    utc_now: Callable[[], str],
) -> dict[str, Any]:
    record.status = QueueStatus.STOPPED_BY_USER
    state.update_queue(record)
    workspace_cwd = str(resolve_target_workspace(record.workspace))
    artifact = write_stop_artifact(
        workspace_cwd,
        queue_id=record.id,
        label=record.label,
        step_index=record.current_step_index,
    )
    append_event(
        workspace_cwd,
        EVENT_QUEUE_STOPPED,
        {"queue_id": record.id, "step_index": record.current_step_index},
    )
    return {
        "status": "STOPPED_BY_USER",
        "queue_id": record.id,
        "workspace": workspace_cwd,
        "active_step_index": record.current_step_index,
        "message": "Orchestrator halted because .overseer.stop was present.",
        "artifact_path": str(artifact),
        "timestamp": utc_now(),
    }


def run_afk_orchestrator(
    state: StateManager,
    queue_id: str,
    *,
    utc_now: Callable[[], str],
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """
    Autonomous overseer loop.

    Runs tasks sequentially. On step failure, emits events for the local Sleeper
    daemon and pauses in NEEDS_REPAIR until resume_queue is called.
    """
    record = state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

    if record.status == QueueStatus.COMPLETED:
        return {
            "status": "COMPLETED",
            "queue_id": queue_id,
            "workspace": str(resolve_target_workspace(record.workspace)),
            "message": "Queue already completed.",
        }

    if record.status == QueueStatus.ABORTED:
        return {
            "status": "ABORTED",
            "queue_id": queue_id,
            "workspace": str(resolve_target_workspace(record.workspace)),
            "message": "Queue aborted after exceeding max retries.",
        }

    if record.status == QueueStatus.STOPPED_BY_USER:
        return {
            "status": "STOPPED_BY_USER",
            "queue_id": queue_id,
            "workspace": str(resolve_target_workspace(record.workspace)),
            "message": "Queue was stopped by user kill-switch.",
        }

    state.register_worker(queue_id)
    repair_history: list[dict[str, Any]] = list(record.repair_history)
    started_at = monotonic()
    orchestrator_timeout = resolve_orchestrator_timeout(record.orchestrator_timeout_seconds)

    try:
        record.status = QueueStatus.RUNNING
        state.update_queue(record)

        while True:
            if monotonic() - started_at > orchestrator_timeout:
                record.status = QueueStatus.ABORTED
                record.repair_history = repair_history
                state.update_queue(record)
                workspace_cwd = str(resolve_target_workspace(record.workspace))
                artifact = write_failure_artifact(
                    workspace_cwd,
                    queue_id=record.id,
                    label=record.label,
                    failed_task_id=record.tasks[record.current_step_index].id
                    if record.current_step_index < len(record.tasks)
                    else "unknown",
                    retry_count=0,
                    max_retries=record.max_retries,
                    last_error={
                        "error": "orchestrator_timeout",
                        "timeout_seconds": orchestrator_timeout,
                    },
                    repair_history=repair_history,
                    tasks=[t.to_dict() for t in record.tasks],
                )
                append_event(
                    workspace_cwd,
                    EVENT_QUEUE_ABORTED,
                    {"queue_id": record.id, "reason": "orchestrator_timeout"},
                )
                return {
                    "status": "ABORTED",
                    "queue_id": queue_id,
                    "workspace": workspace_cwd,
                    "message": (
                        f"Orchestrator exceeded timeout of {orchestrator_timeout}s"
                    ),
                    "artifact_path": str(artifact),
                }

            record = state.get_queue(queue_id)
            if record is None:
                return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}

            workspace_cwd = str(resolve_target_workspace(record.workspace))
            if is_stop_requested(workspace_cwd):
                return _halt_for_stop(state, record, utc_now=utc_now)

            if record.current_step_index >= len(record.tasks):
                break

            task = record.tasks[record.current_step_index]
            result = run_task(
                task_id=task.id,
                command=task.command,
                args=task.args,
                workspace=workspace_cwd,
                runtime=task.runtime,
                url=task.url,
            )

            if result.succeeded:
                record.history.append(
                    _record_history_entry(result, "success", utc_now())
                )
                record.current_step_index += 1
                record.last_error = None
                state.update_queue(record)
                append_event(
                    workspace_cwd,
                    EVENT_STEP_PASSED,
                    {
                        "queue_id": record.id,
                        "task_id": task.id,
                        "step_index": record.current_step_index - 1,
                    },
                )
                continue

            retries = record.retry_counts.get(task.id, 0) + 1
            record.retry_counts[task.id] = retries
            record.history.append(_record_history_entry(result, "failed", utc_now()))
            record.last_error = _build_last_error(record, result, retries)

            append_event(
                workspace_cwd,
                EVENT_STEP_FAILED,
                {
                    "queue_id": record.id,
                    "task_id": task.id,
                    "retry_count": retries,
                    "last_error": record.last_error,
                },
            )

            if retries > record.max_retries:
                record.status = QueueStatus.ABORTED
                record.repair_history = repair_history
                state.update_queue(record)
                artifact = write_failure_artifact(
                    workspace_cwd,
                    queue_id=record.id,
                    label=record.label,
                    failed_task_id=task.id,
                    retry_count=retries,
                    max_retries=record.max_retries,
                    last_error=record.last_error,
                    repair_history=repair_history,
                    tasks=[t.to_dict() for t in record.tasks],
                )
                append_event(
                    workspace_cwd,
                    EVENT_QUEUE_ABORTED,
                    {
                        "queue_id": record.id,
                        "failed_task_id": task.id,
                        "retry_count": retries,
                    },
                )
                return {
                    "status": "ABORTED",
                    **_failure_payload(record, result, retries),
                    "artifact_path": str(artifact),
                    "message": (
                        f"Step '{task.id}' failed after {record.max_retries} "
                        "repair attempts. See .overseer_failure.md."
                    ),
                }

            record.status = QueueStatus.NEEDS_REPAIR
            record.repair_history = repair_history
            state.update_queue(record)

            append_event(
                workspace_cwd,
                EVENT_NEEDS_REPAIR,
                {
                    "queue_id": record.id,
                    "task_id": task.id,
                    "retry_count": retries,
                    "last_error": record.last_error,
                },
            )
            append_event(
                workspace_cwd,
                EVENT_AWAITING_DAEMON,
                {
                    "queue_id": record.id,
                    "task_id": task.id,
                    "retry_count": retries,
                    "error_message": result.stderr or result.traceback(),
                },
            )

            return {
                "status": "NEEDS_REPAIR",
                "queue_id": queue_id,
                "workspace": workspace_cwd,
                "task_id": task.id,
                "retry_count": retries,
                "max_retries": record.max_retries,
                "last_error": record.last_error,
                "message": (
                    "Step failed. Sleeper daemon should drive Cursor chat for a local "
                    "fix, then resume_queue or update tasks."
                ),
            }

        record.status = QueueStatus.COMPLETED
        record.last_error = None
        record.repair_history = repair_history
        state.update_queue(record)
        workspace_cwd = str(resolve_target_workspace(record.workspace))
        append_event(
            workspace_cwd,
            EVENT_QUEUE_COMPLETED,
            {"queue_id": record.id, "completed_steps": len(record.tasks)},
        )
        return {
            "status": "COMPLETED",
            "queue_id": queue_id,
            "workspace": workspace_cwd,
            "message": "All tasks completed successfully.",
            "completed_steps": len(record.tasks),
            "repair_turns": len(repair_history),
        }
    finally:
        state.unregister_worker(queue_id)


def record_daemon_repair_attempt(
    state: StateManager,
    queue_id: str,
    *,
    task_id: str,
    cursor_response: str,
    utc_now: Callable[[], str],
) -> None:
    """Append a Cursor chat repair attempt to queue repair history."""
    record = state.get_queue(queue_id)
    if record is None:
        return
    history = list(record.repair_history)
    history.append(
        {
            "task_id": task_id,
            "attempt": record.retry_counts.get(task_id, 0),
            "timestamp": utc_now(),
            "cursor_response": cursor_response,
        }
    )
    record.repair_history = history
    state.update_queue(record)
    clear_transient_caches(record.workspace)
