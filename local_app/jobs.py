"""A single durable worker; a chat timeout never cancels local work."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import re
import threading
from typing import Callable
import uuid

from .workspaces import atomic_json, private_dir, read_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobNotReady(RuntimeError):
    """Known actionable error. Raw third-party errors must not escape jobs."""


class JobManager:
    def __init__(self, data_dir: Path):
        self.directory = private_dir(Path(data_dir) / "jobs")
        self._jobs: dict[str, dict] = {}
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
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
        atomic_json(self.directory / f"{job['job_id']}.json", job)

    @staticmethod
    def _public(job: dict) -> dict:
        public = deepcopy(
            {
                key: value
                for key, value in job.items()
                if key not in {"params", "dedupe_key"}
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
            job.update(status="queued", updated_at=_now(), progress={})
            job.pop("error", None)
            self._save(job)
            if self._thread and self._thread.is_alive():
                self._queue.put(job_id)
            return self._public(job)

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

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                job = self._jobs[job_id]
                if job["status"] != "queued":
                    continue
                job.update(
                    status="running", updated_at=_now(), attempts=job["attempts"] + 1
                )
                self._save(job)
                handler = self._handlers.get(job["kind"])
                params = deepcopy(job["params"])
            try:
                if handler is None:
                    raise JobNotReady("handler unavailable")
                result = handler(
                    params,
                    lambda value, identity=job_id: self._progress(identity, value),
                )
                result = json.loads(
                    json.dumps(result, ensure_ascii=False, allow_nan=False)
                )
                with self._lock:
                    job.update(status="succeeded", result=result, updated_at=_now())
                    job.pop("error", None)
                    self._save(job)
            except Exception as exc:
                code = (
                    "not_ready"
                    if isinstance(exc, JobNotReady)
                    else re.sub(r"[^a-zA-Z0-9_]", "", type(exc).__name__)
                )
                message = (
                    "所需组件尚未就绪，请完成组件准备后重试"
                    if isinstance(exc, JobNotReady)
                    else "任务未完成。请检查组件状态和指定路径后重试；原始资料未更改"
                )
                with self._lock:
                    job.update(
                        status="failed",
                        error={"code": code, "message": message},
                        updated_at=_now(),
                    )
                    self._save(job)
            finally:
                self._queue.task_done()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
