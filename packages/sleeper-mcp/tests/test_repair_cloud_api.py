"""REST cloud repair API tests."""

from __future__ import annotations

from sleeper_agent_mcp.repair_cloud_api import (
    CloudApiRunResult,
    _build_create_payload,
    git_info_from_api,
    run_cloud_repair_via_api,
)


def test_build_create_payload_omits_model_for_auto():
    payload = _build_create_payload(
        prompt="fix it",
        repo_url="https://github.com/example/repo",
        starting_ref="main",
        model="auto",
    )
    assert "model" not in payload
    assert payload["repos"][0]["url"] == "https://github.com/example/repo"
    assert payload["workOnCurrentBranch"] is True


def test_git_info_from_api_normalizes_branches():
    git_info = git_info_from_api(
        {
            "branches": [
                {
                    "repoUrl": "github.com/example/repo",
                    "branch": "cursor/fix",
                    "prUrl": "https://github.com/example/repo/pull/1",
                }
            ]
        }
    )
    assert git_info is not None
    assert len(git_info.branches) == 1
    assert git_info.branches[0].repo_url == "github.com/example/repo"
    assert git_info.branches[0].branch == "cursor/fix"


def test_run_cloud_repair_via_api_happy_path(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_request_json(*, method, path, api_key, body=None, timeout=60.0):
        calls.append((method, path))
        if method == "POST" and path == "/v1/agents":
            return {
                "agent": {"id": "bc-1", "latestRunId": "run-1"},
                "run": {"id": "run-1", "status": "RUNNING"},
            }
        if method == "GET":
            return {
                "id": "run-1",
                "agentId": "bc-1",
                "status": "FINISHED",
                "result": "fixed",
                "git": {"branches": [{"repoUrl": "github.com/example/repo", "branch": "main"}]},
            }
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(
        "sleeper_agent_mcp.repair_cloud_api._request_json",
        fake_request_json,
    )
    monkeypatch.setattr("sleeper_agent_mcp.repair_cloud_api.time.sleep", lambda _s: None)

    result = run_cloud_repair_via_api(
        prompt="fix",
        repo_url="https://github.com/example/repo",
        starting_ref="main",
        api_key="key",
        model="auto",
        timeout_seconds=30,
    )
    assert isinstance(result, CloudApiRunResult)
    assert result.status == "FINISHED"
    assert result.agent_id == "bc-1"
    assert calls[0] == ("POST", "/v1/agents")
