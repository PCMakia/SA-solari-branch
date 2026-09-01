"""Execution result and backend configuration types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionBackend(str, Enum):
    DOCKER = "docker"
    SOLARI = "solari"


class TaskRuntime(str, Enum):
    """Where a queued task should execute."""

    SANDBOX = "sandbox"
    BROWSER = "browser"


class WhitelistError(ValueError):
    """Raised when a command is not on the allowed binary whitelist."""


@dataclass
class ResourcePlan:
    """Dynamic memory allocation plan derived from host resources."""

    total_ram_bytes: int
    host_buffer_bytes: int
    allocatable_ram_bytes: int
    allocatable_ram_gb: float
    max_workers: int
    per_task_ram_gb: int
    per_task_memory_limit: str
    memory_allows_concurrent: bool

    def to_dict(self) -> dict[str, float | int | str | bool]:
        return {
            "total_ram_bytes": self.total_ram_bytes,
            "host_buffer_bytes": self.host_buffer_bytes,
            "allocatable_ram_bytes": self.allocatable_ram_bytes,
            "allocatable_ram_gb": round(self.allocatable_ram_gb, 2),
            "max_workers": self.max_workers,
            "per_task_ram_gb": self.per_task_ram_gb,
            "per_task_memory_limit": self.per_task_memory_limit,
            "memory_allows_concurrent": self.memory_allows_concurrent,
        }


@dataclass
class ExecutionResult:
    task_id: str
    command: str
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    workspace: str
    backend: str = "docker"
    runtime: str = "sandbox"
    memory_limit: str = ""
    failing_file_path: str | None = None
    oom_killed: bool = False
    error: str | None = None
    recommendation: str | None = None
    session_id: str | None = None
    replay_url: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def traceback(self) -> str:
        """Human-readable failure summary for agent self-healing."""
        lines = [
            f"Task '{self.task_id}' failed with exit code {self.returncode}.",
            f"Backend: {self.backend} ({self.runtime})",
            f"Command: {self.command} {' '.join(self.args)}".strip(),
            f"Workspace: {self.workspace}",
            f"Memory limit: {self.memory_limit or 'unset'}",
        ]
        if self.session_id:
            lines.append(f"Session: {self.session_id}")
        if self.oom_killed and self.error:
            lines.append(f"Error: {self.error}")
        if self.recommendation:
            lines.append(f"Recommendation: {self.recommendation}")
        if self.failing_file_path:
            lines.append(f"Failing file: {self.failing_file_path}")
        lines.extend(
            [
                "",
                "=== stdout ===",
                self.stdout or "(empty)",
                "",
                "=== stderr ===",
                self.stderr or "(empty)",
            ]
        )
        return "\n".join(lines)
