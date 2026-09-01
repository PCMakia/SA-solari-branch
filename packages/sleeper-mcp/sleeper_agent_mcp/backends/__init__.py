"""Backend selection for Sleeper Agent task execution."""

from __future__ import annotations

import os

from sleeper_agent_mcp.backends.base import TaskRunner
from sleeper_agent_mcp.backends.docker_runner import DockerTaskRunner
from sleeper_agent_mcp.backends.solari_runner import SolariTaskRunner
from sleeper_agent_mcp.execution.types import ExecutionBackend, ExecutionResult, TaskRuntime

_RUNNERS: dict[str, TaskRunner] = {
    ExecutionBackend.DOCKER.value: DockerTaskRunner(),
    ExecutionBackend.SOLARI.value: SolariTaskRunner(),
}


def get_execution_backend() -> str:
    backend = os.environ.get("SLEEPER_BACKEND", ExecutionBackend.DOCKER.value)
    normalized = backend.strip().lower()
    if normalized not in _RUNNERS:
        raise ValueError(
            f"Unknown SLEEPER_BACKEND '{backend}'. "
            f"Use one of: {', '.join(sorted(_RUNNERS))}"
        )
    return normalized


def get_task_runner() -> TaskRunner:
    return _RUNNERS[get_execution_backend()]


def run_task(
    *,
    task_id: str,
    command: str,
    args: list[str],
    workspace: str,
    runtime: str = "sandbox",
    url: str | None = None,
    timeout_seconds: int | None = None,
    memory_limit: str | None = None,
) -> ExecutionResult:
    """Dispatch a task to the configured execution backend."""
    task_runtime = TaskRuntime(runtime)
    return get_task_runner().run_task(
        task_id=task_id,
        command=command,
        args=args,
        workspace=workspace,
        runtime=task_runtime,
        url=url,
        timeout_seconds=timeout_seconds,
        memory_limit=memory_limit,
    )
