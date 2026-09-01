"""Unit tests for Solari command routing (no API calls)."""

from __future__ import annotations

from types import SimpleNamespace

from sleeper_agent_mcp.backends.solari_runner import (
    _format_run_code_result,
    _is_python_inline,
    _resolve_sandbox_command,
    _should_skip_workspace_sync,
)


def test_python_inline_detection():
    assert _is_python_inline("python", ["-c", "print(1)"])
    assert _is_python_inline("python3", ["-c", "print(1)"])
    assert not _is_python_inline("python", ["script.py"])


def test_skip_workspace_sync_for_inline():
    assert _should_skip_workspace_sync("python", ["-c", "print(1)"])
    assert not _should_skip_workspace_sync("pytest", ["-q"])


def test_resolve_python_uses_shell_and_python3():
    cmd, args = _resolve_sandbox_command("python", ["-c", "print(42)"])
    assert cmd == "sh"
    assert args == ["-c", "python3 -c 'print(42)'"]


def test_resolve_pytest_uses_python3_module():
    cmd, args = _resolve_sandbox_command("pytest", ["-q", "tests"])
    assert cmd == "sh"
    assert "python3 -m pytest" in args[1]
    assert "-q" in args[1]


def test_format_run_code_result_success():
    result = SimpleNamespace(
        results=[
            SimpleNamespace(type="stdout", text="42\n"),
        ],
        error=None,
    )
    code, stdout, stderr = _format_run_code_result(result)
    assert code == 0
    assert "42" in stdout
    assert stderr == ""


def test_format_run_code_result_error():
    result = SimpleNamespace(
        results=[],
        error={"message": "SyntaxError"},
    )
    code, stdout, stderr = _format_run_code_result(result)
    assert code == 1
    assert "SyntaxError" in stderr
