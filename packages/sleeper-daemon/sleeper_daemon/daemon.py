"""Local Sleeper daemon orchestrating Cursor chat + MCP event queue."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sleeper_agent_mcp.local_control import resume_afk_queue, update_queue_tasks
from sleeper_agent_mcp.orchestrator import record_daemon_repair_attempt
from sleeper_agent_mcp.sleeper_events import (
    EVENT_AWAITING_DAEMON,
    EVENT_QUEUE_ABORTED,
    EVENT_QUEUE_COMPLETED,
    EVENT_QUEUE_STARTED,
    cursor_response_path,
    read_events_after,
)
from sleeper_agent_mcp.sleeper_input import (
    extract_sleeper_call_body,
    format_kickoff_prompt,
    format_repair_prompt,
    parse_tasks_from_payload,
    tasks_equal,
)
from sleeper_agent_mcp.state import DEFAULT_STATE_FILE, StateManager
from sleeper_agent_mcp.workspace_scope import resolve_target_workspace

from sleeper_daemon.cursor_driver import CursorChatDriver, build_cursor_driver
from sleeper_daemon.dashboard import build_dashboard_url, prepare_dashboard_for_session
from sleeper_daemon.windows import get_active_cursor_windows


INPUT_FILE_NAME = ".sleeper_input"
TERMINAL_EVENTS = frozenset(
    {EVENT_QUEUE_COMPLETED, EVENT_QUEUE_ABORTED, "QUEUE_STOPPED"}
)


@dataclass
class DaemonConfig:
    workspace: str
    poll_seconds: float = 1.0
    turn_timeout_seconds: float = 900.0
    driver_name: str | None = None
    window_title: str | None = None


class SleeperDaemon:
    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        self.workspace = str(resolve_target_workspace(config.workspace))
        self.state = StateManager(DEFAULT_STATE_FILE)
        self.cursor: CursorChatDriver = build_cursor_driver(
            config.driver_name,
            window_title=config.window_title,
        )
        self._event_offset = 0
        self._active_queue_id: str | None = None
        self._dashboard_opened_urls: set[str] = set()

    def _log(self, message: str) -> None:
        sys.stdout.write(f"[sleeper] {message}\n")
        sys.stdout.flush()

    def list_cursor_windows(self) -> list[dict[str, Any]]:
        return [
            {"hwnd": window.hwnd, "title": window.title, "pid": window.pid}
            for window in get_active_cursor_windows()
        ]

    def _prepare_dashboard(
        self,
        *,
        queue_id: str | None = None,
        open_browser: bool = True,
        refocus: bool = False,
    ) -> bool:
        return prepare_dashboard_for_session(
            self.workspace,
            self.cursor,
            queue_id=queue_id,
            log=self._log,
            open_browser=open_browser,
            refocus=refocus,
            opened_urls=self._dashboard_opened_urls,
        )

    def run_payload(self, raw_text: str, *, label: str = "sleeper-session") -> None:
        body = extract_sleeper_call_body(raw_text)
        tasks = parse_tasks_from_payload(body)
        self._log(f"kickoff label={label} tasks={len(tasks) if tasks else 'unparsed'}")
        self._dashboard_opened_urls.clear()
        # Start dashboard + open browser once. Do not refocus here — send_message
        # activates chat input; extra window activates collapse the Agent panel.
        self._prepare_dashboard(queue_id=None, open_browser=True, refocus=False)
        prompt = format_kickoff_prompt(
            workspace=self.workspace,
            payload=body,
            tasks=tasks,
            label=label,
            dashboard_url=build_dashboard_url(None),
        )
        self.cursor.send_message(prompt)
        self.cursor.wait_for_turn_complete(timeout_seconds=self.config.turn_timeout_seconds)
        self._watch_until_terminal()

    def watch_input_file(self) -> None:
        input_path = Path(self.workspace) / INPUT_FILE_NAME
        self._log(f"watching {input_path}")
        self._log("idle until that file is created or updated. Ctrl+C to stop.")
        windows = self.list_cursor_windows()
        if windows:
            titles = ", ".join(f'"{w["title"]}"' for w in windows)
            self._log(f"Cursor windows: {titles}")
        else:
            self._log("no Cursor windows found yet")
        wanted = (self.config.window_title or "").strip()
        if wanted:
            match = next(
                (w for w in windows if wanted.lower() in str(w["title"]).lower()),
                None,
            )
            if match:
                self._log(f'window-title "{wanted}" matched "{match["title"]}"')
            else:
                self._log(
                    f'window-title "{wanted}" matched nothing. '
                    "Use a substring from `python sleeper_daemon.py windows` "
                    '(example: "Solari").'
                )

        last_mtime = 0.0
        while True:
            if input_path.is_file():
                mtime = input_path.stat().st_mtime
                if mtime > last_mtime:
                    last_mtime = mtime
                    payload = input_path.read_text(encoding="utf-8")
                    self._log(f"read {input_path.name} ({len(payload)} chars); kicking off Cursor")
                    self.run_payload(payload)
                    self._log("payload finished; watching for next update")
            time.sleep(self.config.poll_seconds)

    def _watch_until_terminal(self) -> None:
        while True:
            events, self._event_offset = read_events_after(self.workspace, self._event_offset)
            for event in events:
                self._handle_event(event)
                if event.get("type") in TERMINAL_EVENTS:
                    return
            time.sleep(self.config.poll_seconds)

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        payload = event.get("payload") or {}
        if event_type == EVENT_QUEUE_STARTED:
            self._active_queue_id = str(payload.get("queue_id") or "")
            if self._active_queue_id:
                # Refresh deep-link metadata only — do not reopen IDE/browser
                # (second Simple Browser open + --classic collapses Agent panel).
                self._prepare_dashboard(
                    queue_id=self._active_queue_id,
                    open_browser=True,
                    refocus=False,
                )
            return
        if event_type != EVENT_AWAITING_DAEMON:
            return

        queue_id = str(payload.get("queue_id") or self._active_queue_id or "")
        task_id = str(payload.get("task_id") or "")
        error_message = str(payload.get("error_message") or "")
        if not queue_id:
            return

        # Keep dashboard alive but do not reopen the browser or thrash focus.
        self._prepare_dashboard(queue_id=queue_id, open_browser=False, refocus=False)
        repair_prompt = format_repair_prompt(
            workspace=self.workspace,
            error_message=error_message,
            task_id=task_id,
            queue_id=queue_id,
        )
        self.cursor.send_message(repair_prompt)
        self.cursor.wait_for_turn_complete(timeout_seconds=self.config.turn_timeout_seconds)
        cursor_response = self._read_cursor_response()
        record_daemon_repair_attempt(
            self.state,
            queue_id,
            task_id=task_id,
            cursor_response=cursor_response,
            utc_now=lambda: datetime.now(timezone.utc).isoformat(),
        )
        self._resume_after_repair(queue_id, cursor_response)

    def _read_cursor_response(self) -> str:
        path = cursor_response_path(self.workspace)
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return ""

    def _resume_after_repair(self, queue_id: str, cursor_response: str) -> None:
        record = self.state.get_queue(queue_id)
        if record is None:
            return

        new_tasks = parse_tasks_from_payload(cursor_response)
        current_tasks = [task.to_dict() for task in record.tasks]
        if new_tasks and not tasks_equal(new_tasks, current_tasks):
            update_queue_tasks(self.state, queue_id, new_tasks)
        resume_afk_queue(self.state, queue_id)
        self._watch_until_terminal()
