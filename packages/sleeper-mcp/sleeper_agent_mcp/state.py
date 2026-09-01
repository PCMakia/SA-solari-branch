"""Thread-safe queue tracking and retry state manager."""

from __future__ import annotations

import copy
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

DEFAULT_MAX_RETRIES = 3
DEFAULT_STATE_DIR = Path.home() / ".sleeper_agent"
DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / "queue_state.json"


def resolve_path(path: str | Path) -> Path:
    """Normalize any filesystem path to an absolute resolved path."""
    return Path(path).expanduser().resolve()


class QueueStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    STOPPED_BY_USER = "STOPPED_BY_USER"


class StreamMode(str, Enum):
    SEQUENTIAL = "sequential"
    CONCURRENT = "concurrent"


@dataclass
class TaskSpec:
    id: str
    command: str
    args: list[str] = field(default_factory=list)
    runtime: str = "sandbox"
    url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSpec:
        return cls(
            id=str(data["id"]),
            command=str(data["command"]),
            args=[str(a) for a in data.get("args", [])],
            runtime=str(data.get("runtime", "sandbox")),
            url=data.get("url"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "command": self.command,
            "args": self.args,
            "runtime": self.runtime,
        }
        if self.url:
            payload["url"] = self.url
        return payload


@dataclass
class HistoryEntry:
    task_id: str
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueueRecord:
    id: str
    status: QueueStatus
    tasks: list[TaskSpec]
    current_step_index: int = 0
    retry_counts: dict[str, int] = field(default_factory=dict)
    history: list[HistoryEntry] = field(default_factory=list)
    workspace: str = ""
    last_error: dict[str, Any] | None = None
    max_retries: int = DEFAULT_MAX_RETRIES
    parent_queue_id: str | None = None
    stream_mode: StreamMode = StreamMode.SEQUENTIAL
    label: str | None = None
    repair_model: str | None = None
    repair_mode: str | None = None
    repair_history: list[dict[str, Any]] = field(default_factory=list)
    repair_timeout_seconds: int | None = None
    orchestrator_timeout_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "status": self.status.value,
            "tasks": [t.to_dict() for t in self.tasks],
            "current_step_index": self.current_step_index,
            "retry_counts": self.retry_counts,
            "history": [h.to_dict() for h in self.history],
            "workspace": self.workspace,
            "last_error": self.last_error,
            "max_retries": self.max_retries,
            "parent_queue_id": self.parent_queue_id,
            "stream_mode": self.stream_mode.value,
        }
        if self.label:
            payload["label"] = self.label
        if self.repair_model:
            payload["repair_model"] = self.repair_model
        if self.repair_mode:
            payload["repair_mode"] = self.repair_mode
        if self.repair_history:
            payload["repair_history"] = self.repair_history
        if self.repair_timeout_seconds is not None:
            payload["repair_timeout_seconds"] = self.repair_timeout_seconds
        if self.orchestrator_timeout_seconds is not None:
            payload["orchestrator_timeout_seconds"] = self.orchestrator_timeout_seconds
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueueRecord:
        return cls(
            id=data["id"],
            status=QueueStatus(data["status"]),
            tasks=[TaskSpec.from_dict(t) for t in data["tasks"]],
            current_step_index=int(data.get("current_step_index", 0)),
            retry_counts={
                str(k): int(v) for k, v in data.get("retry_counts", {}).items()
            },
            history=[HistoryEntry(**entry) for entry in data.get("history", [])],
            workspace=str(data.get("workspace", "")),
            last_error=data.get("last_error"),
            max_retries=int(data.get("max_retries", DEFAULT_MAX_RETRIES)),
            parent_queue_id=data.get("parent_queue_id"),
            stream_mode=StreamMode(data.get("stream_mode", StreamMode.SEQUENTIAL.value)),
            label=data.get("label"),
            repair_model=data.get("repair_model"),
            repair_mode=data.get("repair_mode"),
            repair_history=list(data.get("repair_history", [])),
            repair_timeout_seconds=data.get("repair_timeout_seconds"),
            orchestrator_timeout_seconds=data.get("orchestrator_timeout_seconds"),
        )


class StateManager:
    """Thread-safe queue state backed by an in-memory cache and JSON file."""

    def __init__(self, state_file: Path | str | None = None) -> None:
        self._state_file = resolve_path(state_file or DEFAULT_STATE_FILE)
        self._lock = threading.Lock()
        self._queues: dict[str, QueueRecord] = {}
        self._active_workers: set[str] = set()
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self._state_file.exists():
                return
            try:
                raw = json.loads(self._state_file.read_text(encoding="utf-8"))
                for queue_id, payload in raw.get("queues", {}).items():
                    record = QueueRecord.from_dict(payload)
                    if record.workspace:
                        record.workspace = str(resolve_path(record.workspace))
                    self._queues[queue_id] = record
            except (json.JSONDecodeError, KeyError, ValueError):
                self._queues = {}

    def _save_unlocked(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"queues": {qid: q.to_dict() for qid, q in self._queues.items()}}
        self._state_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def create_queue(
        self,
        tasks: list[TaskSpec],
        workspace: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        *,
        parent_queue_id: str | None = None,
        stream_mode: StreamMode = StreamMode.SEQUENTIAL,
        label: str | None = None,
        repair_model: str | None = None,
        repair_mode: str | None = None,
        repair_timeout_seconds: int | None = None,
        orchestrator_timeout_seconds: int | None = None,
    ) -> QueueRecord:
        queue_id = str(uuid.uuid4())
        workspace_resolved = str(resolve_path(workspace))
        retry_counts = {task.id: 0 for task in tasks}
        record = QueueRecord(
            id=queue_id,
            status=QueueStatus.PENDING,
            tasks=tasks,
            retry_counts=retry_counts,
            workspace=workspace_resolved,
            max_retries=max_retries,
            parent_queue_id=parent_queue_id,
            stream_mode=stream_mode,
            label=label,
            repair_model=repair_model,
            repair_mode=repair_mode,
            repair_timeout_seconds=repair_timeout_seconds,
            orchestrator_timeout_seconds=orchestrator_timeout_seconds,
        )
        with self._lock:
            self._queues[queue_id] = record
            self._save_unlocked()
        return copy.deepcopy(record)

    def get_queue(self, queue_id: str) -> QueueRecord | None:
        with self._lock:
            record = self._queues.get(queue_id)
            return copy.deepcopy(record) if record else None

    def update_queue(self, record: QueueRecord) -> None:
        if record.workspace:
            record.workspace = str(resolve_path(record.workspace))
        with self._lock:
            self._queues[record.id] = copy.deepcopy(record)
            self._save_unlocked()

    def modify_queue(
        self,
        queue_id: str,
        modifier: Callable[[QueueRecord], None],
    ) -> QueueRecord | None:
        with self._lock:
            record = self._queues.get(queue_id)
            if record is None:
                return None
            modifier(record)
            if record.workspace:
                record.workspace = str(resolve_path(record.workspace))
            self._queues[queue_id] = record
            self._save_unlocked()
            return copy.deepcopy(record)

    def append_tasks(self, queue_id: str, tasks: list[TaskSpec]) -> QueueRecord | None:
        def _append(record: QueueRecord) -> None:
            record.tasks.extend(tasks)
            for task in tasks:
                record.retry_counts[task.id] = 0

        return self.modify_queue(queue_id, _append)

    def list_queues(self) -> list[QueueRecord]:
        with self._lock:
            return copy.deepcopy(list(self._queues.values()))

    def prune_non_running_queues(self) -> int:
        """Remove finished/stale queues so the dashboard focuses on the new session."""
        with self._lock:
            stale_ids = [
                qid
                for qid, record in self._queues.items()
                if record.status != QueueStatus.RUNNING
            ]
            for qid in stale_ids:
                del self._queues[qid]
            if stale_ids:
                self._save_unlocked()
            return len(stale_ids)

    def register_worker(self, queue_id: str) -> None:
        with self._lock:
            self._active_workers.add(queue_id)

    def unregister_worker(self, queue_id: str) -> None:
        with self._lock:
            self._active_workers.discard(queue_id)

    def active_worker_count(self) -> int:
        with self._lock:
            return len(self._active_workers)

    def active_worker_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._active_workers)

    def count_running_streams(self) -> int:
        """Count queues currently executing (RUNNING status or registered workers)."""
        with self._lock:
            running_queues = sum(
                1 for q in self._queues.values() if q.status == QueueStatus.RUNNING
            )
            return max(running_queues, len(self._active_workers))

    def get_status_snapshot(self, queue_id: str) -> dict[str, Any]:
        record = self.get_queue(queue_id)
        if record is None:
            raise KeyError(f"Queue not found: {queue_id}")

        active_step = None
        if record.current_step_index < len(record.tasks):
            active_step = record.tasks[record.current_step_index].to_dict()

        remaining = [
            t.to_dict() for t in record.tasks[record.current_step_index + 1 :]
        ]

        return {
            "queue_id": record.id,
            "status": record.status.value,
            "workspace": record.workspace,
            "active_step": active_step,
            "active_step_index": record.current_step_index,
            "remaining_steps": remaining,
            "retry_counts": dict(record.retry_counts),
            "max_retries": record.max_retries,
            "history": [h.to_dict() for h in record.history],
            "last_error": record.last_error,
            "parent_queue_id": record.parent_queue_id,
            "stream_mode": record.stream_mode.value,
            "repair_model": record.repair_model,
            "repair_mode": record.repair_mode,
            "repair_history": list(record.repair_history),
            "repair_timeout_seconds": record.repair_timeout_seconds,
            "orchestrator_timeout_seconds": record.orchestrator_timeout_seconds,
        }

    def get_all_queues_summary(self) -> dict[str, list[dict[str, Any]]]:
        buckets: dict[str, list[dict[str, Any]]] = {
            "active": [],
            "queued": [],
            "concurrent": [],
            "needs_repair": [],
            "completed": [],
            "aborted": [],
            "stopped": [],
        }
        for record in self.list_queues():
            summary = {
                "queue_id": record.id,
                "status": record.status.value,
                "stream_mode": record.stream_mode.value,
                "parent_queue_id": record.parent_queue_id,
                "workspace": record.workspace,
                "active_step_index": record.current_step_index,
                "total_steps": len(record.tasks),
                "retry_counts": dict(record.retry_counts),
            }
            if record.stream_mode == StreamMode.CONCURRENT:
                buckets["concurrent"].append(summary)
            elif record.status == QueueStatus.RUNNING:
                buckets["active"].append(summary)
            elif record.status == QueueStatus.PENDING:
                buckets["queued"].append(summary)
            elif record.status == QueueStatus.NEEDS_REPAIR:
                buckets["needs_repair"].append(summary)
            elif record.status == QueueStatus.COMPLETED:
                buckets["completed"].append(summary)
            elif record.status == QueueStatus.ABORTED:
                buckets["aborted"].append(summary)
            elif record.status == QueueStatus.STOPPED_BY_USER:
                buckets["stopped"].append(summary)
        return buckets
