"""Sleeper-call parsing and event queue tests."""

from __future__ import annotations

import json

from sleeper_agent_mcp.sleeper_events import EVENT_STEP_FAILED, append_event, read_events
from sleeper_agent_mcp.sleeper_input import (
    extract_sleeper_call_body,
    parse_tasks_from_payload,
    tasks_equal,
)


def test_extract_sleeper_call_body():
    raw = '"""Sleeper-call\n{"tasks":[{"id":"a","command":"python","args":["x.py"]}]}\n"""'
    body = extract_sleeper_call_body(raw)
    tasks = parse_tasks_from_payload(body)
    assert tasks is not None
    assert tasks[0]["id"] == "a"


def test_events_jsonl_roundtrip(tmp_path):
    ws = str(tmp_path)
    append_event(ws, EVENT_STEP_FAILED, {"task_id": "step-1"})
    events = read_events(ws)
    assert len(events) == 1
    assert events[0]["type"] == EVENT_STEP_FAILED
    assert events[0]["payload"]["task_id"] == "step-1"


def test_tasks_equal_detects_changes():
    left = [{"id": "a", "command": "python", "args": ["x.py"]}]
    right = [{"id": "a", "command": "python", "args": ["y.py"]}]
    assert tasks_equal(left, left)
    assert not tasks_equal(left, right)
