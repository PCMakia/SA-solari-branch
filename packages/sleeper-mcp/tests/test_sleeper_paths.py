"""Tests for SLEEPER_HOME vs task workspace resolution."""

from __future__ import annotations

import pytest

from sleeper_agent_mcp.sleeper_paths import resolve_task_workspace, sleeper_home
from sleeper_agent_mcp.workspace_scope import WorkspaceScopeError


def test_sleeper_home_detects_repo():
    home = sleeper_home()
    assert (home / "packages" / "sleeper-mcp").is_dir()


def test_resolve_task_workspace_explicit(tmp_path):
    assert resolve_task_workspace(tmp_path) == tmp_path.resolve()


def test_resolve_task_workspace_requires_open_project(monkeypatch):
    monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CURSOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("VSCODE_WORKSPACE_FOLDER", raising=False)
    monkeypatch.delenv("PWD", raising=False)
    monkeypatch.delenv("INIT_CWD", raising=False)
    with pytest.raises(WorkspaceScopeError, match="No task workspace"):
        resolve_task_workspace(None)


def test_resolve_task_workspace_uses_cursor_project_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    assert resolve_task_workspace(None) == tmp_path.resolve()
