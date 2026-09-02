"""Tests for global ~/.cursor/mcp.json env loading."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sleeper_agent_mcp import mcp_config


@pytest.fixture
def global_mcp_json(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp.json"
    monkeypatch.setattr(mcp_config, "global_mcp_config_path", lambda: config_path)
    return config_path


def test_reload_applies_env_from_global_config(global_mcp_json, monkeypatch):
    global_mcp_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sleeper-agent-mcp": {
                        "command": "python",
                        "args": ["-m", "sleeper_agent_mcp.server"],
                        "env": {
                            "CURSOR_API_KEY": "cursor_test_key",
                            "SOLARI_API_KEY": "slr_live_test",
                            "SLEEPER_BACKEND": "solari",
                            "SLEEPER_REPAIR_MODEL": "auto",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("SOLARI_API_KEY", raising=False)

    result = mcp_config.reload_global_mcp_env(apply=True)

    assert result.status == "RELOADED"
    assert result.server_key == "sleeper-agent-mcp"
    assert os.environ["CURSOR_API_KEY"] == "cursor_test_key"
    assert os.environ["SOLARI_API_KEY"] == "slr_live_test"
    assert os.environ["SLEEPER_REPAIR_MODEL"] == "auto"


def test_reload_reports_missing_cursor_api_key(global_mcp_json):
    global_mcp_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sleeper-agent-mcp": {
                        "env": {
                            "SLEEPER_BACKEND": "solari",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = mcp_config.reload_global_mcp_env(apply=True)

    assert result.status == "RELOADED_WITH_WARNINGS"
    assert "CURSOR_API_KEY" in result.missing_required
    assert "SOLARI_API_KEY" in result.missing_required


def test_reload_errors_when_config_missing(global_mcp_json):
    result = mcp_config.reload_global_mcp_env(apply=True)

    assert result.status == "ERROR"
    assert result.error is not None
    assert "not found" in result.error.lower()


def test_consume_reload_request_applies_env(global_mcp_json, tmp_path, monkeypatch):
    global_mcp_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sleeper-agent-mcp": {
                        "env": {
                            "CURSOR_API_KEY": "cursor_from_request",
                            "SLEEPER_BACKEND": "solari",
                            "SOLARI_API_KEY": "slr_live_test",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "reload.request"
    monkeypatch.setattr(mcp_config, "reload_request_path", lambda: request_path)
    monkeypatch.setattr(
        mcp_config, "reload_status_path", lambda: tmp_path / "status.json"
    )
    request_path.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)

    result = mcp_config.consume_reload_request_if_present()

    assert result is not None
    assert result.status == "RELOADED"
    assert os.environ["CURSOR_API_KEY"] == "cursor_from_request"
    assert not request_path.exists()


def test_find_server_by_module_marker(global_mcp_json, monkeypatch):
    global_mcp_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "custom-name": {
                        "args": ["-m", "sleeper_agent_mcp.server"],
                        "env": {"CURSOR_API_KEY": "cursor_ok"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = mcp_config.reload_global_mcp_env(apply=True)

    assert result.status == "RELOADED_WITH_WARNINGS"
    assert result.server_key == "custom-name"
    assert os.environ["CURSOR_API_KEY"] == "cursor_ok"
