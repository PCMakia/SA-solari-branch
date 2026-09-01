"""Task runner protocol shared by Docker and Solari backends."""

from __future__ import annotations

from typing import Protocol

from sleeper_agent_mcp.execution.types import ExecutionResult, TaskRuntime


class TaskRunner(Protocol):
    """Execute a single queued task and return a normalized result."""

    name: str

    def run_task(
        self,
        *,
        task_id: str,
        command: str,
        args: list[str],
        workspace: str,
        runtime: TaskRuntime = TaskRuntime.SANDBOX,
        url: str | None = None,
        timeout_seconds: int | None = None,
        memory_limit: str | None = None,
    ) -> ExecutionResult: ...
