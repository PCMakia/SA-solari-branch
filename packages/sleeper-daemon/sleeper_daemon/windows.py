"""Enumerate Cursor IDE windows on the host OS."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CursorWindow:
    hwnd: int
    title: str
    pid: int


def get_active_cursor_windows() -> list[CursorWindow]:
    """Return Cursor windows with visible titles."""
    if sys.platform == "win32":
        return _windows_cursor_windows()
    return _posix_cursor_windows()


def _windows_cursor_windows() -> list[CursorWindow]:
    script = (
        "$items = Get-Process | Where-Object { "
        "$_.MainWindowTitle -and ($_.ProcessName -match 'cursor|Cursor') "
        "}; "
        "$items | ForEach-Object { "
        "[PSCustomObject]@{ hwnd = [int]$_.MainWindowHandle; title = $_.MainWindowTitle; pid = $_.Id } "
        "} | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    items = raw if isinstance(raw, list) else [raw]
    windows: list[CursorWindow] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        hwnd = int(item.get("hwnd") or 0)
        title = str(item.get("title") or "")
        if hwnd and title:
            windows.append(CursorWindow(hwnd=hwnd, title=title, pid=int(item.get("pid") or 0)))
    return windows


def _posix_cursor_windows() -> list[CursorWindow]:
    return []


def select_cursor_window(
    *,
    title_substring: str | None = None,
    hwnd: int | None = None,
) -> CursorWindow | None:
    windows = get_active_cursor_windows()
    if hwnd is not None:
        for window in windows:
            if window.hwnd == hwnd:
                return window
    if title_substring:
        needle = title_substring.lower()
        for window in windows:
            if needle in window.title.lower():
                return window
    return windows[0] if windows else None


# Prefer multi-word / branded markers so short tokens like "edge" do not
# false-positive on titles such as "Knowledge - Solari - Cursor".
BROWSER_TITLE_MARKERS = (
    "google chrome",
    "microsoft edge",
    "mozilla firefox",
    " - chrome",
    " - edge",
    " - firefox",
    " - opera",
    " - brave",
    "internet explorer",
    " - google search",
    "google search -",
)


def get_foreground_window() -> CursorWindow | None:
    """Return the current foreground window (any process), if available."""
    if sys.platform != "win32":
        return None
    script = (
        "Add-Type @'\n"
        "using System;\n"
        "using System.Text;\n"
        "using System.Runtime.InteropServices;\n"
        "public class FgWin {\n"
        "  [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();\n"
        "  [DllImport(\"user32.dll\")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);\n"
        "  [DllImport(\"user32.dll\")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);\n"
        "}\n"
        "'@;\n"
        "$hwnd = [FgWin]::GetForegroundWindow();\n"
        "if ($hwnd -eq [IntPtr]::Zero) { exit 0 };\n"
        "$sb = New-Object System.Text.StringBuilder 1024;\n"
        "[void][FgWin]::GetWindowText($hwnd, $sb, $sb.Capacity);\n"
        "$pidOut = 0;\n"
        "[void][FgWin]::GetWindowThreadProcessId($hwnd, [ref]$pidOut);\n"
        "[PSCustomObject]@{ hwnd = [int64]$hwnd; title = $sb.ToString(); pid = [int]$pidOut } "
        "| ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    hwnd = int(raw.get("hwnd") or 0)
    title = str(raw.get("title") or "")
    if not hwnd:
        return None
    return CursorWindow(hwnd=hwnd, title=title, pid=int(raw.get("pid") or 0))


def is_browser_window_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in BROWSER_TITLE_MARKERS)


def is_cursor_window_title(title: str) -> bool:
    lowered = title.lower()
    if is_browser_window_title(lowered):
        return False
    return "cursor" in lowered
