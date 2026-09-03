"""Spawn / reuse the local Sleeper daemon watch process for a workspace."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


WATCH_PID_NAME = "watch.pid"
WATCH_LOG_NAME = "watch.log"


def watch_pid_path(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    sleeper = root / ".sleeper"
    sleeper.mkdir(parents=True, exist_ok=True)
    return sleeper / WATCH_PID_NAME


def watch_log_path(workspace: str | Path) -> Path:
    return watch_pid_path(workspace).with_name(WATCH_LOG_NAME)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_watch_pid(workspace: str | Path) -> int | None:
    path = watch_pid_path(workspace)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _write_watch_pid(workspace: str | Path, pid: int) -> None:
    watch_pid_path(workspace).write_text(str(pid), encoding="utf-8")


def _default_window_title(workspace: str | Path) -> str:
    env = os.environ.get("SLEEPER_CURSOR_WINDOW_TITLE", "").strip()
    if env:
        return env
    # Prefer the IDE repo folder name (Solari), not a nested canary_test* dir.
    start = Path(workspace).expanduser().resolve()
    for candidate in [start, *start.parents]:
        if (candidate / "apps" / "overseer-dashboard").is_dir():
            return candidate.name
        if (candidate / ".git").exists():
            return candidate.name
    return "Cursor"


def _watch_command(workspace: str, window_title: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "sleeper_daemon.cli",
        "watch",
        "--workspace",
        workspace,
        "--window-title",
        window_title,
    ]


def ensure_sleeper_watch(
    workspace: str | Path,
    *,
    window_title: str | None = None,
) -> dict[str, Any]:
    """
    Ensure ``sleeper_daemon watch`` is running for ``workspace``.

    Safe to call from ``start_afk_overseer`` or an agent turn after Open IDE:
    if a live watch PID exists, returns without spawning another process.
    """
    ws = str(Path(workspace).expanduser().resolve())
    title = (window_title or _default_window_title(ws)).strip() or "Cursor"

    existing = _read_watch_pid(ws)
    if existing and _pid_is_running(existing):
        return {
            "status": "ALREADY_RUNNING",
            "pid": existing,
            "workspace": ws,
            "window_title": title,
            "command": _watch_command(ws, title),
        }

    log_path = watch_log_path(ws)
    log_file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - inherited by child
    log_file.write(f"\n--- ensure_sleeper_watch {ws} ---\n")
    log_file.flush()

    cmd = _watch_command(ws, title)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000
        )

    env = os.environ.copy()
    # Prefer install packages on path (SLEEPER_HOME or sibling of this package).
    try:
        from sleeper_agent_mcp.sleeper_paths import sleeper_home

        home = sleeper_home()
        daemon_src = home / "packages" / "sleeper-daemon"
        mcp_src = home / "packages" / "sleeper-mcp"
    except Exception:  # noqa: BLE001
        daemon_src = Path(__file__).resolve().parents[2] / "sleeper-daemon"
        mcp_src = Path(__file__).resolve().parents[1]
    extras = [str(daemon_src), str(mcp_src)]
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [p for p in extras + ([existing_pp] if existing_pp else []) if p]
    )

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(daemon_src) if daemon_src.is_dir() else ws,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
            env=env,
        )
    except OSError as err:
        return {
            "status": "ERROR",
            "workspace": ws,
            "window_title": title,
            "error": str(err),
            "command": cmd,
            "log": str(log_path),
        }

    if proc.pid:
        _write_watch_pid(ws, int(proc.pid))

    return {
        "status": "STARTED",
        "pid": int(proc.pid or 0),
        "workspace": ws,
        "window_title": title,
        "command": cmd,
        "log": str(log_path),
    }
