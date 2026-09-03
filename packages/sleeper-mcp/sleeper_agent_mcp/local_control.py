"""Shared local control helpers for MCP server and Sleeper daemon."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

from sleeper_agent_mcp.orchestrator import run_afk_orchestrator
from sleeper_agent_mcp.state import QueueStatus, StateManager, TaskSpec

_background_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def orchestrator_thread_alive(queue_id: str) -> bool:
    with _threads_lock:
        thread = _background_threads.get(queue_id)
    return bool(thread and thread.is_alive())


def active_background_queue_ids() -> list[str]:
    with _threads_lock:
        return list(_background_threads.keys())


def start_afk_background(
    state: StateManager,
    queue_id: str,
    *,
    utc_now: Callable[[], str] | None = None,
) -> None:
    now = utc_now or _utc_now

    def _worker() -> None:
        try:
            run_afk_orchestrator(state, queue_id, utc_now=now)
        finally:
            with _threads_lock:
                _background_threads.pop(queue_id, None)

    thread = threading.Thread(
        target=_worker,
        name=f"sleeper-{queue_id[:8]}",
        daemon=True,
    )
    with _threads_lock:
        _background_threads[queue_id] = thread
    thread.start()


def resume_afk_queue(state: StateManager, queue_id: str) -> dict[str, Any]:
    record = state.get_queue(queue_id)
    if record is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}
    if not record.afk_mode:
        return {"status": "ERROR", "message": "Queue is not an AFK overseer session."}
    if orchestrator_thread_alive(queue_id):
        return {
            "status": "RUNNING",
            "queue_id": queue_id,
            "message": "Orchestrator thread already running.",
        }
    if record.status == QueueStatus.COMPLETED:
        return {"status": "COMPLETED", "queue_id": queue_id}
    start_afk_background(state, queue_id)
    return {"status": "RESUMED", "queue_id": queue_id}


def update_queue_tasks(state: StateManager, queue_id: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    specs = [TaskSpec.from_dict(task) for task in tasks]
    updated = state.replace_tasks(queue_id, specs)
    if updated is None:
        return {"status": "ERROR", "message": f"Queue not found: {queue_id}"}
    return {"status": "UPDATED", "queue_id": queue_id, "task_count": len(specs)}
