"""Cursor SDK repair-turn integration for autonomous overseer loops."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sleeper_agent_mcp.overseer_controls import resolve_repair_timeout
from sleeper_agent_mcp.repair_git import (
    RepairGitContext,
    build_repair_git_context,
    sync_cloud_repair_to_workspace,
)
from sleeper_agent_mcp.workspace_scope import (
    resolve_target_workspace,
    scope_failing_file_path,
    workspace_relative_display,
)

DEFAULT_REPAIR_MODEL = "auto"
DEFAULT_REPAIR_MODE = "agent"
DEFAULT_REPAIR_RUNTIME = "auto"
TRACE_TAIL_LINES = 40
REPAIR_PAYLOAD_FILE = ".overseer_repair_ctx.json"
REPAIR_RESULT_FILE = ".overseer_repair_result.json"

REPAIR_GUARDRAIL = (
    "CRITICAL: You are running in an automated REPAIR TURN. "
    "Fix the failing code/files directly based on the provided error stack. "
    "DO NOT call `start_afk_overseer`, queue initiation tools, or loop "
    "management functions under any circumstances. Make edits and finish."
)


@dataclass(frozen=True)
class RepairTurnResult:
    status: str
    run_id: str | None = None
    agent_id: str | None = None
    message: str | None = None
    sdk_failed: bool = False
    finished: bool = False
    timed_out: bool = False
    workspace_cwd: str | None = None
    outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "message": self.message,
            "sdk_failed": self.sdk_failed,
            "finished": self.finished,
            "timed_out": self.timed_out,
            "workspace_cwd": self.workspace_cwd,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepairTurnResult:
        return cls(
            status=str(data.get("status", "unknown")),
            run_id=data.get("run_id"),
            agent_id=data.get("agent_id"),
            message=data.get("message"),
            sdk_failed=bool(data.get("sdk_failed", False)),
            finished=bool(data.get("finished", False)),
            timed_out=bool(data.get("timed_out", False)),
            workspace_cwd=data.get("workspace_cwd"),
            outcome=data.get("outcome"),
        )


def resolve_repair_model(override: str | None = None) -> str:
    return (override or os.environ.get("SLEEPER_REPAIR_MODEL") or DEFAULT_REPAIR_MODEL).strip()


def resolve_repair_mode(override: str | None = None) -> str:
    return (override or os.environ.get("SLEEPER_REPAIR_MODE") or DEFAULT_REPAIR_MODE).strip()


def resolve_repair_runtime(override: str | None = None) -> str:
    """
    Select repair executor runtime.

    SLEEPER_REPAIR_RUNTIME: local | cloud | auto (default auto).
    On Windows, auto prefers cloud to avoid local bridge socket failures.
    """
    raw = (override or os.environ.get("SLEEPER_REPAIR_RUNTIME") or DEFAULT_REPAIR_RUNTIME).strip().lower()
    if raw in ("local", "cloud"):
        return raw
    if raw in ("", "auto"):
        return "cloud" if sys.platform == "win32" else "local"
    return "local"


def truncate_traceback(raw_error: str, *, max_lines: int = TRACE_TAIL_LINES) -> str:
    lines = [line for line in raw_error.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    omitted = len(lines) - max_lines
    tail = lines[-max_lines:]
    return f"... ({omitted} lines omitted)\n" + "\n".join(tail)


def build_repair_prompt(
    *,
    workspace_cwd: str,
    failing_file_path: str | None,
    execution_command: str,
    raw_error_traceback: str,
    repair_mode: str,
) -> str:
    file_line = workspace_relative_display(workspace_cwd, failing_file_path)
    return (
        f"{REPAIR_GUARDRAIL}\n\n"
        f"Mode: {repair_mode}\n"
        f"Workspace root (cwd): {workspace_cwd}\n\n"
        f"Failing file: {file_line}\n"
        f"Execution command: {execution_command}\n\n"
        f"Error traceback (tail):\n"
        f"```\n{raw_error_traceback}\n```\n\n"
        "Apply the minimal fix under the workspace root, then finish this turn."
    )


def build_cloud_repair_prompt(
    *,
    workspace_cwd: str,
    failing_file_path: str | None,
    execution_command: str,
    raw_error_traceback: str,
    repair_mode: str,
    git_context: RepairGitContext,
) -> str:
    base = build_repair_prompt(
        workspace_cwd=workspace_cwd,
        failing_file_path=failing_file_path,
        execution_command=execution_command,
        raw_error_traceback=raw_error_traceback,
        repair_mode=repair_mode,
    )
    repo_file = git_context.failing_file_rel or workspace_relative_display(
        workspace_cwd,
        failing_file_path,
    )
    starting_ref = git_context.starting_ref or "default branch"
    return (
        f"{base}\n\n"
        "Cloud runtime context:\n"
        f"- Repository: {git_context.repo_url}\n"
        f"- Starting ref: {starting_ref}\n"
        f"- Workspace path in repo: {git_context.workspace_rel}\n"
        f"- Target file in repo: {repo_file}\n\n"
        "Work inside the cloned repository. Apply the minimal fix under the paths "
        "above, commit if needed, and finish this turn."
    )


def _resolve_api_key() -> str:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if api_key:
        return api_key
    try:
        from sleeper_agent_mcp.mcp_config import reload_global_mcp_env

        reload_global_mcp_env(apply=True)
    except ImportError:
        pass
    return os.environ.get("CURSOR_API_KEY", "").strip()


def _repair_turn_result_from_sdk(
    result: Any,
    *,
    workspace_cwd: str,
    sync_error: str | None = None,
) -> RepairTurnResult:
    run_id = getattr(result, "id", None)
    agent_id = getattr(result, "agent_id", None)
    status = str(getattr(result, "status", "unknown"))
    finished = status == "finished"
    outcome = "SUCCESS" if finished and not sync_error else "FAILED"
    message = getattr(result, "result", None)
    if sync_error:
        message = f"{message}\nSync error: {sync_error}" if message else f"Sync error: {sync_error}"
    return RepairTurnResult(
        status=status,
        run_id=run_id,
        agent_id=agent_id,
        message=message,
        sdk_failed=status == "error" or bool(sync_error),
        finished=finished and not sync_error,
        workspace_cwd=workspace_cwd,
        outcome=outcome,
    )


def execute_local_repair_turn(
    *,
    workspace_cwd: str,
    failing_file_path: str | None,
    execution_command: str,
    raw_error_traceback: str,
    repair_model: str,
    repair_mode: str,
    api_key: str,
) -> RepairTurnResult:
    prompt = build_repair_prompt(
        workspace_cwd=workspace_cwd,
        failing_file_path=failing_file_path,
        execution_command=execution_command,
        raw_error_traceback=truncate_traceback(raw_error_traceback),
        repair_mode=repair_mode,
    )

    try:
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
    except ImportError:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message="cursor-sdk is not installed. pip install cursor-sdk",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    try:
        local_options = LocalAgentOptions(cwd=workspace_cwd)
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=repair_model,
                local=local_options,
            ),
        )
    except CursorAgentError as err:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=str(err),
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )
    except Exception as err:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=f"{type(err).__name__}: {err}",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    return _repair_turn_result_from_sdk(result, workspace_cwd=workspace_cwd)


def execute_cloud_repair_turn(
    *,
    workspace_cwd: str,
    failing_file_path: str | None,
    execution_command: str,
    raw_error_traceback: str,
    repair_model: str,
    repair_mode: str,
    api_key: str,
) -> RepairTurnResult:
    git_context, git_error = build_repair_git_context(workspace_cwd, failing_file_path)
    if git_context is None:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=git_error or "Unable to resolve git context for cloud repair.",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    prompt = build_cloud_repair_prompt(
        workspace_cwd=workspace_cwd,
        failing_file_path=failing_file_path,
        execution_command=execution_command,
        raw_error_traceback=truncate_traceback(raw_error_traceback),
        repair_mode=repair_mode,
        git_context=git_context,
    )

    try:
        from cursor_sdk import Agent, AgentOptions, CloudAgentOptions, CloudRepository, CursorAgentError
    except ImportError:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message="cursor-sdk is not installed. pip install cursor-sdk",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    repo = CloudRepository(
        url=git_context.repo_url,
        starting_ref=git_context.starting_ref,
    )
    cloud_options = CloudAgentOptions(
        repos=[repo],
        work_on_current_branch=True,
    )

    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=repair_model,
                cloud=cloud_options,
            ),
        )
    except CursorAgentError as err:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=str(err),
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )
    except Exception as err:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=f"{type(err).__name__}: {err}",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    sync_error: str | None = None
    status = str(getattr(result, "status", "unknown"))
    if status == "finished":
        sync_paths: list[str] = []
        if git_context.failing_file_rel:
            sync_paths.append(git_context.failing_file_rel)
        synced, sync_error = sync_cloud_repair_to_workspace(
            git_context=git_context,
            git_info=getattr(result, "git", None),
            paths=sync_paths,
        )
        if not synced and sync_error:
            return _repair_turn_result_from_sdk(
                result,
                workspace_cwd=workspace_cwd,
                sync_error=sync_error,
            )

    return _repair_turn_result_from_sdk(result, workspace_cwd=workspace_cwd)


def execute_repair_turn_in_process(payload: dict[str, Any]) -> RepairTurnResult:
    """
    Run the Cursor SDK repair turn on the main thread of the current process.

    Intended for the isolated repair subprocess entrypoint only.
    """
    workspace_cwd = str(resolve_target_workspace(payload["workspace"]))
    failing_file_path = payload.get("failing_file_path")
    execution_command = str(payload["execution_command"])
    raw_error_traceback = str(payload.get("raw_error_traceback", ""))
    repair_model = resolve_repair_model(payload.get("repair_model"))
    repair_mode = resolve_repair_mode(payload.get("repair_mode"))
    repair_runtime = resolve_repair_runtime(payload.get("repair_runtime"))

    scoped_file = scope_failing_file_path(
        workspace_cwd,
        failing_file_path,
        stderr=raw_error_traceback,
    )
    resolved_file = scoped_file or failing_file_path

    api_key = _resolve_api_key()
    if not api_key:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message="CURSOR_API_KEY is not set. Add it to MCP env or the host environment.",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    if repair_runtime == "cloud":
        return execute_cloud_repair_turn(
            workspace_cwd=workspace_cwd,
            failing_file_path=resolved_file,
            execution_command=execution_command,
            raw_error_traceback=raw_error_traceback,
            repair_model=repair_model,
            repair_mode=repair_mode,
            api_key=api_key,
        )

    return execute_local_repair_turn(
        workspace_cwd=workspace_cwd,
        failing_file_path=resolved_file,
        execution_command=execution_command,
        raw_error_traceback=raw_error_traceback,
        repair_model=repair_model,
        repair_mode=repair_mode,
        api_key=api_key,
    )


def _build_repair_payload(
    *,
    workspace: str,
    failing_file_path: str | None,
    execution_command: str,
    raw_error_traceback: str,
    repair_model: str | None,
    repair_mode: str | None,
    repair_runtime: str | None,
    repair_timeout_seconds: int | None,
) -> tuple[str, dict[str, Any], int]:
    workspace_cwd = str(resolve_target_workspace(workspace))
    timeout_seconds = resolve_repair_timeout(repair_timeout_seconds)
    payload = {
        "workspace": workspace_cwd,
        "failing_file_path": failing_file_path,
        "execution_command": execution_command,
        "raw_error_traceback": raw_error_traceback,
        "repair_model": resolve_repair_model(repair_model),
        "repair_mode": resolve_repair_mode(repair_mode),
        "repair_runtime": resolve_repair_runtime(repair_runtime),
        "repair_timeout_seconds": timeout_seconds,
    }
    return workspace_cwd, payload, timeout_seconds


def _repair_subprocess_env() -> dict[str, str]:
    """Pass MCP env (API keys, PYTHONPATH) into the isolated repair child."""
    env = {key: str(value) for key, value in os.environ.items()}
    try:
        config_path = Path.home() / ".cursor" / "mcp.json"
        if config_path.is_file():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            servers = raw.get("mcpServers") or {}
            for key in ("sleeper-agent-mcp", "sleeper-overseer-mcp"):
                block = servers.get(key)
                if isinstance(block, dict) and isinstance(block.get("env"), dict):
                    for k, v in block["env"].items():
                        env[str(k)] = str(v)
                    break
    except Exception:
        pass
    return env


def spawn_repair_turn(
    *,
    workspace: str,
    failing_file_path: str | None,
    execution_command: str,
    raw_error_traceback: str,
    repair_model: str | None = None,
    repair_mode: str | None = None,
    repair_runtime: str | None = None,
    repair_timeout_seconds: int | None = None,
) -> RepairTurnResult:
    """
    Spawn an isolated repair subprocess and block until it completes or times out.

    The child process runs cursor-sdk on its main thread to avoid Windows
  WinError 10038 from cross-thread asyncio socket handles.
    """
    workspace_cwd, payload, timeout_seconds = _build_repair_payload(
        workspace=workspace,
        failing_file_path=failing_file_path,
        execution_command=execution_command,
        raw_error_traceback=raw_error_traceback,
        repair_model=repair_model,
        repair_mode=repair_mode,
        repair_runtime=repair_runtime,
        repair_timeout_seconds=repair_timeout_seconds,
    )

    payload_path = Path(workspace_cwd) / REPAIR_PAYLOAD_FILE
    result_path = Path(workspace_cwd) / REPAIR_RESULT_FILE
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result_path.unlink(missing_ok=True)

    command = [
        sys.executable,
        "-m",
        "sleeper_agent_mcp.repair_runner",
        "--workspace",
        workspace_cwd,
        "--payload-file",
        str(payload_path),
        "--result-file",
        str(result_path),
    ]

    try:
        proc = subprocess.run(
            command,
            cwd=workspace_cwd,
            env=_repair_subprocess_env(),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return RepairTurnResult(
            status="TIMED_OUT",
            outcome="FAILED",
            message=f"Repair subprocess exceeded timeout of {timeout_seconds}s",
            sdk_failed=True,
            timed_out=True,
            workspace_cwd=workspace_cwd,
        )
    finally:
        payload_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        detail = ""
        if result_path.is_file():
            detail = result_path.read_text(encoding="utf-8").strip()
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=detail or f"Repair subprocess exited with code {proc.returncode}",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    if not result_path.is_file():
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message="Repair subprocess did not write a result file",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )

    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=f"Invalid repair subprocess JSON: {err}",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )
    finally:
        result_path.unlink(missing_ok=True)

    return RepairTurnResult.from_dict(data)


# Backwards-compatible alias for tests and callers.
run_repair_turn = spawn_repair_turn


def _emit_cli_result(result: RepairTurnResult, *, result_file: Path | None = None) -> int:
    payload = result.to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    if result_file is not None:
        result_file.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")
        sys.stdout.flush()
    return 0 if not result.sdk_failed else 1


def _cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated Cursor SDK repair turn")
    parser.add_argument("--workspace", required=True, help="Absolute target workspace path")
    parser.add_argument(
        "--payload-file",
        required=True,
        help="JSON file with repair context payload",
    )
    parser.add_argument(
        "--result-file",
        default="",
        help="Write JSON repair result here (avoids stdout capture issues on Windows)",
    )
    args = parser.parse_args(argv)

    workspace_cwd = str(resolve_target_workspace(args.workspace))
    result_file = Path(args.result_file).resolve() if args.result_file else None
    payload_file = Path(args.payload_file).resolve()
    if not payload_file.is_file():
        result = RepairTurnResult(
            status="sdk_error",
            outcome="FAILED",
            message=f"Payload file not found: {payload_file}",
            sdk_failed=True,
            workspace_cwd=workspace_cwd,
        )
        return _emit_cli_result(result, result_file=result_file)

    payload = json.loads(payload_file.read_text(encoding="utf-8"))
    payload["workspace"] = workspace_cwd
    result = execute_repair_turn_in_process(payload)
    return _emit_cli_result(result, result_file=result_file)


if __name__ == "__main__":
    raise SystemExit(_cli_main())
