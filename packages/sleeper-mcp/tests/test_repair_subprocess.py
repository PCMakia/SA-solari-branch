"""Subprocess-isolated repair runner tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sleeper_agent_mcp.repair_runner import (
    DEFAULT_REPAIR_MODEL,
    RepairTurnResult,
    _cli_main,
    execute_repair_turn_in_process,
    resolve_repair_model,
    spawn_repair_turn,
)


def test_resolve_repair_model_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("SLEEPER_REPAIR_MODEL", raising=False)
    assert resolve_repair_model() == "auto"
    assert DEFAULT_REPAIR_MODEL == "auto"


def test_spawn_repair_turn_parses_success_stdout(tmp_path, monkeypatch):
    ws = str(tmp_path.resolve())
    payload = {
        "workspace": ws,
        "failing_file_path": None,
        "execution_command": "python broken.py",
        "raw_error_traceback": "NameError",
        "repair_model": "auto",
        "repair_mode": "agent",
        "repair_timeout_seconds": 30,
    }
    stdout = json.dumps(
        RepairTurnResult(
            status="finished",
            outcome="SUCCESS",
            finished=True,
            workspace_cwd=ws,
        ).to_dict()
    )

    def fake_run(command, **kwargs):
        assert command[0] == sys.executable
        assert "-m" in command
        assert "sleeper_agent_mcp.repair_runner" in command
        assert "--result-file" in command
        assert kwargs["cwd"] == ws
        result_index = command.index("--result-file") + 1
        Path(command[result_index]).write_text(stdout, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("sleeper_agent_mcp.repair_runner.subprocess.run", fake_run)

    result = spawn_repair_turn(
        workspace=ws,
        failing_file_path=None,
        execution_command="python broken.py",
        raw_error_traceback="NameError",
        repair_timeout_seconds=30,
    )

    assert result.outcome == "SUCCESS"
    assert result.finished is True
    assert result.workspace_cwd == ws


def test_spawn_repair_turn_handles_timeout(tmp_path, monkeypatch):
    ws = str(tmp_path.resolve())

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["repair"], timeout=5)

    monkeypatch.setattr("sleeper_agent_mcp.repair_runner.subprocess.run", fake_run)

    result = spawn_repair_turn(
        workspace=ws,
        failing_file_path=None,
        execution_command="python broken.py",
        raw_error_traceback="NameError",
        repair_timeout_seconds=5,
    )

    assert result.timed_out is True
    assert result.status == "TIMED_OUT"


def test_cli_main_emits_json(tmp_path, monkeypatch):
    ws = str(tmp_path.resolve())
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(
        json.dumps(
            {
                "workspace": ws,
                "execution_command": "python x.py",
                "raw_error_traceback": "err",
            }
        ),
        encoding="utf-8",
    )

    fake_result = RepairTurnResult(
        status="finished",
        outcome="SUCCESS",
        finished=True,
        workspace_cwd=ws,
    )
    monkeypatch.setattr(
        "sleeper_agent_mcp.repair_runner.execute_repair_turn_in_process",
        lambda _payload: fake_result,
    )

    exit_code = _cli_main(
        ["--workspace", ws, "--payload-file", str(payload_file), "--result-file", str(tmp_path / "out.json")]
    )
    assert exit_code == 0
    assert (tmp_path / "out.json").is_file()


def test_execute_repair_turn_missing_api_key(tmp_path, monkeypatch):
    ws = str(tmp_path.resolve())
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr(
        "sleeper_agent_mcp.repair_runner._resolve_api_key",
        lambda: "",
    )

    result = execute_repair_turn_in_process(
        {
            "workspace": ws,
            "execution_command": "python x.py",
            "raw_error_traceback": "boom",
        }
    )
    assert result.outcome == "FAILED"
    assert result.sdk_failed is True
