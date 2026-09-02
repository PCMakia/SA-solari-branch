"""Repair-loop state machine tests (no Solari API)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import sleeper_agent_mcp.server as server_module
from sleeper_agent_mcp.execution.types import ExecutionResult
from sleeper_agent_mcp.server import _run_from_current_step
from sleeper_agent_mcp.state import StateManager, TaskSpec


def test_needs_repair_then_resume_completes(tmp_path: Path):
    state_file = tmp_path / "queue_state.json"
    mgr = StateManager(state_file)
    record = mgr.create_queue(
        tasks=[TaskSpec(id="t1", command="python", args=["-c", "raise SystemExit(1)"])],
        workspace=str(tmp_path),
        label="repair-test",
    )
    queue_id = record.id

    fail = ExecutionResult(
        task_id="t1",
        command="python",
        args=["-c", "raise SystemExit(1)"],
        returncode=1,
        stdout="",
        stderr="boom",
        workspace=str(tmp_path),
        failing_file_path=str(tmp_path / "demo.py"),
    )
    ok = ExecutionResult(
        task_id="t1",
        command="python",
        args=["-c", "print(5)"],
        returncode=0,
        stdout="5\n",
        stderr="",
        workspace=str(tmp_path),
    )

    with patch.object(server_module, "_state", mgr):
        with patch("sleeper_agent_mcp.server.run_task", return_value=fail):
            first = _run_from_current_step(queue_id)

        assert first["status"] == "NEEDS_REPAIR"
        assert first["failing_file_path"] == str(tmp_path / "demo.py")

        with patch("sleeper_agent_mcp.server.run_task", return_value=ok):
            second = _run_from_current_step(queue_id)

    assert second["status"] == "COMPLETED"
    assert second["completed_steps"] == 1
