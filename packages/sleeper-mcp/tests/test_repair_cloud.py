"""Cloud-runtime repair path tests."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from sleeper_agent_mcp.repair_git import (
    build_repair_git_context,
    find_git_root,
    resolve_repair_repo_url,
    resolve_starting_ref,
    sync_cloud_repair_to_workspace,
)
from sleeper_agent_mcp.repair_runner import (
    RepairTurnResult,
    build_cloud_repair_prompt,
    execute_cloud_repair_turn,
    execute_repair_turn_in_process,
    resolve_repair_runtime,
)


def _git(cwd, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(tmp_path, *, remote_url: str | None = None) -> str:
    ws = tmp_path / "workspace"
    ws.mkdir()
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (ws / "broken.py").write_text("print('x'\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    if remote_url:
        _git(tmp_path, "remote", "add", "origin", remote_url)
    return str(ws.resolve())


def test_resolve_repair_runtime_auto_prefers_cloud_on_windows(monkeypatch):
    monkeypatch.delenv("SLEEPER_REPAIR_RUNTIME", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert resolve_repair_runtime() == "cloud"


def test_resolve_repair_runtime_auto_prefers_local_elsewhere(monkeypatch):
    monkeypatch.delenv("SLEEPER_REPAIR_RUNTIME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert resolve_repair_runtime() == "local"


def test_resolve_repair_runtime_explicit_override(monkeypatch):
    monkeypatch.setenv("SLEEPER_REPAIR_RUNTIME", "cloud")
    assert resolve_repair_runtime("local") == "local"


def test_resolve_repair_repo_url_prefers_env(tmp_path, monkeypatch):
    ws = _init_repo(tmp_path, remote_url="https://example.com/origin.git")
    monkeypatch.setenv("SLEEPER_REPAIR_REPO", "https://example.com/override.git")
    assert resolve_repair_repo_url(ws) == "https://example.com/override.git"


def test_resolve_repair_repo_url_from_origin(tmp_path, monkeypatch):
    ws = _init_repo(tmp_path, remote_url="https://example.com/origin.git")
    monkeypatch.delenv("SLEEPER_REPAIR_REPO", raising=False)
    assert resolve_repair_repo_url(ws) == "https://example.com/origin.git"


def test_build_repair_git_context(tmp_path, monkeypatch):
    ws = _init_repo(tmp_path, remote_url="https://example.com/repo.git")
    monkeypatch.delenv("SLEEPER_REPAIR_REPO", raising=False)
    failing = str((tmp_path / "workspace" / "broken.py").resolve())

    context, error = build_repair_git_context(ws, failing)
    assert error is None
    assert context is not None
    assert context.repo_url == "https://example.com/repo.git"
    assert context.workspace_rel == "workspace"
    assert context.failing_file_rel == "workspace/broken.py"
    assert find_git_root(ws) == tmp_path.resolve()


def test_build_cloud_repair_prompt_includes_repo_context(tmp_path, monkeypatch):
    ws = _init_repo(tmp_path, remote_url="https://example.com/repo.git")
    monkeypatch.delenv("SLEEPER_REPAIR_REPO", raising=False)
    failing = str((tmp_path / "workspace" / "broken.py").resolve())
    context, _ = build_repair_git_context(ws, failing)
    assert context is not None

    prompt = build_cloud_repair_prompt(
        workspace_cwd=ws,
        failing_file_path=failing,
        execution_command="python broken.py",
        raw_error_traceback="SyntaxError",
        repair_mode="agent",
        git_context=context,
    )
    assert "Cloud runtime context" in prompt
    assert "https://example.com/repo.git" in prompt
    assert "workspace/broken.py" in prompt


def test_execute_cloud_repair_turn_missing_repo(tmp_path, monkeypatch):
    ws = str(tmp_path.resolve())
    monkeypatch.delenv("SLEEPER_REPAIR_REPO", raising=False)

    result = execute_cloud_repair_turn(
        workspace_cwd=ws,
        failing_file_path=None,
        execution_command="python x.py",
        raw_error_traceback="boom",
        repair_model="auto",
        repair_mode="agent",
        api_key="test-key",
    )
    assert result.outcome == "FAILED"
    assert result.sdk_failed is True
    assert "SLEEPER_REPAIR_REPO" in (result.message or "")


def test_execute_repair_turn_dispatches_cloud(tmp_path, monkeypatch):
    ws = str(tmp_path.resolve())
    monkeypatch.setattr(
        "sleeper_agent_mcp.repair_runner.execute_cloud_repair_turn",
        lambda **_kwargs: RepairTurnResult(
            status="finished",
            outcome="SUCCESS",
            finished=True,
            workspace_cwd=ws,
        ),
    )
    monkeypatch.setattr("sleeper_agent_mcp.repair_runner._resolve_api_key", lambda: "key")

    result = execute_repair_turn_in_process(
        {
            "workspace": ws,
            "execution_command": "python x.py",
            "raw_error_traceback": "err",
            "repair_runtime": "cloud",
        }
    )
    assert result.outcome == "SUCCESS"


def test_sync_cloud_repair_to_workspace_checkout(tmp_path, monkeypatch):
    ws = _init_repo(tmp_path, remote_url="https://example.com/repo.git")
    monkeypatch.delenv("SLEEPER_REPAIR_REPO", raising=False)
    failing = str((tmp_path / "workspace" / "broken.py").resolve())
    context, _ = build_repair_git_context(ws, failing)
    assert context is not None

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("sleeper_agent_mcp.repair_git.subprocess.run", fake_run)
    git_info = SimpleNamespace(
        branches=[SimpleNamespace(branch="repair-branch", repo_url=context.repo_url)]
    )

    ok, error = sync_cloud_repair_to_workspace(
        git_context=context,
        git_info=git_info,
        paths=["workspace/broken.py"],
    )
    assert ok is True
    assert error is None
    assert calls[0][:2] == ["git", "fetch"]
    assert calls[1][:4] == ["git", "checkout", "refs/heads/repair-branch", "--"]
