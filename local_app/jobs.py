"""A single durable worker; a chat timeout never cancels local work."""

from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from .workspaces import atomic_json, private_dir, read_json


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobNotReady(RuntimeError):
    """Known actionable error. Raw third-party errors must not escape jobs."""


class JobStorageError(RuntimeError):
    """A persistence boundary failed; never expose raw paths or storage errors."""


class JobManager:
    def __init__(self, data_dir: Path):
        self.directory = private_dir(Path(data_dir) / "jobs")
        self._jobs: dict[str, dict] = {}
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._events: dict[str, deque] = {}
        self._event_sequence: dict[str, int] = {}
        for path in sorted(self.directory.glob("*.json")):
            job = read_json(path)
            if not isinstance(job, dict) or job.get("job_id") != path.stem:
                raise ValueError("本地任务状态无效；请保留数据并使用修复功能")
            if job["status"] == "running":
                job.update(
                    status="interrupted",
                    updated_at=_now(),
                    error={
                        "code": "interrupted",
                        "message": "服务曾被中断，请点击重试以继续",
                    },
                )
                atomic_json(path, job)
            self._jobs[job["job_id"]] = job

    def register(self, kind: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[kind] = handler

    def _save(self, job: dict) -> None:
        try:
            atomic_json(self.directory / f"{job['job_id']}.json", job)
        except Exception:
            # Storage backends may include private paths or payloads in errors.
            raise JobStorageError("本地任务状态未能保存，请检查磁盘空间与数据目录权限") from None

    @staticmethod
    def _public(job: dict) -> dict:
        public = deepcopy(
            {
                key: value
                for key, value in job.items()
                if key not in {"params", "dedupe_key", "checkpoints"}
            }
        )
        # Opaque IDs make persisted scope/job association available without
        # leaking input paths, note contents or credentials from task params.
        for source, target, length in (
            ("vault_id", "scope_id", 24),
            ("revision", "scope_revision", 64),
        ):
            value = job.get("params", {}).get(source)
            if (
                isinstance(value, str)
                and len(value) == length
                and re.fullmatch(r"[a-f0-9]+", value)
            ):
                public[target] = value
        return public

    def submit(self, kind: str, params: dict, dedupe_key: str | None = None) -> dict:
        if not isinstance(params, dict):
            raise ValueError("任务参数无效")
        # Roundtrip makes it impossible for a caller to mutate queued parameters.
        params = json.loads(json.dumps(params, ensure_ascii=False, allow_nan=False))
        with self._lock:
            if kind not in self._handlers:
                raise ValueError("未注册的任务类型")
            if dedupe_key:
                for item in self._jobs.values():
                    if (
                        item.get("dedupe_key") == dedupe_key
                        and item["kind"] == kind
                        and item["status"] in {"queued", "running"}
                    ):
                        return self._public(item)
            job = {
                "job_id": uuid.uuid4().hex,
                "kind": kind,
                "params": params,
                "dedupe_key": dedupe_key,
                "status": "queued",
                "created_at": _now(),
                "updated_at": _now(),
                "attempts": 0,
                "progress": {},
            }
            self._save(job)
            self._jobs[job["job_id"]] = job
            if self._thread and self._thread.is_alive():
                self._queue.put(job["job_id"])
            return self._public(job)

    def get(self, job_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError("任务不存在")
            return self._public(self._jobs[job_id])

    def list(self) -> list[dict]:
        with self._lock:
            return [
                self._public(item)
                for item in sorted(
                    self._jobs.values(),
                    key=lambda value: value["created_at"],
                    reverse=True,
                )
            ]

    def retry(self, job_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError("任务不存在")
            job = self._jobs[job_id]
            if job["status"] in {"queued", "running"}:
                return self._public(job)
            if job["status"] == "succeeded":
                return self._public(job)
            if job["kind"] not in self._handlers:
                raise ValueError("此任务类型尚未可用")
            queued = deepcopy(job)
            queued.update(status="queued", updated_at=_now(), progress={})
            queued.pop("error", None)
            queued.pop("result", None)
            queued.pop("state_persisted", None)
            # A failed retry write must not leave an unqueued in-memory job.
            self._save(queued)
            job.clear()
            job.update(queued)
            self._events.pop(job_id, None)
            self._event_sequence.pop(job_id, None)
            if self._thread and self._thread.is_alive():
                self._queue.put(job_id)
            return self._public(job)

    def checkpoint(self, job_id: str, name: str, value=None):
        """Private, credential-free task checkpoints are never public job fields."""
        with self._lock:
            job = self._jobs[job_id]
            if value is not None:
                clean = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
                job.setdefault("checkpoints", {})[name] = clean
                self._save(job)
            return deepcopy(job.get("checkpoints", {}).get(name))

    def events(self, job_id: str, after: int = 0) -> list[dict]:
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError("任务不存在")
            return [deepcopy(e) for e in self._events.get(job_id, []) if e["sequence"] > after]

    def _event(self, job_id: str, event: dict):
        if event.get("type") != "delta" or not isinstance(event.get("text"), str):
            return
        with self._lock:
            sequence = self._event_sequence.get(job_id, 0) + 1
            self._event_sequence[job_id] = sequence
            self._events.setdefault(job_id, deque(maxlen=1024)).append(
                {"type": "delta", "text": event["text"][:16384], "sequence": sequence}
            )

    def clear_events(self, job_id: str):
        with self._lock:
            self._events.pop(job_id, None)

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._queue = queue.Queue()
            for job in self._jobs.values():
                if job["status"] == "queued":
                    self._queue.put(job["job_id"])
            self._thread = threading.Thread(
                target=self._run, name="personal-kb-worker", daemon=True
            )
            self._thread.start()

    def _progress(self, job_id: str, value: dict) -> None:
        # Deliberately omit arbitrary blobs, credentials, task parameters, etc.
        clean = {
            key: val
            for key, val in value.items()
            if key
            in {
                "phase",
                "message",
                "completed",
                "total",
                "percent",
                "notes",
                "chunks",
                "file",
                "downloaded",
                "completed_files",
                "total_files",
            }
            and isinstance(val, (str, int, float, bool))
        }
        for key, val in clean.items():
            if isinstance(val, str):
                clean[key] = val[:300]
        with self._lock:
            job = self._jobs[job_id]
            job.update(progress=clean, updated_at=_now())
            self._save(job)

    def _record_failure(self, job_id: str, exc: Exception) -> None:
        from local_app.models import ModelError

        if isinstance(exc, JobStorageError):
            code = "job_storage_failed"
            message = "任务状态未能可靠保存，请检查磁盘空间和数据目录权限后手动重试。"
        elif isinstance(exc, ModelError):
            code, message = exc.code, str(exc)
        elif isinstance(exc, JobNotReady):
            code, message = "not_ready", "所需组件尚未就绪，请完成组件准备后重试"
        else:
            code = re.sub(r"[^a-zA-Z0-9_]", "", type(exc).__name__)
            message = "任务未完成。请检查组件状态和指定路径后重试；原始资料未更改"
        with self._lock:
            job = self._jobs[job_id]
            job.update(
                status="failed",
                error={"code": code, "message": message},
                updated_at=_now(),
            )
            # Never expose a success result whose durable completion failed.
            # Checkpoints remain available for explicit, idempotent recovery.
            job.pop("result", None)
            job.pop("state_persisted", None)
            try:
                self._save(job)
            except Exception:
                # A failure marker is best effort when the disk is unavailable.
                # Keep the live job terminal and truthful, then serve later jobs.
                job["state_persisted"] = False
                job["error"] = {
                    "code": "job_storage_failed",
                    "message": "任务失败状态未能保存，当前仅在内存标记为失败。"
                    "请修复磁盘空间或数据目录权限后重试；重启后可能显示此前状态。",
                }
            self.clear_events(job_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    job = self._jobs[job_id]
                    if job["status"] != "queued":
                        continue
                    running = deepcopy(job)
                    running.update(
                        status="running", updated_at=_now(), attempts=job["attempts"] + 1
                    )
                    self._save(running)
                    job.clear()
                    job.update(running)
                    handler = self._handlers.get(job["kind"])
                    params = deepcopy(job["params"])
                if handler is None:
                    raise JobNotReady("handler unavailable")

                def progress(value, identity=job_id):
                    self._progress(identity, value)

                progress.event = lambda event, identity=job_id: self._event(identity, event)
                progress.checkpoint = lambda name, value=None, identity=job_id: self.checkpoint(
                    identity, name, value
                )
                result = handler(params, progress)
                result = json.loads(
                    json.dumps(result, ensure_ascii=False, allow_nan=False)
                )
                with self._lock:
                    completed = deepcopy(job)
                    completed.update(status="succeeded", result=result, updated_at=_now())
                    completed.pop("error", None)
                    completed.pop("state_persisted", None)
                    # Publish success only after the completed state is durable.
                    self._save(completed)
                    job.clear()
                    job.update(completed)
            except Exception as exc:
                self._record_failure(job_id, exc)
            finally:
                self._queue.task_done()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
