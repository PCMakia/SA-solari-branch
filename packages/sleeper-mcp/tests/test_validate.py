"""Validation and task schema tests."""

from __future__ import annotations

import pytest

from sleeper_agent_mcp.execution.validate import validate_command, validate_tasks


def test_validate_command_whitelist():
    assert validate_command("python") == "python"
    assert validate_command("python3") == "python3"
    with pytest.raises(Exception):
        validate_command("bash")


def test_validate_tasks_browser_requires_url():
    with pytest.raises(ValueError, match="url"):
        validate_tasks(
            [
                {
                    "id": "b",
                    "command": "python",
                    "args": [],
                    "runtime": "browser",
                }
            ]
        )


def test_validate_tasks_sandbox_defaults():
    tasks = validate_tasks([{"id": "a", "command": "python", "args": ["-c", "1"]}])
    assert tasks[0]["runtime"] == "sandbox"
    assert tasks[0]["url"] is None
