"""Install home vs per-run task workspace resolution.

Sleeper is installed once (clone of Solari / sleeper-agent). User projects never
need the Sleeper source tree. Each ``start_afk_overseer`` / Sleeper-call run
targets the currently open project folder as ``workspace``.
"""

from __future__ import annotations

import os
from pathlib import Path

from sleeper_agent_mcp.state import resolve_path
from sleeper_agent_mcp.workspace_scope import WorkspaceScopeError, resolve_target_workspace


def detect_sleeper_home() -> Path:
    """
    Locate the Sleeper/Solari install root (contains packages/sleeper-mcp).

    Order: ``SLEEPER_HOME`` → walk up from this package → legacy ``SLEEPER_WORKSPACE``
    only when that path looks like an install (has packages/sleeper-mcp).
    """
    env_home = os.environ.get("SLEEPER_HOME", "").strip()
    if env_home:
        return resolve_path(env_home)

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "sleeper-mcp").is_dir():
            return parent

    legacy = os.environ.get("SLEEPER_WORKSPACE", "").strip()
    if legacy:
        candidate = resolve_path(legacy)
        if (candidate / "packages" / "sleeper-mcp").is_dir():
            return candidate

    # packages/sleeper-mcp/sleeper_agent_mcp/sleeper_paths.py → repo root
    return here.parents[2]


def sleeper_home() -> Path:
    return detect_sleeper_home()


def is_sleeper_install_path(path: str | Path) -> bool:
    """True if path is the Sleeper install (or packages/sleeper-mcp), not a user app."""
    try:
        resolved = resolve_path(path)
    except (OSError, ValueError):
        return False
    home = sleeper_home()
    try:
        resolved.relative_to(home)
    except ValueError:
        return False
    # Exact install root or known package dirs under it count as install, not a task ws.
    if resolved == home:
        return True
    if resolved in {
        home / "packages" / "sleeper-mcp",
        home / "packages" / "sleeper-daemon",
        home / "apps" / "overseer-dashboard",
    }:
        return True
    # Nested canary_* under the install IS a valid demo workspace.
    name = resolved.name.lower()
    if name.startswith("canary"):
        return False
    # Other paths under home (docs/, apps/ other) — treat as install-adjacent; allow
    # only if not the mcp cwd.
    if resolved == home / "packages" / "sleeper-mcp":
        return True
    return False


def _candidate_open_project_dirs() -> list[Path]:
    """Best-effort hints for the folder the user currently has open in Cursor."""
    keys = (
        "CURSOR_PROJECT_DIR",
        "CURSOR_WORKSPACE_ROOT",
        "VSCODE_WORKSPACE_FOLDER",
        "PWD",
        "INIT_CWD",
    )
    out: list[Path] = []
    seen: set[str] = set()
    for key in keys:
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        try:
            path = resolve_path(raw)
        except (OSError, ValueError):
            continue
        if not path.is_dir():
            continue
        key_s = str(path)
        if key_s in seen:
            continue
        seen.add(key_s)
        out.append(path)
    return out


def resolve_task_workspace(workspace: str | Path | None = None) -> Path:
    """
    Resolve the **user project** directory for this overseer run.

    Prefer the explicit ``workspace`` argument (agent / Sleeper-call must pass the
    open project). Never silently fall back to the Sleeper install root or the
    MCP server ``cwd`` (packages/sleeper-mcp).
    """
    if workspace is not None and str(workspace).strip():
        return resolve_target_workspace(workspace)

    for candidate in _candidate_open_project_dirs():
        # Skip MCP process cwd / install package dirs used as false defaults.
        if candidate == sleeper_home() / "packages" / "sleeper-mcp":
            continue
        if candidate == sleeper_home() / "packages" / "sleeper-daemon":
            continue
        try:
            return resolve_target_workspace(candidate)
        except WorkspaceScopeError:
            continue

    raise WorkspaceScopeError(
        "No task workspace provided. Pass workspace=<absolute path of the open "
        "project> to start_afk_overseer (or set it in the Sleeper-call payload). "
        "Sleeper is installed globally; each run targets the project you have open, "
        "not the Solari/Sleeper clone."
    )
