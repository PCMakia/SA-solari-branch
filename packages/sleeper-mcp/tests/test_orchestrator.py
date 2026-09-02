"""Autonomous orchestrator loop tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from sleeper_agent_mcp.execution.types import ExecutionResult
from sleeper_agent_mcp.orchestrator import run_afk_orchestrator
from sleeper_agent_mcp.overseer_controls import FAILURE_FILE_NAME, STOP_FILE_NAME
from sleeper_agent_mcp.repair_runner import RepairTurnResult
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


def _fail(
    task_id: str,
    workspace: str,
    *,
    failing_file: str | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        task_id=task_id,
        command="python",
        args=["broken.py"],
        returncode=1,
        stdout="",
        stderr="NameError: boom",
        workspace=workspace,
        failing_file_path=failing_file or f"{workspace}/broken.py",
    )


def test_orchestrator_repairs_and_completes_chain(tmp_path, monkeypatch):
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
        repair_model="claude-3-5-sonnet",
        repair_mode="agent",
    )

    results = [_ok("s1", ws), _fail("s2", ws), _ok("s2", ws, "2\n"), _ok("s3", ws, "3\n")]

    def fake_run_task(**kwargs):
        return results.pop(0)

    repair_calls: list[dict] = []

    def fake_repair(**kwargs):
        repair_calls.append(kwargs)
        return RepairTurnResult(status="finished", finished=True, run_id="run-1")

    monkeypatch.setattr("sleeper_agent_mcp.orchestrator.run_task", fake_run_task)

    out = run_afk_orchestrator(
        mgr,
        record.id,
        utc_now=lambda: "2026-01-01T00:00:00Z",
        repair_runner=fake_repair,
    )

    assert out["status"] == "COMPLETED"
    assert out["completed_steps"] == 3
    assert len(repair_calls) == 1
    assert repair_calls[0]["execution_command"] == "python broken.py"
    assert repair_calls[0]["repair_model"] == "claude-3-5-sonnet"
    final = mgr.get_queue(record.id)
    assert final is not None
    assert final.status == QueueStatus.COMPLETED
    assert len(final.repair_history) == 1


def test_orchestrator_aborts_after_max_repairs(tmp_path, monkeypatch):
    mgr = StateManager(tmp_path / "state.json")
    ws = str(tmp_path)
    record = mgr.create_queue(
        tasks=[TaskSpec(id="s1", command="python", args=["broken.py"])],
        workspace=ws,
        max_retries=3,
    )

    def always_fail(**kwargs):
        return _fail("s1", ws)

    def fake_repair(**kwargs):
        return RepairTurnResult(status="finished", finished=True)

    monkeypatch.setattr("sleeper_agent_mcp.orchestrator.run_task", always_fail)

    out = run_afk_orchestrator(
        mgr,
        record.id,
        utc_now=lambda: "2026-01-01T00:00:00Z",
        repair_runner=fake_repair,
    )

    assert out["status"] == "ABORTED"
    assert (tmp_path / FAILURE_FILE_NAME).is_file()
    payload = json.loads((tmp_path / FAILURE_FILE_NAME).read_text(encoding="utf-8"))
    assert payload["failed_task_id"] == "s1"
    assert len(payload["repair_history"]) == 3


def test_orchestrator_stops_on_kill_switch(tmp_path, monkeypatch):
    mgr = StateManager(tmp_path / "state.json")
    ws = str(tmp_path)
    record = mgr.create_queue(
        tasks=[TaskSpec(id="s1", command="python", args=["-c", "1"])],
        workspace=ws,
    )
    (tmp_path / STOP_FILE_NAME).write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "sleeper_agent_mcp.orchestrator.run_task",
        MagicMock(side_effect=AssertionError("should not run task")),
    )

    out = run_afk_orchestrator(
        mgr,
        record.id,
        utc_now=lambda: "2026-01-01T00:00:00Z",
        repair_runner=MagicMock(),
    )

    assert out["status"] == "STOPPED_BY_USER"
    final = mgr.get_queue(record.id)
    assert final is not None
    assert final.status == QueueStatus.STOPPED_BY_USER
