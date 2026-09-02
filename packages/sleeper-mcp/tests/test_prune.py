"""Tests for stale queue pruning."""

from __future__ import annotations

from pathlib import Path

from sleeper_agent_mcp.state import QueueStatus, StateManager, TaskSpec


def test_prune_non_running_queues(tmp_path: Path):
    state_file = tmp_path / "queue_state.json"
    mgr = StateManager(state_file)

    stale = mgr.create_queue(
        tasks=[TaskSpec(id="old", command="python", args=["-c", "1"])],
        workspace=str(tmp_path),
    )
    stale.status = QueueStatus.NEEDS_REPAIR
    mgr.update_queue(stale)

    running = mgr.create_queue(
        tasks=[TaskSpec(id="live", command="python", args=["-c", "2"])],
        workspace=str(tmp_path),
    )
    running.status = QueueStatus.RUNNING
    mgr.update_queue(running)

    removed = mgr.prune_non_running_queues()
    assert removed == 1

    reloaded = StateManager(state_file)
    assert reloaded.get_queue(stale.id) is None
    assert reloaded.get_queue(running.id) is not None
