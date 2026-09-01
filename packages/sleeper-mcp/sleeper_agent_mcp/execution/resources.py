"""Host resource planning for concurrent worker scheduling."""

from __future__ import annotations

import os

import psutil

from sleeper_agent_mcp.execution.types import ResourcePlan

DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("SLEEPER_TASK_TIMEOUT", "600"))
MEMORY_AVAILABLE_THRESHOLD = float(os.environ.get("SLEEPER_MEMORY_THRESHOLD", "0.20"))
DOCKER_OOM_EXIT_CODE = 137
DEFAULT_DOCKER_IMAGE = os.environ.get("SLEEPER_DOCKER_IMAGE", "python:3.11-slim")

GB = 1024**3
MB = 1024**2
MIN_HOST_BUFFER_BYTES = 4 * GB
HOST_BUFFER_RATIO = 0.25
MIN_PER_TASK_RAM_GB = 2
WORKER_SLOT_RAM_GB = 4


def parse_ram_limit(value: str) -> int:
    """Parse a RAM limit string (e.g. '4g', '512m') into bytes."""
    normalized = value.strip().lower()
    if normalized.endswith("g"):
        return int(float(normalized[:-1]) * GB)
    if normalized.endswith("m"):
        return int(float(normalized[:-1]) * MB)
    if normalized.endswith("b"):
        return int(normalized[:-1])
    return int(float(normalized) * GB)


def format_docker_memory_limit(bytes_value: int) -> str:
    """Format bytes as a Docker-compatible --memory value."""
    if bytes_value >= GB and bytes_value % GB == 0:
        return f"{bytes_value // GB}g"
    if bytes_value >= MB and bytes_value % MB == 0:
        return f"{bytes_value // MB}m"
    return f"{bytes_value}b"


def get_resource_plan() -> ResourcePlan:
    """
    Compute dynamic RAM allocation for concurrent workers and per-container caps.

    Reserves 25% of total RAM (minimum 4 GB) for the OS and Cursor, then derives
    worker slots and per-task limits from the remaining allocatable memory.
    """
    vm = psutil.virtual_memory()
    total = int(vm.total)
    host_buffer = max(int(total * HOST_BUFFER_RATIO), MIN_HOST_BUFFER_BYTES)
    allocatable = max(total - host_buffer, MIN_PER_TASK_RAM_GB * GB)
    allocatable_gb = allocatable / GB

    max_workers = max(1, int(allocatable_gb // WORKER_SLOT_RAM_GB))
    max_workers_override = os.environ.get("SLEEPER_MAX_CONCURRENT")
    if max_workers_override:
        max_workers = max(1, int(max_workers_override))

    per_task_ram_gb = max(MIN_PER_TASK_RAM_GB, int(allocatable_gb // max_workers))
    task_ram_override = os.environ.get("SLEEPER_TASK_RAM")
    if task_ram_override:
        per_task_bytes = parse_ram_limit(task_ram_override)
        per_task_memory_limit = format_docker_memory_limit(per_task_bytes)
        per_task_ram_gb = max(MIN_PER_TASK_RAM_GB, per_task_bytes // GB)
    else:
        per_task_memory_limit = f"{per_task_ram_gb}g"

    available_ratio = vm.available / vm.total if vm.total else 0.0
    memory_allows_concurrent = available_ratio > MEMORY_AVAILABLE_THRESHOLD

    return ResourcePlan(
        total_ram_bytes=total,
        host_buffer_bytes=host_buffer,
        allocatable_ram_bytes=allocatable,
        allocatable_ram_gb=allocatable_gb,
        max_workers=max_workers,
        per_task_ram_gb=per_task_ram_gb,
        per_task_memory_limit=per_task_memory_limit,
        memory_allows_concurrent=memory_allows_concurrent,
    )


def get_system_resource_snapshot() -> dict[str, float | bool | int | str]:
    """Return host RAM load, allocation plan, and concurrency eligibility."""
    vm = psutil.virtual_memory()
    plan = get_resource_plan()
    available_ratio = vm.available / vm.total if vm.total else 0.0
    return {
        "memory_total_bytes": float(vm.total),
        "memory_available_bytes": float(vm.available),
        "memory_used_percent": float(vm.percent),
        "memory_available_percent": round(available_ratio * 100, 2),
        "memory_allows_concurrent": plan.memory_allows_concurrent,
        "memory_threshold_percent": MEMORY_AVAILABLE_THRESHOLD * 100,
        "allocation": plan.to_dict(),
        "backend": os.environ.get("SLEEPER_BACKEND", "docker").strip().lower(),
    }


def memory_allows_concurrent() -> bool:
    """True when available RAM exceeds the configured threshold (default 20%)."""
    return get_resource_plan().memory_allows_concurrent


def can_spawn_concurrent_worker(active_workers: int) -> tuple[bool, str | None]:
    """
    Check whether a new concurrent worker stream may be started.

    Returns (allowed, downgrade_reason).
    """
    plan = get_resource_plan()
    if active_workers >= plan.max_workers:
        return (
            False,
            f"Active workers ({active_workers}) reached max_workers ({plan.max_workers}).",
        )
    if not plan.memory_allows_concurrent:
        return (
            False,
            (
                "Available host RAM is below the concurrency threshold "
                f"({MEMORY_AVAILABLE_THRESHOLD * 100:.0f}%)."
            ),
        )
    return True, None
