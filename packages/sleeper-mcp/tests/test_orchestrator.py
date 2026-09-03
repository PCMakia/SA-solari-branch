"""Autonomous orchestrator loop tests (local Cursor daemon repair path)."""

from __future__ import annotations

from sleeper_agent_mcp.execution.types import ExecutionResult
from sleeper_agent_mcp.orchestrator import run_afk_orchestrator
from sleeper_agent_mcp.overseer_controls import FAILURE_FILE_NAME
from sleeper_agent_mcp.sleeper_events import (
    EVENT_AWAITING_DAEMON,
    EVENT_NEEDS_REPAIR,
    EVENT_STEP_PASSED,
    read_events,
)
from sleeper_agent_mcp.state import QueueStatus, StateManager, TaskSpec


def _ok(task_id: str, workspace: str, stdout: str = "ok\n") -> ExecutionResult:
    return ExecutionResult(
        task_id=task_id,
        command="python",
        args=[],
        returncode=0,
        stdout=stdout,
        stderr="",
        workspace=workspace,
    )


def _fail(task_id: str, workspace: str) -> ExecutionResult:
    return ExecutionResult(
        task_id=task_id,
        command="python",
        args=["broken.py"],
        returncode=1,
        stdout="",
        stderr="NameError: boom",
        workspace=workspace,
        failing_file_path=f"{workspace}/broken.py",
    )


def test_orchestrator_pauses_for_daemon_repair_then_completes(tmp_path, monkeypatch):
    mgr = StateManager(tmp_path / "state.json")
    ws = str(tmp_path)
    record = mgr.create_queue(
        tasks=[
            TaskSpec(id="s1", command="python", args=["-c", "1"]),
            TaskSpec(id="s2", command="python", args=["broken.py"]),
            TaskSpec(id="s3", command="python", args=["-c", "3"]),
        ],
        workspace=ws,
        max_retries=3,
        label="orch-test",
        afk_mode=True,
    )

    results = [_ok("s1", ws), _fail("s2", ws), _ok("s2", ws, "2\n"), _ok("s3", ws, "3\n")]
    calls = {"count": 0}

    def fake_run_task(**kwargs):
        calls["count"] += 1
        return results.pop(0)

    monkeypatch.setattr("sleeper_agent_mcp.orchestrator.run_task", fake_run_task)

    first = run_afk_orchestrator(
        mgr,
        record.id,
        utc_now=lambda: "2026-01-01T00:00:00Z",
    )
    assert first["status"] == "NEEDS_REPAIR"
    assert calls["count"] == 2
    events = read_events(ws)
    assert any(event["type"] == EVENT_AWAITING_DAEMON for event in events)

    second = run_afk_orchestrator(
        mgr,
        record.id,
        utc_now=lambda: "2026-01-01T00:00:01Z",
    )
    assert second["status"] == "COMPLETED"
    assert calls["count"] == 4
    final = mgr.get_queue(record.id)
    assert final is not None
    assert final.status == QueueStatus.COMPLETED
    assert any(event["type"] == EVENT_STEP_PASSED for event in read_events(ws))


def test_orchestrator_aborts_after_max_daemon_repair_cycles(tmp_path, monkeypatch):
    mgr = StateManager(tmp_path / "state.json")
    ws = str(tmp_path)
    record = mgr.create_queue(
        tasks=[TaskSpec(id="s1", command="python", args=["broken.py"])],
        workspace=ws,
        max_retries=3,
        afk_mode=True,
    )

    monkeypatch.setattr(
        "sleeper_agent_mcp.orchestrator.run_task",
        lambda **_kwargs: _fail("s1", ws),
    )

    for _ in range(3):
        out = run_afk_orchestrator(
            mgr,
            record.id,
            utc_now=lambda: "2026-01-01T00:00:00Z",
        )
        assert out["status"] == "NEEDS_REPAIR"

    out = run_afk_orchestrator(
        mgr,
        record.id,
        utc_now=lambda: "2026-01-01T00:00:01Z",
    )
    assert out["status"] == "ABORTED"
    assert (tmp_path / FAILURE_FILE_NAME).is_file()
    assert "# Overseer Failure Report" in (tmp_path / FAILURE_FILE_NAME).read_text(encoding="utf-8")
