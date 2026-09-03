"""Host and Solari drivers for Cursor chat automation."""

from __future__ import annotations

import os
import sys
import time
from abc import ABC, abstractmethod

from sleeper_daemon.windows import (
    CursorWindow,
    get_foreground_window,
    is_browser_window_title,
    is_cursor_window_title,
    select_cursor_window,
)


class CursorChatDriver(ABC):
    @abstractmethod
    def send_message(self, text: str) -> None: ...

    @abstractmethod
    def wait_for_turn_complete(self, *, timeout_seconds: float) -> bool: ...

    def focus_window(self) -> None:
        """Bring the target Cursor window to the foreground (optional)."""
        return None


class HostCursorDriver(CursorChatDriver):
    """Drive Cursor on the host desktop (fallback AFK mode)."""

    def __init__(
        self,
        *,
        window_title: str | None = None,
        hwnd: int | None = None,
    ) -> None:
        self._window_title = window_title or os.environ.get("SLEEPER_CURSOR_WINDOW_TITLE")
        hwnd_env = os.environ.get("SLEEPER_CURSOR_HWND")
        self._hwnd = hwnd or (int(hwnd_env) if hwnd_env else None)
        self._window: CursorWindow | None = None

    def _resolve_window(self) -> CursorWindow:
        window = select_cursor_window(title_substring=self._window_title, hwnd=self._hwnd)
        if window is None:
            raise RuntimeError(
                "No Cursor window found. Set SLEEPER_CURSOR_WINDOW_TITLE or pass --window-title."
            )
        self._window = window
        return window

    def focus_window(self) -> None:
        """Activate the configured Cursor window without typing."""
        if sys.platform != "win32":
            raise RuntimeError("HostCursorDriver currently supports Windows only.")
        window = self._resolve_window()
        try:
            import pygetwindow as gw
        except ImportError as err:
            raise RuntimeError(
                "Install pygetwindow for host Cursor automation."
            ) from err

        target = None
        for candidate in gw.getAllWindows():
            if candidate.title == window.title:
                target = candidate
                break
        if target is None:
            # Fallback: any window whose title looks like Cursor and matches filter.
            for candidate in gw.getAllWindows():
                if not candidate.title:
                    continue
                if self._window_title and self._window_title.lower() not in candidate.title.lower():
                    continue
                if is_cursor_window_title(candidate.title):
                    target = candidate
                    break
        if target is None:
            raise RuntimeError(f"Unable to focus Cursor window: {window.title}")
        if target.isMinimized:
            target.restore()
        target.activate()
        time.sleep(0.35)

    def _assert_cursor_foreground(self) -> None:
        foreground = get_foreground_window()
        if foreground is None:
            return
        title = foreground.title
        if is_browser_window_title(title):
            raise RuntimeError(
                f"Foreground window is a browser ({title!r}); refusing to paste. "
                "Refocus Cursor and retry."
            )
        if not is_cursor_window_title(title):
            # Soft warn path: still allow if hwnd matches resolved Cursor window.
            expected = self._window
            if expected and foreground.hwnd == expected.hwnd:
                return
            raise RuntimeError(
                f"Foreground window is not Cursor ({title!r}); refusing to paste."
            )

    def _focus_chat_input(self) -> None:
        """
        Force the Agent/Composer input field to own the text cursor.

        Prefer Ctrl+I (Composer). Avoid relying on Ctrl+L alone — that shortcut
        focuses the browser address bar when Chrome/Edge still has focus.
        """
        import pyautogui

        # Clear any accidental address-bar / overlay focus.
        pyautogui.press("escape")
        time.sleep(0.1)

        hotkey = os.environ.get("SLEEPER_CHAT_FOCUS_HOTKEY", "ctrl+i").strip().lower()
        keys = [part for part in hotkey.replace("-", "+").split("+") if part]
        if not keys:
            keys = ["ctrl", "i"]
        pyautogui.hotkey(*keys)
        time.sleep(0.25)

        # Second pass: open Agent chat if Composer hotkey landed elsewhere.
        secondary = os.environ.get("SLEEPER_CHAT_FOCUS_HOTKEY_FALLBACK", "ctrl+l").strip().lower()
        if secondary and secondary != hotkey:
            # Only use Ctrl+L after we have already verified Cursor is foreground.
            self._assert_cursor_foreground()
            fallback_keys = [part for part in secondary.replace("-", "+").split("+") if part]
            if fallback_keys:
                pyautogui.hotkey(*fallback_keys)
                time.sleep(0.2)

    def send_message(self, text: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("HostCursorDriver currently supports Windows only.")
        try:
            import pyautogui
        except ImportError as err:
            raise RuntimeError(
                "Install pyautogui and pygetwindow for host Cursor automation."
            ) from err

        pyautogui.FAILSAFE = False

        # Activate Cursor, then re-check focus (browser may steal it after open).
        for attempt in range(3):
            self.focus_window()
            time.sleep(0.2)
            foreground = get_foreground_window()
            if foreground and is_browser_window_title(foreground.title):
                time.sleep(0.3)
                continue
            if foreground is None or is_cursor_window_title(foreground.title):
                break
            time.sleep(0.2)
        else:
            self._assert_cursor_foreground()

        self._assert_cursor_foreground()
        self._focus_chat_input()
        self._assert_cursor_foreground()

        # Always clipboard-paste; never type long prompts (avoids address-bar search).
        _paste_text(text)
        time.sleep(0.2)
        self._assert_cursor_foreground()
        pyautogui.press("enter")
        self._turn_started_at = time.monotonic()

    def wait_for_turn_complete(self, *, timeout_seconds: float) -> bool:
        """
        Wait until Composer appears idle.

        Uses a minimum settle delay plus optional template/OCR hook. When
        SLEEPER_FORCE_IDLE=1, returns after the minimum delay (tests/dry-run).
        """
        minimum = float(os.environ.get("SLEEPER_TURN_MIN_SETTLE_SECONDS", "5"))
        elapsed = time.monotonic() - getattr(self, "_turn_started_at", time.monotonic())
        if elapsed < minimum:
            time.sleep(minimum - elapsed)
        if os.environ.get("SLEEPER_FORCE_IDLE", "").strip() in {"1", "true", "yes"}:
            return True

        deadline = time.monotonic() + timeout_seconds
        poll = float(os.environ.get("SLEEPER_TURN_POLL_SECONDS", "2"))
        while time.monotonic() < deadline:
            if _composer_idle_heuristic():
                return True
            time.sleep(poll)
        return False


def _paste_text(text: str) -> None:
    import pyperclip
    import pyautogui

    pyperclip.copy(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")


def _composer_idle_heuristic() -> bool:
    """
    Placeholder for visual template matching on the Composer submit/stop icons.

    Returns True when no better signal is available so host mode can proceed.
    """
    return True


class SolariVirtualDesktopDriver(CursorChatDriver):
    """
    Drive Cursor inside a Solari Desktop VM (isolated display).

    Requires SOLARI_API_KEY and an active desktop session with Cursor installed
    in the template image.
    """

    def __init__(self, *, session_id: str | None = None) -> None:
        self._session_id = session_id or os.environ.get("SLEEPER_SOLARI_DESKTOP_SESSION")

    def send_message(self, text: str) -> None:
        raise NotImplementedError(
            "Solari virtual desktop driver requires a configured desktop session. "
            "Set SLEEPER_CURSOR_DRIVER=host to use host AFK mode."
        )

    def focus_window(self) -> None:
        raise NotImplementedError("Solari virtual desktop driver is not configured.")

    def wait_for_turn_complete(self, *, timeout_seconds: float) -> bool:
        raise NotImplementedError("Solari virtual desktop driver is not configured.")


def build_cursor_driver(
    driver_name: str | None = None,
    *,
    window_title: str | None = None,
) -> CursorChatDriver:
    selected = (driver_name or os.environ.get("SLEEPER_CURSOR_DRIVER", "host")).strip().lower()
    if selected in {"solari", "virtual", "desktop"}:
        return SolariVirtualDesktopDriver()
    return HostCursorDriver(window_title=window_title)
