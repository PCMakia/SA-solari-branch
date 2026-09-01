"""MCP server registration smoke tests."""

from __future__ import annotations

import asyncio

from sleeper_agent_mcp.server import SERVER_BUILD, mcp


def test_server_build_is_set():
    assert SERVER_BUILD


def test_expected_tool_count():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "start_afk_overseer",
        "enqueue_sequence",
        "schedule_tasks",
        "execute_queue",
        "get_overseer_status",
        "stop_overseer",
        "clear_overseer_stop",
        "restart_mcp",
        "get_queue_status",
        "resume_queue",
    }


def test_get_queue_status_schema_allows_empty_queue_id():
    tools = asyncio.run(mcp.list_tools())
    status_tool = next(t for t in tools if t.name == "get_queue_status")
    props = status_tool.input_schema.get("properties", {})
    assert "queue_id" in props
    assert "queue_id" not in status_tool.input_schema.get("required", [])
