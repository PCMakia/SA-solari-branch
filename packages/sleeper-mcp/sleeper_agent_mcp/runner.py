"""Backward-compatible facade over execution backends and resource planning."""

from __future__ import annotations

from sleeper_agent_mcp.backends import get_execution_backend, get_task_runner, run_task
from sleeper_agent_mcp.execution.resources import (
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_TIMEOUT_SECONDS,
    DOCKER_OOM_EXIT_CODE,
    can_spawn_concurrent_worker,
    get_resource_plan,
    get_system_resource_snapshot,
    memory_allows_concurrent,
)
from sleeper_agent_mcp.execution.types import ExecutionResult, ResourcePlan, WhitelistError
from sleeper_agent_mcp.execution.validate import validate_command, validate_tasks

__all__ = [
    "DEFAULT_DOCKER_IMAGE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DOCKER_OOM_EXIT_CODE",
    "ExecutionResult",
    "ResourcePlan",
    "WhitelistError",
    "can_spawn_concurrent_worker",
    "get_execution_backend",
    "get_resource_plan",
    "get_system_resource_snapshot",
    "get_task_runner",
    "memory_allows_concurrent",
    "run_task",
    "run_task_in_docker",
    "validate_command",
    "validate_tasks",
]


def run_task_in_docker(**kwargs) -> ExecutionResult:
    """Legacy alias — routes through the active backend dispatcher."""
    runtime = kwargs.pop("runtime", "sandbox")
    url = kwargs.pop("url", None)
    return run_task(
        runtime=runtime,
        url=url,
        **kwargs,
    )
