"""Multi-step chain: success steps run, middle failure pauses for agent repair."""

from unittest.mock import patch

import sleeper_agent_mcp.server as server_module
from sleeper_agent_mcp.execution.types import ExecutionResult
from sleeper_agent_mcp.server import _run_from_current_step
from sleeper_agent_mcp.state import StateManager, TaskSpec


def test_chain_pauses_mid_pipeline_for_agent(tmp_path):
    mgr = StateManager(tmp_path / "state.json")
    record = mgr.create_queue(
        tasks=[
            TaskSpec(id="s1", command="python", args=["-c", "print(1)"]),
            TaskSpec(id="s2", command="python", args=["-c", "fail"]),
            TaskSpec(id="s3", command="python", args=["-c", "print(3)"]),
        ],
        workspace=str(tmp_path),
        label="chain-test",
        max_retries=3,
    )
    qid = record.id

    ok = lambda tid, stdout: ExecutionResult(
        task_id=tid, command="python", args=[], returncode=0,
        stdout=stdout, stderr="", workspace=str(tmp_path),
    )
    fail = ExecutionResult(
        task_id="s2", command="python", args=[], returncode=1,
        stdout="", stderr="boom", workspace=str(tmp_path),
        failing_file_path=str(tmp_path / "broken.py"),
    )

    results = [ok("s1", "1\n"), fail]

    def side_effect(**kwargs):
        return results.pop(0)

    with patch.object(server_module, "_state", mgr):
        with patch("sleeper_agent_mcp.server.run_task", side_effect=side_effect):
            out = _run_from_current_step(qid)

    assert out["status"] == "NEEDS_REPAIR"
    assert out["failed_task_id"] == "s2"
    assert out["agent_repair_attempts_remaining"] == 3
    assert mgr.get_queue(qid).current_step_index == 1

    results = [ok("s2", "2\n"), ok("s3", "3\n")]
    with patch.object(server_module, "_state", mgr):
        with patch("sleeper_agent_mcp.server.run_task", side_effect=side_effect):
            done = _run_from_current_step(qid)

    assert done["status"] == "COMPLETED"
    assert done["completed_steps"] == 3
