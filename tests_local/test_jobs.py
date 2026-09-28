import json
import threading
import time

from local_app.jobs import JobManager


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
