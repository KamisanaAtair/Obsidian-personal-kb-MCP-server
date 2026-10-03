import json
import threading
import time

import pytest

from local_app.jobs import JobManager, JobStorageError


def wait_for(jobs, identity, statuses=("succeeded", "failed")):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        value = jobs.get(identity)
        if value["status"] in statuses:
            return value
        time.sleep(0.01)
    raise AssertionError("job did not complete")


def test_queued_work_survives_restart_and_hides_private_parameters(tmp_path):
    jobs = JobManager(tmp_path)
    jobs.register("example", lambda params, progress: {"value": params["value"] + 1})
    queued = jobs.submit(
        "example",
        {"value": 2, "api_key": "private-key", "note_content": "private note"},
    )
    assert "params" not in queued and "private-key" not in json.dumps(queued)
    restored = JobManager(tmp_path)
    restored.register(
        "example", lambda params, progress: {"value": params["value"] + 1}
    )
    restored.start()
    try:
        done = wait_for(restored, queued["job_id"])
        assert done["result"] == {"value": 3}
        assert done["attempts"] == 1
        assert "private-key" not in json.dumps(restored.list())
    finally:
        restored.close()


def test_running_job_becomes_interrupted_and_requires_explicit_retry(tmp_path):
    jobs = JobManager(tmp_path)
    jobs.register("example", lambda params, progress: {"done": True})
    queued = jobs.submit("example", {})
    path = tmp_path / "jobs" / f"{queued['job_id']}.json"
    state = json.loads(path.read_text())
    state["status"] = "running"
    path.write_text(json.dumps(state))
    restored = JobManager(tmp_path)
    restored.register("example", lambda params, progress: {"done": True})
    restored.start()
    try:
        assert restored.get(queued["job_id"])["status"] == "interrupted"
        restored.retry(queued["job_id"])
        assert wait_for(restored, queued["job_id"])["result"] == {"done": True}
    finally:
        restored.close()


def test_failure_does_not_leak_exception_text_and_can_retry(tmp_path):
    jobs = JobManager(tmp_path)

    def fail(params, progress):
        raise RuntimeError("secret note and sk-private")

    jobs.register("example", fail)
    queued = jobs.submit("example", {"key": "sk-private"})
    jobs.start()
    try:
        failed = wait_for(jobs, queued["job_id"])
        assert failed["status"] == "failed"
        assert "sk-private" not in json.dumps(failed)
        assert "secret note" not in json.dumps(failed)
        jobs.register("example", lambda params, progress: {"done": True})
        jobs.retry(queued["job_id"])
        done = wait_for(jobs, queued["job_id"])
        assert done["status"] == "succeeded" and done["attempts"] == 2
    finally:
        jobs.close()


def test_single_worker_dedupes_and_preserves_progress(tmp_path):
    jobs = JobManager(tmp_path)
    release, started = threading.Event(), threading.Event()
    active = []

    def work(params, progress):
        active.append(params["id"])
        progress(
            {"phase": "working", "completed": 1, "note_content": "must not appear"}
        )
        started.set()
        release.wait(3)
        return {"done": True}

    jobs.register("example", work)
    one = jobs.submit("example", {"id": 1}, "same")
    assert jobs.submit("example", {"id": 999}, "same")["job_id"] == one["job_id"]
    two = jobs.submit("example", {"id": 2})
    jobs.start()
    try:
        assert started.wait(2)
        assert active == [1]
        assert jobs.get(two["job_id"])["status"] == "queued"
        assert jobs.get(one["job_id"])["progress"] == {
            "phase": "working",
            "completed": 1,
        }
        release.set()
        assert wait_for(jobs, two["job_id"])["status"] == "succeeded"
        assert active == [1, 2]
    finally:
        release.set()
        jobs.close()


def test_running_state_write_failure_stops_only_affected_job(tmp_path, monkeypatch):
    import local_app.jobs as job_module

    jobs = JobManager(tmp_path)
    invoked = []
    jobs.register("example", lambda params, progress: invoked.append(params["id"]) or {"ok": True})
    first = jobs.submit("example", {"id": 1})
    second = jobs.submit("example", {"id": 2})
    original = job_module.atomic_json

    def fail_running(path, value):
        if value.get("job_id") == first["job_id"] and value.get("status") == "running":
            raise OSError("synthetic private storage path and key")
        return original(path, value)

    monkeypatch.setattr(job_module, "atomic_json", fail_running)
    jobs.start()
    try:
        failed = wait_for(jobs, first["job_id"])
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "job_storage_failed"
        assert "synthetic private" not in json.dumps(failed)
        assert "result" not in failed
        assert wait_for(jobs, second["job_id"])["status"] == "succeeded"
        assert invoked == [2]
        assert jobs._thread.is_alive()
        assert jobs._queue.unfinished_tasks == 0
    finally:
        jobs.close()


def test_error_state_write_failure_stays_visible_and_worker_continues(tmp_path, monkeypatch):
    import local_app.jobs as job_module

    jobs = JobManager(tmp_path)

    def handler(params, progress):
        if params["fail"]:
            progress.event({"type": "delta", "text": "synthetic unfinished preview"})
            raise RuntimeError("synthetic private provider failure")
        return {"ok": True}

    jobs.register("example", handler)
    first = jobs.submit("example", {"fail": True})
    second = jobs.submit("example", {"fail": False})
    original = job_module.atomic_json

    def fail_error(path, value):
        if value.get("job_id") == first["job_id"] and value.get("status") == "failed":
            raise OSError("synthetic private failing persistence")
        return original(path, value)

    monkeypatch.setattr(job_module, "atomic_json", fail_error)
    jobs.start()
    try:
        failed = wait_for(jobs, first["job_id"])
        assert failed["error"]["code"] == "job_storage_failed"
        assert failed["state_persisted"] is False
        assert "未能保存" in failed["error"]["message"]
        assert "synthetic private" not in json.dumps(failed)
        assert "result" not in failed and jobs.events(first["job_id"]) == []
        assert wait_for(jobs, second["job_id"])["status"] == "succeeded"
        assert jobs._thread.is_alive()
        persisted = json.loads((jobs.directory / (first["job_id"] + ".json")).read_text())
        assert persisted["status"] == "running"
    finally:
        jobs.close()
    restored = JobManager(tmp_path)
    assert restored.get(first["job_id"])["status"] == "interrupted"


def test_success_write_failure_reuses_durable_checkpoint_on_manual_retry(tmp_path, monkeypatch):
    import local_app.jobs as job_module

    jobs = JobManager(tmp_path)
    generated = []

    def handler(params, progress):
        checkpoint = progress.checkpoint("generated")
        if checkpoint is None:
            generated.append(params["id"])
            checkpoint = {"text": "synthetic generated note"}
            progress.checkpoint("generated", checkpoint)
        return checkpoint

    jobs.register("example", handler)
    first = jobs.submit("example", {"id": 1})
    second = jobs.submit("example", {"id": 2})
    original = job_module.atomic_json
    fail_once = [True]

    def fail_success(path, value):
        if (value.get("job_id") == first["job_id"]
                and value.get("status") == "succeeded" and fail_once):
            fail_once.pop()
            raise OSError("synthetic storage failure")
        return original(path, value)

    monkeypatch.setattr(job_module, "atomic_json", fail_success)
    jobs.start()
    try:
        failed = wait_for(jobs, first["job_id"])
        assert failed["status"] == "failed" and "result" not in failed
        assert failed["error"]["code"] == "job_storage_failed"
        assert wait_for(jobs, second["job_id"])["status"] == "succeeded"
        jobs.retry(first["job_id"])
        assert wait_for(jobs, first["job_id"])["status"] == "succeeded"
        assert generated == [1, 2]
        persisted = json.loads((jobs.directory / (first["job_id"] + ".json")).read_text())
        assert persisted["checkpoints"]["generated"]["text"] == "synthetic generated note"
    finally:
        jobs.close()


def test_progress_callbacks_remain_bound_to_original_job(tmp_path):
    jobs = JobManager(tmp_path)
    callbacks = []
    second_started, release = threading.Event(), threading.Event()

    def handler(params, progress):
        callbacks.append(progress)
        if params["id"] == 2:
            second_started.set()
            assert release.wait(3)
        return {"ok": True}

    jobs.register("example", handler)
    first = jobs.submit("example", {"id": 1})
    second = jobs.submit("example", {"id": 2})
    jobs.start()
    try:
        assert second_started.wait(3)
        callbacks[0]({"message": "original task update"})
        callbacks[0].event({"type": "delta", "text": "original task event"})
        callbacks[0].checkpoint("original", {"id": 1})
        assert jobs.get(first["job_id"])["progress"]["message"] == "original task update"
        assert jobs.events(first["job_id"])[0]["text"] == "original task event"
        assert jobs.checkpoint(first["job_id"], "original") == {"id": 1}
        assert jobs.get(second["job_id"])["progress"] == {}
        assert jobs.events(second["job_id"]) == []
        assert jobs.checkpoint(second["job_id"], "original") is None
        release.set()
        assert wait_for(jobs, second["job_id"])["status"] == "succeeded"
    finally:
        release.set()
        jobs.close()



def test_retry_write_failure_preserves_terminal_state_until_storage_recovers(tmp_path, monkeypatch):
    import local_app.jobs as job_module

    jobs = JobManager(tmp_path)
    jobs.register("example", lambda params, progress: {"ok": True})
    original = job_module.atomic_json
    first = jobs.submit("example", {})

    def fail_running(path, value):
        if value.get("status") == "running":
            raise OSError("synthetic write failure")
        return original(path, value)

    monkeypatch.setattr(job_module, "atomic_json", fail_running)
    jobs.start()
    try:
        assert wait_for(jobs, first["job_id"])["status"] == "failed"

        def fail_queued(path, value):
            if value.get("status") == "queued":
                raise OSError("synthetic private path")
            return original(path, value)

        monkeypatch.setattr(job_module, "atomic_json", fail_queued)
        with pytest.raises(JobStorageError, match="本地任务状态未能保存"):
            jobs.retry(first["job_id"])
        assert jobs.get(first["job_id"])["status"] == "failed"
        assert jobs._queue.unfinished_tasks == 0
        monkeypatch.setattr(job_module, "atomic_json", original)
        jobs.retry(first["job_id"])
        assert wait_for(jobs, first["job_id"])["status"] == "succeeded"
    finally:
        jobs.close()
