"""Tests for stop file, failure artifacts, and cache hygiene."""

import json

from sleeper_agent_mcp.overseer_controls import (
    FAILURE_FILE_NAME,
    STOP_FILE_NAME,
    clear_transient_caches,
    is_stop_requested,
    request_stop,
    write_failure_artifact,
    write_stop_artifact,
)


def test_stop_file_halts_detection(tmp_path):
    assert not is_stop_requested(tmp_path)
    (tmp_path / STOP_FILE_NAME).write_text("", encoding="utf-8")
    assert is_stop_requested(tmp_path)


def test_clear_transient_caches(tmp_path):
    cache = tmp_path / "pkg" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "mod.pyc").write_bytes(b"x")
    pytest_cache = tmp_path / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "v").mkdir()

    removed = clear_transient_caches(tmp_path)
    assert any("__pycache__" in path for path in removed)
    assert not cache.exists()
    assert not pytest_cache.exists()


def test_request_stop_writes_kill_switch(tmp_path):
    path = request_stop(tmp_path, reason="unit-test")
    assert path.name == STOP_FILE_NAME
    assert is_stop_requested(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["reason"] == "unit-test"


def test_write_failure_artifact(tmp_path):
    path = write_failure_artifact(
        tmp_path,
        queue_id="q-1",
        label="demo",
        failed_task_id="step-2",
        retry_count=4,
        max_retries=3,
        last_error={"stderr": "boom"},
        repair_history=[{"attempt": 1}],
    )
    assert path.name == FAILURE_FILE_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "ABORTED"
    assert payload["failed_task_id"] == "step-2"
    assert payload["repair_history"][0]["attempt"] == 1


def test_write_stop_artifact(tmp_path):
    path = write_stop_artifact(
        tmp_path,
        queue_id="q-2",
        label="demo",
        step_index=1,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "STOPPED_BY_USER"
    assert payload["active_step_index"] == 1
