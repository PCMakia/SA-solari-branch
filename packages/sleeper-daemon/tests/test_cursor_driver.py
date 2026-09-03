"""Tests for Cursor chat focus anchoring."""

from __future__ import annotations

import pytest

from sleeper_daemon.cursor_driver import HostCursorDriver
from sleeper_daemon.windows import (
    CursorWindow,
    is_browser_window_title,
    is_cursor_window_title,
)


def test_browser_title_detection():
    assert is_browser_window_title("Sleeper - Google Search - Google Chrome")
    assert is_browser_window_title("localhost:3000 - Microsoft Edge")
    assert not is_browser_window_title(".gitignore - Solari - Cursor")


def test_cursor_title_detection():
    assert is_cursor_window_title(".gitignore - Solari - Cursor")
    assert not is_cursor_window_title("Google Chrome")
    assert not is_cursor_window_title("localhost - Google Search - Chrome")


def test_assert_cursor_foreground_rejects_browser(monkeypatch):
    driver = HostCursorDriver(window_title="Solari")
    monkeypatch.setattr(
        "sleeper_daemon.cursor_driver.get_foreground_window",
        lambda: CursorWindow(hwnd=1, title="foo - Google Search - Google Chrome", pid=9),
    )
    with pytest.raises(RuntimeError, match="browser"):
        driver._assert_cursor_foreground()


def test_send_message_focuses_composer_before_paste(monkeypatch):
    driver = HostCursorDriver(window_title="Solari")
    hotkeys: list[tuple] = []
    presses: list[str] = []

    class FakeAutogui:
        FAILSAFE = False

        @staticmethod
        def hotkey(*keys):
            hotkeys.append(keys)

        @staticmethod
        def press(key):
            presses.append(key)

    monkeypatch.setattr(driver, "focus_window", lambda: None)
    monkeypatch.setattr(
        "sleeper_daemon.cursor_driver.get_foreground_window",
        lambda: CursorWindow(hwnd=42, title="Solari - Cursor", pid=1),
    )
    monkeypatch.setattr(
        "sleeper_daemon.cursor_driver._paste_text",
        lambda text: hotkeys.append(("paste", text)),
    )
    monkeypatch.setitem(__import__("sys").modules, "pyautogui", FakeAutogui)
    monkeypatch.setattr("sleeper_daemon.cursor_driver.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setenv("SLEEPER_CHAT_FOCUS_HOTKEY", "ctrl+i")
    monkeypatch.setenv("SLEEPER_CHAT_FOCUS_HOTKEY_FALLBACK", "")

    driver.send_message("hello repair")

    assert ("ctrl", "i") in hotkeys
    assert ("paste", "hello repair") in hotkeys
    assert "enter" in presses
    assert "escape" in presses
