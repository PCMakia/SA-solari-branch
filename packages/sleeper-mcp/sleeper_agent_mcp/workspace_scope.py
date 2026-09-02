"""Strict workspace path resolution and scoping for overseer operations."""

from __future__ import annotations

from pathlib import Path

from sleeper_agent_mcp.state import resolve_path


class WorkspaceScopeError(ValueError):
    """Raised when a path cannot be scoped to the target workspace."""


def resolve_target_workspace(workspace: str | Path) -> Path:
    """
    Resolve the target workspace to an absolute, normalized directory path.

    All overseer file operations and SDK local-agent cwd must use this value.
    """
    path = resolve_path(workspace)
    if not path.is_dir():
        raise WorkspaceScopeError(f"Target workspace is not a directory: {path}")
    return path


def scope_failing_file_path(
    workspace: str | Path,
    failing_file_path: str | None,
    *,
    stderr: str | None = None,
) -> str | None:
    """
    Return an absolute path under the target workspace when possible.

    Host paths outside the workspace are returned as workspace-relative hints
    when the file exists under the workspace root.
    """
    root = resolve_target_workspace(workspace)

    if failing_file_path:
        candidate = _resolve_under_workspace(root, failing_file_path)
        if candidate is not None:
            return str(candidate)

    if stderr:
        from sleeper_agent_mcp.execution.validate import infer_failing_file_path

        inferred = infer_failing_file_path(root, [], stderr)
        if inferred:
            candidate = _resolve_under_workspace(root, inferred)
            if candidate is not None:
                return str(candidate)

    return None


def workspace_relative_display(workspace: str | Path, file_path: str | None) -> str:
    """Human/SDK-friendly path for repair prompts (prefer paths relative to workspace)."""
    if not file_path:
        return "(unknown — inspect traceback)"
    root = resolve_target_workspace(workspace)
    resolved = resolve_path(file_path)
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        under = _resolve_under_workspace(root, file_path)
        if under is not None:
            return str(under.relative_to(root))
        return str(resolved)


def _resolve_under_workspace(root: Path, file_path: str) -> Path | None:
    resolved = resolve_path(file_path)

    # Solari guest paths like /workspace/demo/foo.py → map to host workspace root.
    normalized = file_path.replace("\\", "/")
    if normalized.startswith("/workspace/"):
        suffix = normalized.removeprefix("/workspace/").lstrip("/")
        candidate = root / suffix
        if candidate.is_file():
            return candidate.resolve()

    if resolved.is_file():
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            pass

    # Try basename match under workspace (last resort).
    matches = list(root.rglob(Path(file_path).name))
    if len(matches) == 1 and matches[0].is_file():
        return matches[0].resolve()

    return None
