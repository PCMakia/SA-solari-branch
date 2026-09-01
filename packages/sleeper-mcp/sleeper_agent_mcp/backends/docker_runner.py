"""Docker-isolated task execution (local backend)."""

from __future__ import annotations

import subprocess

from sleeper_agent_mcp.execution.types import ExecutionResult, TaskRuntime
from sleeper_agent_mcp.execution.validate import infer_failing_file_path, validate_command
from sleeper_agent_mcp.execution.resources import (
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_TIMEOUT_SECONDS,
    DOCKER_OOM_EXIT_CODE,
    get_resource_plan,
)
from sleeper_agent_mcp.state import resolve_path


def _build_oom_diagnostics(memory_limit: str) -> tuple[str, str]:
    error = (
        f"Task terminated by Docker OOM Killer (exceeded {memory_limit} RAM cap)."
    )
    recommendation = (
        "Refactor code to process data in chunks, or re-schedule task in 'append' mode."
    )
    return error, recommendation


def _docker_available() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class DockerTaskRunner:
    name = "docker"

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
        docker_image: str | None = None,
    ) -> ExecutionResult:
        if runtime == TaskRuntime.BROWSER:
            return ExecutionResult(
                task_id=task_id,
                command=command,
                args=args,
                returncode=1,
                stdout="",
                stderr=(
                    "Browser runtime requires SLEEPER_BACKEND=solari. "
                    "Docker backend only supports sandbox tasks."
                ),
                workspace=workspace,
                backend=self.name,
                runtime=runtime.value,
            )

        binary = validate_command(command)
        workspace_path = resolve_path(workspace)
        if not workspace_path.is_dir():
            raise FileNotFoundError(f"Workspace directory does not exist: {workspace_path}")

        if not _docker_available():
            raise RuntimeError(
                "Docker is not available. Ensure Docker is installed and running."
            )

        plan = get_resource_plan()
        limit = memory_limit or plan.per_task_memory_limit
        image = docker_image or DEFAULT_DOCKER_IMAGE
        timeout = timeout_seconds or DEFAULT_TIMEOUT_SECONDS

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            limit,
            "-v",
            f"{workspace_path}:/workspace",
            "-w",
            "/workspace",
            image,
            binary,
            *args,
        ]

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            stderr = proc.stderr
            stdout = proc.stdout
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            stderr = (
                f"Task timed out after {timeout} seconds.\n"
                + (exc.stderr or "" if isinstance(exc.stderr, str) else "")
            )
            stdout = exc.stdout or "" if isinstance(exc.stdout, str) else ""
            returncode = -1

        oom_killed = returncode == DOCKER_OOM_EXIT_CODE
        error = None
        recommendation = None
        failing_path = None

        if oom_killed:
            error, recommendation = _build_oom_diagnostics(limit)
            stderr = f"{error}\n{recommendation}\n\n{stderr or ''}".strip()
        elif returncode != 0:
            failing_path = infer_failing_file_path(workspace_path, args, stderr)

        return ExecutionResult(
            task_id=task_id,
            command=binary,
            args=args,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            workspace=str(workspace_path),
            backend=self.name,
            runtime=runtime.value,
            memory_limit=limit,
            failing_file_path=failing_path,
            oom_killed=oom_killed,
            error=error,
            recommendation=recommendation,
        )
