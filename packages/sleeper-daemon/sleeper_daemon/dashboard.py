"""Overseer dashboard process lifecycle and browser surfacing."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

DEFAULT_DASHBOARD_URL = "http://localhost:3000"
HEALTH_PATH = "/api/health"
HEALTH_TIMEOUT_SECONDS = 1.0
STARTUP_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.5
FOCUS_RACE_DELAY_SECONDS = 0.8
PID_FILE_NAME = "dashboard.pid"
ALLOWED_DASHBOARD_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def dashboard_base_url() -> str:
    return os.environ.get("SLEEPER_DASHBOARD_URL", DEFAULT_DASHBOARD_URL).rstrip("/")


def dashboard_app_dir() -> Path:
    override = os.environ.get("SLEEPER_DASHBOARD_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    home = os.environ.get("SLEEPER_HOME", "").strip()
    if home:
        candidate = Path(home).expanduser().resolve() / "apps" / "overseer-dashboard"
        if candidate.is_dir():
            return candidate
    # packages/sleeper-daemon/sleeper_daemon/dashboard.py -> repo/apps/overseer-dashboard
    return (
        Path(__file__).resolve().parents[3] / "apps" / "overseer-dashboard"
    ).resolve()


def pid_file_path(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    sleeper = root / ".sleeper"
    sleeper.mkdir(parents=True, exist_ok=True)
    return sleeper / PID_FILE_NAME


def is_port_open(host: str = "127.0.0.1", port: int = 3000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def is_dashboard_healthy(base_url: str | None = None) -> bool:
    url = f"{(base_url or dashboard_base_url()).rstrip('/')}{HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            if not (200 <= int(response.status) < 300):
                return False
            body = response.read().decode("utf-8", errors="replace")
            return '"status"' in body and "ok" in body.lower()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


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


def _read_saved_pid(workspace: str | Path) -> int | None:
    path = pid_file_path(workspace)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _write_saved_pid(workspace: str | Path, pid: int) -> None:
    pid_file_path(workspace).write_text(str(pid), encoding="utf-8")


def dashboard_log_path(workspace: str | Path) -> Path:
    return pid_file_path(workspace).with_name("dashboard.log")


def _has_production_build(app_dir: Path) -> bool:
    """True only when `next build` produced a BUILD_ID (dev `.next` cache is not enough)."""
    return (app_dir / ".next" / "BUILD_ID").is_file()


def _choose_npm_command(app_dir: Path) -> list[str]:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    force_dev = os.environ.get("SLEEPER_DASHBOARD_FORCE_DEV", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not force_dev and _has_production_build(app_dir):
        return [npm, "run", "start"]
    return [npm, "run", "dev"]


def _tail_log(path: Path, *, max_chars: int = 1200) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _spawn_dashboard(app_dir: Path, workspace: str | Path) -> int:
    if not app_dir.is_dir():
        raise FileNotFoundError(f"Dashboard app directory not found: {app_dir}")
    command = _choose_npm_command(app_dir)
    log_path = dashboard_log_path(workspace)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Truncate prior run so early-exit diagnosis is clear.
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - kept open for child
    log_file.write(f"$ {' '.join(command)}  (cwd={app_dir})\n")
    log_file.flush()

    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW avoids the flashing console. Do not use DETACHED_PROCESS
        # with npm.cmd — that often exits immediately and leaves no Next.js server.
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000
        )

    env = os.environ.copy()
    env.setdefault("BROWSER", "none")  # next dev: don't open an extra browser tab
    env.setdefault("HOST", "127.0.0.1")

    proc = subprocess.Popen(
        command,
        cwd=str(app_dir),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=sys.platform != "win32",
        env=env,
    )
    if proc.pid:
        _write_saved_pid(workspace, proc.pid)

    # npm.cmd / next often fails in <1s when start is mis-chosen; surface that early.
    time.sleep(1.0)
    if proc.poll() is not None:
        try:
            log_file.flush()
        except OSError:
            pass
        snippet = _tail_log(log_path)
        raise RuntimeError(
            f"dashboard process exited immediately (code={proc.returncode}). "
            f"log={log_path}"
            + (f"\n---\n{snippet}\n---" if snippet else "")
        )
    return int(proc.pid or 0)


def ensure_dashboard_running(
    workspace: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> bool:
    """
    Ensure localhost:3000 is healthy. Spawn Next.js if needed.

    Returns True when healthy, False if startup timed out / failed.
    """
    def _log(message: str) -> None:
        if log:
            log(message)

    if is_dashboard_healthy():
        _log(f"dashboard healthy at {dashboard_base_url()}")
        return True

    port_busy = is_port_open("127.0.0.1", 3000)
    saved = _read_saved_pid(workspace)

    if port_busy:
        _log("port 3000 is in use; waiting for /api/health without spawning another Next.js")
    elif saved and _pid_is_running(saved):
        _log(f"dashboard pid {saved} still running; waiting for health")
    else:
        app_dir = dashboard_app_dir()
        try:
            command = _choose_npm_command(app_dir)
            _log(
                f"starting dashboard via `{' '.join(command)}` "
                f"(production_build={_has_production_build(app_dir)})"
            )
            pid = _spawn_dashboard(app_dir, workspace)
            _log(f"spawned dashboard pid={pid} in {app_dir}")
        except Exception as err:  # noqa: BLE001 - kickoff must not hard-fail
            _log(f"failed to spawn dashboard: {err}")
            return False

    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if is_dashboard_healthy():
            _log(f"dashboard ready at {dashboard_base_url()}")
            return True
        saved_now = _read_saved_pid(workspace)
        if saved_now and not _pid_is_running(saved_now) and not is_port_open("127.0.0.1", 3000):
            snippet = _tail_log(dashboard_log_path(workspace))
            _log(
                f"dashboard pid {saved_now} exited before becoming healthy"
                + (f"; log tail:\n{snippet}" if snippet else "")
            )
            return False
        time.sleep(POLL_INTERVAL_SECONDS)

    snippet = _tail_log(dashboard_log_path(workspace))
    _log(
        f"dashboard did not become healthy within {STARTUP_TIMEOUT_SECONDS:.0f}s; "
        "continuing without browser surface"
        + (f"\nlog: {dashboard_log_path(workspace)}\n{snippet}" if snippet else "")
    )
    return False


def build_dashboard_url(queue_id: str | None = None) -> str:
    """Build and validate a localhost dashboard URL (never accepts free-form prompts)."""
    base = dashboard_base_url()
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid dashboard URL scheme: {base!r}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_DASHBOARD_HOSTS:
        raise ValueError(
            f"Dashboard URL host must be localhost/127.0.0.1, got {host!r} from {base!r}"
        )
    if queue_id is not None:
        cleaned = str(queue_id).strip()
        if not cleaned or any(ch.isspace() for ch in cleaned) or len(cleaned) > 128:
            raise ValueError(f"Invalid queue_id for dashboard deep-link: {queue_id!r}")
        if any(ch in cleaned for ch in "<>\"'`"):
            raise ValueError(f"Invalid queue_id for dashboard deep-link: {queue_id!r}")
        return f"{base}/?queue_id={cleaned}"
    return f"{base}/"


def resolve_ide_workspace(task_workspace: str | Path | None = None) -> Path:
    """
    Folder the classic Cursor IDE should open — same idea as Agents "Open IDE".

    Prefer ``SLEEPER_CURSOR_WORKSPACE``, else walk up from the task workspace to a
    git root (so ``canary_test`` opens the Solari repo, not a blank window).
    """
    override = os.environ.get("SLEEPER_CURSOR_WORKSPACE", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    start = Path(task_workspace or ".").expanduser().resolve()
    best_git: Path | None = None
    for candidate in [start, *start.parents]:
        if (candidate / "apps" / "overseer-dashboard").is_dir() and (
            (candidate / ".git").exists() or (candidate / "packages").is_dir()
        ):
            return candidate
        if best_git is None and (candidate / ".git").exists():
            best_git = candidate
    if best_git is not None:
        return best_git
    return start


def _find_cursor_cli() -> str | None:
    override = os.environ.get("SLEEPER_CURSOR_CLI", "").strip()
    if override:
        return override
    from shutil import which

    if sys.platform == "win32":
        return which("cursor.cmd") or which("cursor")
    return which("cursor")


DASHBOARD_SURFACE_MARK = "__dashboard_surfaced__"


def cursor_ide_already_open_for_workspace(ide_workspace: str | Path) -> bool:
    """
    True when a Cursor window already shows this workspace (agent panel may be open).

    Re-running ``cursor -r --classic`` in that state collapses the Agent side panel.
    """
    from sleeper_daemon.windows import get_active_cursor_windows, is_cursor_window_title

    path = Path(ide_workspace).expanduser().resolve()
    needles = {path.name.lower()}
    # Also match common title forms: "file - Solari - Cursor"
    if path.name:
        needles.add(path.name.lower())
    for window in get_active_cursor_windows():
        title = window.title or ""
        if not is_cursor_window_title(title):
            continue
        lowered = title.lower()
        if any(needle and needle in lowered for needle in needles):
            return True
    return False


def ensure_cursor_ide_open(
    ide_workspace: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> bool:
    """
    Ensure a classic Cursor editor exists for ``ide_workspace``.

    If a Cursor window for that folder is already open (including with the Agent
    panel), do nothing — ``cursor --classic`` would close the agent panel.
    Only invoke the CLI when no matching IDE window is present.
    """
    path = Path(ide_workspace).expanduser().resolve()
    if not path.is_dir():
        if log:
            log(f"IDE workspace missing: {path}")
        return False

    if cursor_ide_already_open_for_workspace(path):
        if log:
            log(
                f"Cursor IDE already open for {path.name}; "
                "skipping Open IDE (--classic) to preserve Agent panel"
            )
        return True

    cursor_bin = _find_cursor_cli()
    if not cursor_bin:
        if log:
            log("cursor CLI not found; cannot Open IDE for workspace")
        return False

    # ``-r`` = reuse existing window; ``--classic`` = editor workbench (not Agents-only).
    cmd = [cursor_bin, "-r", "--classic", str(path)]
    if log:
        log(f"opening Cursor IDE for workspace: {path}")
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
        )
    except OSError as err:
        if log:
            log(f"failed to open Cursor IDE: {err}")
        return False
    time.sleep(0.6)
    return True


def _open_browser_editor_via_palette(url: str) -> None:
    """
    Open Cursor's in-IDE browser (Simple Browser → workbench.action.openBrowserEditor).

    Uses the Command Palette so we never launch Chrome/Edge.
    """
    import pyautogui
    import pyperclip

    pyautogui.FAILSAFE = False
    pyautogui.hotkey("ctrl", "shift", "p")
    time.sleep(0.35)
    # Cursor ships Simple Browser as a shim to openBrowserEditor.
    pyperclip.copy("Simple Browser: Show")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.45)
    pyperclip.copy(url)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.1)
    pyautogui.press("enter")


def open_dashboard_in_ide_browser(
    url: str,
    *,
    log: Callable[[str], None] | None = None,
) -> str:
    """
    Open ``url`` inside Cursor's browser editor.

    Returns the mode used: ``ide-palette``, ``external``, or ``pending``.
    """
    mode = os.environ.get("SLEEPER_DASHBOARD_SURFACE", "ide").strip().lower()
    if mode in {"external", "os", "chrome"}:
        if log:
            log(f"opening external browser {url}")
        webbrowser.open(url)
        return "external"

    try:
        _open_browser_editor_via_palette(url)
        if log:
            log(f"opened in-IDE browser (Simple Browser) {url}")
        return "ide-palette"
    except Exception as err:  # noqa: BLE001 - surfacing must not abort kickoff
        if log:
            log(f"in-IDE browser open failed ({err})")

    if os.environ.get("SLEEPER_DASHBOARD_EXTERNAL_BROWSER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        if log:
            log(f"falling back to external browser {url}")
        webbrowser.open(url)
        return "external"

    if log:
        log(
            "dashboard URL left for agent open_resource / Simple Browser "
            f"(no external Chrome): {url}"
        )
    return "pending"


def _write_dashboard_surface_url(workspace: str | Path | None, url: str) -> None:
    if workspace is None:
        return
    try:
        target = Path(workspace).expanduser().resolve() / ".sleeper"
        target.mkdir(parents=True, exist_ok=True)
        (target / "dashboard_surface.url").write_text(url + "\n", encoding="utf-8")
    except OSError:
        return


def surface_dashboard(
    queue_id: str | None = None,
    *,
    workspace: str | Path | None = None,
    log: Callable[[str], None] | None = None,
    open_ide: bool = True,
    open_browser_editor: bool = True,
) -> str:
    """
    Surface the dashboard in the Cursor IDE for the agent workspace.

    1. Open classic IDE only if that workspace is not already open
    2. Open localhost URL in Cursor's in-IDE browser — not OS Chrome
    """
    url = build_dashboard_url(queue_id)
    if not url.startswith(("http://localhost", "http://127.0.0.1", "https://localhost", "https://127.0.0.1")):
        raise ValueError(f"Refusing to open non-local dashboard URL: {url!r}")

    ide_workspace = resolve_ide_workspace(workspace)
    _write_dashboard_surface_url(workspace, url)

    if open_ide:
        ensure_cursor_ide_open(ide_workspace, log=log)

    if open_browser_editor:
        if log:
            log(f"surfacing dashboard {url} (ide_workspace={ide_workspace})")
        open_dashboard_in_ide_browser(url, log=log)
    elif log:
        log(f"updated dashboard deep-link file only: {url}")
    return url


def refocus_cursor_window(
    cursor_driver: object,
    *,
    log: Callable[[str], None] | None = None,
) -> None:
    """Bring the configured Cursor window to the foreground."""
    focus = getattr(cursor_driver, "focus_window", None)
    if not callable(focus):
        if log:
            log("cursor driver has no focus_window(); skipping refocus")
        return
    if log:
        log("refocusing Cursor window")
    focus()
    # Second nudge — browser launch often steals focus after the first activate.
    time.sleep(0.25)
    focus()


def prepare_dashboard_for_session(
    workspace: str | Path,
    cursor_driver: object,
    *,
    queue_id: str | None = None,
    log: Callable[[str], None] | None = None,
    open_browser: bool = True,
    refocus: bool = False,
    opened_urls: set[str] | None = None,
) -> bool:
    """
    Ensure the dashboard process is healthy; optionally open it once in the IDE.

    Browser/IDE surfacing happens at most once per session (``opened_urls``).
    Later calls (e.g. QUEUE_STARTED with a queue_id) only refresh the deep-link
    file so the already-open in-IDE tab can keep showing state.
    """
    healthy = ensure_dashboard_running(workspace, log=log)
    if healthy and open_browser:
        try:
            url = build_dashboard_url(queue_id)
        except ValueError as err:
            if log:
                log(f"skipping browser surface: {err}")
        else:
            already = opened_urls is not None and DASHBOARD_SURFACE_MARK in opened_urls
            if already:
                _write_dashboard_surface_url(workspace, url)
                if log:
                    log(f"dashboard already surfaced this session; deep-link updated to {url}")
            else:
                try:
                    surface_dashboard(
                        queue_id,
                        workspace=workspace,
                        log=log,
                        open_ide=True,
                        open_browser_editor=True,
                    )
                    if opened_urls is not None:
                        opened_urls.add(DASHBOARD_SURFACE_MARK)
                        opened_urls.add(url)
                except ValueError as err:
                    if log:
                        log(f"skipping browser surface: {err}")
                else:
                    if refocus:
                        time.sleep(FOCUS_RACE_DELAY_SECONDS)
    if refocus:
        refocus_cursor_window(cursor_driver, log=log)
    return healthy
