"""Workspace path scoping tests."""

from pathlib import Path

import pytest

from sleeper_agent_mcp.workspace_scope import (
    WorkspaceScopeError,
    resolve_target_workspace,
    scope_failing_file_path,
    workspace_relative_display,
)


def test_resolve_target_workspace_absolute(tmp_path):
    ws = resolve_target_workspace(tmp_path)
    assert ws.is_absolute()
    assert ws == tmp_path.resolve()


def test_resolve_target_workspace_rejects_missing(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(WorkspaceScopeError):
        resolve_target_workspace(missing)


def test_scope_maps_solari_guest_path(tmp_path):
    target = tmp_path / "demo" / "broken.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")

    scoped = scope_failing_file_path(
        tmp_path,
        "/workspace/demo/broken.py",
    )
    assert scoped == str(target.resolve())


def test_workspace_relative_display(tmp_path):
    target = tmp_path / "demo" / "broken.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")

    display = workspace_relative_display(tmp_path, str(target))
    assert display.replace("\\", "/") == "demo/broken.py"
