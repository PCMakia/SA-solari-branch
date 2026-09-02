"""Tests for repair prompt building and guardrails."""

from sleeper_agent_mcp.repair_runner import (
    REPAIR_GUARDRAIL,
    build_repair_prompt,
    truncate_traceback,
)


def test_build_repair_prompt_includes_guardrail_and_lean_context(tmp_path):
    ws = str(tmp_path.resolve())
    prompt = build_repair_prompt(
        workspace_cwd=ws,
        failing_file_path=str(tmp_path / "foo.py"),
        execution_command="python foo.py",
        raw_error_traceback="NameError: x",
        repair_mode="agent",
    )
    assert REPAIR_GUARDRAIL in prompt
    assert "start_afk_overseer" in prompt
    assert "foo.py" in prompt
    assert ws in prompt
    assert "python foo.py" in prompt
    assert "NameError: x" in prompt


def test_truncate_traceback_keeps_tail():
    lines = [f"line {i}" for i in range(100)]
    raw = "\n".join(lines)
    truncated = truncate_traceback(raw, max_lines=10)
    assert "line 99" in truncated
    assert "line 0" not in truncated
    assert "omitted" in truncated
