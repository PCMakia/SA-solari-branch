"""Git metadata and sync helpers for cloud-runtime overseer repairs."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RepairGitContext:
    git_root: Path
    repo_url: str
    starting_ref: str | None
    workspace_rel: str
    failing_file_rel: str | None


def find_git_root(path: str | Path) -> Path | None:
    """Return the git repository root containing `path`, or None."""
    start = Path(path).resolve()
    if not start.is_dir():
        start = start.parent
    current = start
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def resolve_repair_repo_url(workspace: str | Path) -> str:
    """
    Resolve the git remote URL for cloud repair.

  Priority: SLEEPER_REPAIR_REPO env, then `origin` on the workspace git root.
    """
    override = os.environ.get("SLEEPER_REPAIR_REPO", "").strip()
    if override:
        return override

    git_root = find_git_root(workspace)
    if git_root is None:
        return ""

    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=git_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def resolve_starting_ref(git_root: Path) -> str | None:
    """Current branch name, or commit SHA when detached."""
    try:
        branch_proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=git_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if branch_proc.returncode == 0:
            branch = branch_proc.stdout.strip()
            if branch and branch != "HEAD":
                return branch

        commit_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if commit_proc.returncode == 0:
            commit = commit_proc.stdout.strip()
            return commit or None
    except OSError:
        return None
    return None


def path_relative_to_git_root(git_root: Path, file_path: str | Path | None) -> str | None:
    if not file_path:
        return None
    resolved = Path(file_path).resolve()
    try:
        return str(resolved.relative_to(git_root)).replace("\\", "/")
    except ValueError:
        return None


def normalize_repo_url(repo_url: str) -> str:
    stripped = repo_url.strip()
    if stripped.startswith(("http://", "https://")):
        return stripped
    return f"https://{stripped.lstrip('/')}"


def build_repair_git_context(
    workspace_cwd: str | Path,
    failing_file_path: str | None,
) -> tuple[RepairGitContext | None, str | None]:
    """Build git metadata for a cloud repair turn."""
    repo_url = resolve_repair_repo_url(workspace_cwd)
    if not repo_url:
        return None, (
            "Cloud repair requires a repository URL. Set SLEEPER_REPAIR_REPO or "
            "configure `git remote origin` on the workspace repository."
        )

    git_root = find_git_root(workspace_cwd)
    if git_root is None:
        return None, "Cloud repair requires the workspace to live inside a git repository."

    workspace = Path(workspace_cwd).resolve()
    try:
        workspace_rel = str(workspace.relative_to(git_root)).replace("\\", "/")
    except ValueError:
        workspace_rel = "."

    failing_file_rel = path_relative_to_git_root(git_root, failing_file_path)
    return (
        RepairGitContext(
            git_root=git_root,
            repo_url=repo_url,
            starting_ref=resolve_starting_ref(git_root),
            workspace_rel=workspace_rel,
            failing_file_rel=failing_file_rel,
        ),
        None,
    )


def sync_cloud_repair_to_workspace(
    *,
    git_context: RepairGitContext,
    git_info: Any,
    paths: list[str],
) -> tuple[bool, str | None]:
    """
    Pull cloud-agent file changes into the local git checkout.

    Uses branch metadata from the SDK run result when available.
    """
    branches = getattr(git_info, "branches", None) or ()
    if not branches:
        return False, "Cloud repair finished without git branch metadata to sync."

    branch_info = branches[0]
    branch = getattr(branch_info, "branch", None) or ""
    repo_url = normalize_repo_url(
        getattr(branch_info, "repo_url", None) or git_context.repo_url
    )
    if not branch:
        return False, "Cloud repair returned git metadata without a branch name."

    rel_paths = [path.replace("\\", "/") for path in paths if path]
    if not rel_paths and git_context.failing_file_rel:
        rel_paths = [git_context.failing_file_rel]

    fetch_ref = f"refs/heads/{branch}"
    try:
        fetch_proc = subprocess.run(
            ["git", "fetch", repo_url, f"{branch}:{fetch_ref}"],
            cwd=git_context.git_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if fetch_proc.returncode != 0:
            return False, (fetch_proc.stderr or fetch_proc.stdout or "git fetch failed").strip()

        if rel_paths:
            checkout_proc = subprocess.run(
                ["git", "checkout", fetch_ref, "--", *rel_paths],
                cwd=git_context.git_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if checkout_proc.returncode != 0:
                return (
                    False,
                    (checkout_proc.stderr or checkout_proc.stdout or "git checkout failed").strip(),
                )
        else:
            merge_proc = subprocess.run(
                ["git", "merge", "--ff-only", fetch_ref],
                cwd=git_context.git_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if merge_proc.returncode != 0:
                return False, (merge_proc.stderr or merge_proc.stdout or "git merge failed").strip()
    except OSError as err:
        return False, f"{type(err).__name__}: {err}"

    return True, None
