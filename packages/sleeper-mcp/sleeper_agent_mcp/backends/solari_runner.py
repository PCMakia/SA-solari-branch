"""Solari cloud sandbox and browser execution backend."""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path
from typing import Any

from sleeper_agent_mcp.execution.resources import DEFAULT_TIMEOUT_SECONDS, get_resource_plan
from sleeper_agent_mcp.execution.types import ExecutionResult, TaskRuntime
from sleeper_agent_mcp.execution.validate import infer_failing_file_path, validate_command
from sleeper_agent_mcp.state import resolve_path

SOLARI_BASE_URL = os.environ.get("SOLARI_BASE_URL", "https://api.getsolari.com")
SOLARI_SANDBOX_TEMPLATE = os.environ.get("SOLARI_SANDBOX_TEMPLATE", "base")
SOLARI_SANDBOX_TIMEOUT_MS = int(
    os.environ.get("SOLARI_SANDBOX_TIMEOUT_MS", str(5 * 60_000))
)
SKIP_UPLOAD_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        ".next",
        "__pycache__",
        ".venv",
        "venv",
        ".turbo",
        "dist",
        "build",
    }
)


def _should_skip_workspace_sync(command: str, args: list[str]) -> bool:
    """Inline one-liners do not need the full workspace uploaded to Solari."""
    return command in {"python", "python3"} and bool(args) and args[0] == "-c"


def _is_python_inline(command: str, args: list[str]) -> bool:
    return command in {"python", "python3"} and len(args) >= 2 and args[0] == "-c"


def _iter_workspace_files(workspace_path: Path):
    for path in workspace_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_UPLOAD_DIR_NAMES for part in path.relative_to(workspace_path).parts):
            continue
        yield path


def _format_run_code_result(result: Any) -> tuple[int, str, str]:
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    for item in result.results:
        text = getattr(item, "text", None)
        if not text:
            continue
        item_type = getattr(item, "type", "result")
        if item_type in {"stdout", "result"}:
            stdout_parts.append(text)
        elif item_type == "stderr":
            stderr_parts.append(text)
    if result.error:
        error_text = result.error
        if isinstance(error_text, dict):
            error_text = error_text.get("message") or str(error_text)
        stderr_parts.append(str(error_text))
        return 1, "".join(stdout_parts), "".join(stderr_parts)
    return 0, "".join(stdout_parts), "".join(stderr_parts)


def _resolve_sandbox_command(command: str, args: list[str]) -> tuple[str, list[str]]:
    """
    Map host-style commands to Solari guest executables.

    Solari's `base` template provides `python3`, not `python`. `commands.run`
    does not invoke a shell, so we wrap in `sh -c` for PATH resolution.
    """
    if command in {"python", "python3"}:
        script = "python3 " + " ".join(shlex.quote(arg) for arg in args)
        return "sh", ["-c", script]
    if command == "pytest":
        script = "python3 -m pytest " + " ".join(shlex.quote(arg) for arg in args)
        return "sh", ["-c", script]
    if command == "npm":
        script = "npm " + " ".join(shlex.quote(arg) for arg in args)
        return "sh", ["-c", script]
    if command == "node":
        script = "node " + " ".join(shlex.quote(arg) for arg in args)
        return "sh", ["-c", script]
    return command, args


def _require_api_key() -> str:
    api_key = os.environ.get("SOLARI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "SOLARI_API_KEY is not set. Get a key at https://console.getsolari.com"
        )
    return api_key


def _run_async(coro):
    return asyncio.run(coro)


async def _run_sandbox_command(
    *,
    command: str,
    args: list[str],
    workspace_path: Path,
    timeout_seconds: int,
) -> tuple[int, str, str]:
    from solari_sandbox import SandboxClient

    api_key = _require_api_key()
    skip_sync = _should_skip_workspace_sync(command, args)
    use_run_code = _is_python_inline(command, args)
    guest_command, guest_args = _resolve_sandbox_command(command, args)

    async with SandboxClient(api_key=api_key, base_url=SOLARI_BASE_URL) as client:
        sandbox = await client.create(
            template=SOLARI_SANDBOX_TEMPLATE,
            timeout_ms=SOLARI_SANDBOX_TIMEOUT_MS,
        )
        try:
            await sandbox.connect()
            remote_workspace = "/workspace"
            await sandbox.commands.run(
                "mkdir",
                args=["-p", remote_workspace],
            )

            if not skip_sync:
                for path in _iter_workspace_files(workspace_path):
                    rel = path.relative_to(workspace_path).as_posix()
                    remote_path = f"{remote_workspace}/{rel}"
                    parent = str(Path(remote_path).parent).replace("\\", "/")
                    await sandbox.commands.run("mkdir", args=["-p", parent])
                    await sandbox.files.write(remote_path, path.read_bytes())

            if use_run_code:
                result = await sandbox.run_code(args[1])
                return _format_run_code_result(result)

            out = await sandbox.commands.run(
                guest_command,
                args=guest_args,
                cwd=remote_workspace,
                timeout_ms=timeout_seconds * 1000,
            )
            return out.exitCode, out.stdout or "", out.stderr or ""
        finally:
            await sandbox.kill()


async def _run_browser_smoke(*, url: str) -> tuple[int, str, str, str | None]:
    from solari_browser import Solari

    api_key = _require_api_key()
    solari = Solari(api_key=api_key)
    browser = await solari.launch(recording=True)
    session_id = browser.id
    try:
        page = await browser.new_page()
        await page.goto(url)
        title = await page.title()
        await asyncio.sleep(1)
        return 0, f"Visited {url}\nPage title: {title}", "", session_id
    except Exception as exc:
        return 1, "", str(exc), session_id
    finally:
        await browser.close()
        await solari.close()


class SolariTaskRunner:
    name = "solari"

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
    ) -> ExecutionResult:
        workspace_path = resolve_path(workspace)
        if not workspace_path.is_dir():
            raise FileNotFoundError(f"Workspace directory does not exist: {workspace_path}")

        plan = get_resource_plan()
        limit = memory_limit or plan.per_task_memory_limit
        timeout = timeout_seconds or DEFAULT_TIMEOUT_SECONDS

        try:
            if runtime == TaskRuntime.BROWSER:
                target_url = url or (args[0] if args else None)
                if not target_url:
                    raise ValueError("Browser tasks require a url.")
                returncode, stdout, stderr, session_id = _run_async(
                    _run_browser_smoke(url=target_url)
                )
                command_label = "browser"
                exec_args = [target_url]
            else:
                binary = validate_command(command)
                returncode, stdout, stderr = _run_async(
                    _run_sandbox_command(
                        command=binary,
                        args=args,
                        workspace_path=workspace_path,
                        timeout_seconds=timeout,
                    )
                )
                command_label = binary
                exec_args = args
                session_id = None
        except Exception as exc:
            return ExecutionResult(
                task_id=task_id,
                command=command,
                args=args,
                returncode=1,
                stdout="",
                stderr=str(exc),
                workspace=str(workspace_path),
                backend=self.name,
                runtime=runtime.value,
                memory_limit=limit,
                error=str(exc),
            )

        failing_path = None
        if returncode != 0 and runtime == TaskRuntime.SANDBOX:
            failing_path = infer_failing_file_path(workspace_path, args, stderr)

        return ExecutionResult(
            task_id=task_id,
            command=command_label,
            args=exec_args,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            workspace=str(workspace_path),
            backend=self.name,
            runtime=runtime.value,
            memory_limit=limit,
            failing_file_path=failing_path,
            session_id=session_id,
            replay_url=(
                f"/api/replay/{session_id}" if session_id else None
            ),
        )
