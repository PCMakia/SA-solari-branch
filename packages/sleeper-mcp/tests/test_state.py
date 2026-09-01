"""State manager persistence tests."""

from __future__ import annotations

import json
from pathlib import Path

from sleeper_agent_mcp.state import QueueStatus, StateManager, TaskSpec


def test_create_and_update_queue(tmp_path: Path):
    state_file = tmp_path / "queue_state.json"
    mgr = StateManager(state_file)

    record = mgr.create_queue(
        tasks=[TaskSpec(id="t1", command="python", args=["-c", "print(1)"])],
        workspace=str(tmp_path),
    )
    assert record.status == QueueStatus.PENDING

    record.status = QueueStatus.COMPLETED
    mgr.update_queue(record)

    reloaded = StateManager(state_file)
    got = reloaded.get_queue(record.id)
    assert got is not None
    assert got.status == QueueStatus.COMPLETED

    raw = json.loads(state_file.read_text(encoding="utf-8"))
    assert record.id in raw["queues"]
