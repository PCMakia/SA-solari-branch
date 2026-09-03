"""Tests for dashboard lifecycle helpers."""

from __future__ import annotations

import pytest

from sleeper_daemon import dashboard


def test_surface_dashboard_builds_deep_link(monkeypatch, tmp_path):
    opened: list[str] = []
    ide: list[str] = []
    monkeypatch.setattr(
        dashboard,
        "ensure_cursor_ide_open",
        lambda path, **_k: ide.append(str(path)) or True,
    )
    monkeypatch.setattr(
        dashboard,
        "open_dashboard_in_ide_browser",
        lambda url, **_k: opened.append(url) or "ide-palette",
    )
    monkeypatch.setenv("SLEEPER_DASHBOARD_URL", "http://localhost:3000")
    monkeypatch.setenv("SLEEPER_CURSOR_WORKSPACE", str(tmp_path))

    url = dashboard.surface_dashboard("abc-123", workspace=tmp_path)
    assert url == "http://localhost:3000/?queue_id=abc-123"
    assert opened == [url]
    assert ide == [str(tmp_path.resolve())]
    assert (tmp_path / ".sleeper" / "dashboard_surface.url").read_text(encoding="utf-8").strip() == url


def test_resolve_ide_workspace_walks_to_repo_root(tmp_path, monkeypatch):
    monkeypatch.delenv("SLEEPER_CURSOR_WORKSPACE", raising=False)
    root = tmp_path / "Solari"
    (root / ".git").mkdir(parents=True)
    (root / "apps" / "overseer-dashboard").mkdir(parents=True)
    nested = root / "canary_test"
    nested.mkdir()
    assert dashboard.resolve_ide_workspace(nested) == root.resolve()


def test_build_dashboard_url_rejects_prompt_payload():
    with pytest.raises(ValueError, match="Invalid queue_id"):
        dashboard.build_dashboard_url('"""Sleeper-call{...}"""')


def test_build_dashboard_url_rejects_non_local_host(monkeypatch):
    monkeypatch.setenv("SLEEPER_DASHBOARD_URL", "http://evil.example/steal")
    with pytest.raises(ValueError, match="localhost"):
        dashboard.build_dashboard_url()


def test_surface_dashboard_refuses_non_http_local(monkeypatch, tmp_path):
    monkeypatch.setenv("SLEEPER_DASHBOARD_URL", "http://localhost:3000")
    monkeypatch.setenv("SLEEPER_CURSOR_WORKSPACE", str(tmp_path))
    opened: list[str] = []
    monkeypatch.setattr(dashboard, "ensure_cursor_ide_open", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dashboard,
        "open_dashboard_in_ide_browser",
        lambda url, **_k: opened.append(url) or "pending",
    )
    dashboard.surface_dashboard(None, workspace=tmp_path)
    assert opened and opened[0].startswith("http://localhost:3000")


def test_startup_timeout_is_30s():
    assert dashboard.STARTUP_TIMEOUT_SECONDS == 30.0
    assert dashboard.HEALTH_PATH == "/api/health"


def test_choose_npm_command_uses_dev_without_build_id(tmp_path, monkeypatch):
    monkeypatch.delenv("SLEEPER_DASHBOARD_FORCE_DEV", raising=False)
    (tmp_path / ".next").mkdir()
    # Dev cache only — no BUILD_ID
    cmd = dashboard._choose_npm_command(tmp_path)
    assert cmd[-1] == "dev"


def test_choose_npm_command_uses_start_with_build_id(tmp_path, monkeypatch):
    monkeypatch.delenv("SLEEPER_DASHBOARD_FORCE_DEV", raising=False)
    nxt = tmp_path / ".next"
    nxt.mkdir()
    (nxt / "BUILD_ID").write_text("abc", encoding="utf-8")
    cmd = dashboard._choose_npm_command(tmp_path)
    assert cmd[-1] == "start"


def test_ensure_dashboard_running_short_circuits_when_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "is_dashboard_healthy", lambda: True)
    spawned = {"count": 0}

    def boom(*_args, **_kwargs):
        spawned["count"] += 1
        raise AssertionError("should not spawn")

    monkeypatch.setattr(dashboard, "_spawn_dashboard", boom)
    assert dashboard.ensure_dashboard_running(tmp_path) is True
    assert spawned["count"] == 0


def test_ensure_dashboard_running_spawns_and_waits(tmp_path, monkeypatch):
    health = {"ok": False}

    monkeypatch.setattr(dashboard, "is_dashboard_healthy", lambda: health["ok"])
    monkeypatch.setattr(dashboard, "is_port_open", lambda *_a, **_k: False)
    monkeypatch.setattr(dashboard, "_read_saved_pid", lambda _ws: None)
    monkeypatch.setattr(dashboard, "_spawn_dashboard", lambda *_a, **_k: 4242)
    monkeypatch.setattr(dashboard, "STARTUP_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(dashboard, "POLL_INTERVAL_SECONDS", 0.05)

    def flip_then_true(_seconds):
        health["ok"] = True

    monkeypatch.setattr(dashboard.time, "sleep", flip_then_true)
    assert dashboard.ensure_dashboard_running(tmp_path) is True


def test_ensure_dashboard_skips_spawn_when_port_busy(tmp_path, monkeypatch):
    health = {"ok": False}
    spawned = {"count": 0}

    monkeypatch.setattr(dashboard, "is_dashboard_healthy", lambda: health["ok"])
    monkeypatch.setattr(dashboard, "is_port_open", lambda *_a, **_k: True)
    monkeypatch.setattr(dashboard, "_read_saved_pid", lambda _ws: None)

    def boom(*_a, **_k):
        spawned["count"] += 1
        raise AssertionError("should not spawn when port busy")

    monkeypatch.setattr(dashboard, "_spawn_dashboard", boom)
    monkeypatch.setattr(dashboard, "STARTUP_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(dashboard, "POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(dashboard.time, "sleep", lambda *_a, **_k: None)

    assert dashboard.ensure_dashboard_running(tmp_path) is False
    assert spawned["count"] == 0


def test_prepare_dashboard_skips_browser_when_unhealthy(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(dashboard, "ensure_dashboard_running", lambda *_a, **_k: False)
    monkeypatch.setattr(
        dashboard,
        "surface_dashboard",
        lambda *_a, **_k: calls.append("surface") or "x",
    )
    monkeypatch.setattr(
        dashboard,
        "refocus_cursor_window",
        lambda *_a, **_k: calls.append("refocus"),
    )
    monkeypatch.setattr(dashboard.time, "sleep", lambda *_a, **_k: None)

    class Dummy:
        pass

    ok = dashboard.prepare_dashboard_for_session(
        tmp_path, Dummy(), queue_id="q1", refocus=True
    )
    assert ok is False
    assert calls == ["refocus"]


def test_prepare_dashboard_surfaces_once_without_default_refocus(tmp_path, monkeypatch):
    calls: list[str] = []
    opened: set[str] = set()
    monkeypatch.setattr(dashboard, "ensure_dashboard_running", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dashboard,
        "surface_dashboard",
        lambda queue_id=None, **_k: calls.append(f"surface:{queue_id}") or "url",
    )
    monkeypatch.setattr(
        dashboard,
        "refocus_cursor_window",
        lambda *_a, **_k: calls.append("refocus"),
    )
    written: list[str] = []
    monkeypatch.setattr(
        dashboard,
        "_write_dashboard_surface_url",
        lambda _ws, url: written.append(url),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(dashboard.time, "sleep", lambda s: sleeps.append(s))

    class Dummy:
        pass

    ok = dashboard.prepare_dashboard_for_session(
        tmp_path, Dummy(), queue_id=None, opened_urls=opened
    )
    assert ok is True
    assert calls == ["surface:None"]
    assert dashboard.DASHBOARD_SURFACE_MARK in opened
    assert sleeps == []

    # QUEUE_STARTED with a different URL must not reopen Simple Browser.
    ok2 = dashboard.prepare_dashboard_for_session(
        tmp_path, Dummy(), queue_id="q9", opened_urls=opened
    )
    assert ok2 is True
    assert calls == ["surface:None"]
    assert written == ["http://localhost:3000/?queue_id=q9"]


def test_ensure_cursor_ide_skips_when_already_open(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "cursor_ide_already_open_for_workspace",
        lambda _path: True,
    )
    spawned: list[list[str]] = []

    def boom(*_a, **_k):
        spawned.append(["nope"])
        raise AssertionError("should not spawn cursor --classic")

    monkeypatch.setattr(dashboard.subprocess, "Popen", boom)
    logs: list[str] = []
    assert dashboard.ensure_cursor_ide_open(tmp_path, log=logs.append) is True
    assert spawned == []
    assert any("skipping Open IDE" in line for line in logs)


def test_prepare_dashboard_can_skip_browser(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(dashboard, "ensure_dashboard_running", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dashboard,
        "surface_dashboard",
        lambda *_a, **_k: calls.append("surface") or "x",
    )
    monkeypatch.setattr(
        dashboard,
        "refocus_cursor_window",
        lambda *_a, **_k: calls.append("refocus"),
    )

    class Dummy:
        pass

    ok = dashboard.prepare_dashboard_for_session(
        tmp_path, Dummy(), queue_id="q1", open_browser=False, refocus=False
    )
    assert ok is True
    assert calls == []
