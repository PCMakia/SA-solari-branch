"""Tests for auto-starting sleeper_daemon watch."""

from __future__ import annotations

from sleeper_agent_mcp import sleeper_watch


def test_ensure_sleeper_watch_short_circuits_when_pid_alive(tmp_path, monkeypatch):
    monkeypatch.setattr(sleeper_watch, "_read_watch_pid", lambda _ws: 4242)
    monkeypatch.setattr(sleeper_watch, "_pid_is_running", lambda pid: pid == 4242)
    spawned = {"n": 0}

    def boom(*_a, **_k):
        spawned["n"] += 1
        raise AssertionError("should not spawn")

    monkeypatch.setattr(sleeper_watch.subprocess, "Popen", boom)
    result = sleeper_watch.ensure_sleeper_watch(tmp_path, window_title="Cursor")
    assert result["status"] == "ALREADY_RUNNING"
    assert result["pid"] == 4242
    assert spawned["n"] == 0


def test_ensure_sleeper_watch_spawns_and_writes_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(sleeper_watch, "_read_watch_pid", lambda _ws: None)

    class FakeProc:
        pid = 99901

    captured: dict = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(sleeper_watch.subprocess, "Popen", fake_popen)
    result = sleeper_watch.ensure_sleeper_watch(tmp_path, window_title="Solari")
    assert result["status"] == "STARTED"
    assert result["pid"] == 99901
    assert (tmp_path / ".sleeper" / "watch.pid").read_text(encoding="utf-8").strip() == "99901"
    assert "watch" in captured["cmd"]
    assert str(tmp_path.resolve()) in captured["cmd"]
    assert "Solari" in captured["cmd"]
