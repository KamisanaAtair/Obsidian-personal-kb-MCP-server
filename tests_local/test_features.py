import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_app.features import FeatureManager, atomic_json, download_verified
from local_app.jobs import JobManager
from local_app.models import MemoryCredentialStore, ModelService


@pytest.fixture
def download_server():
    payload = b"verified-model-part" * 1024
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            value = self.headers.get("Range")
            requests.append(value)
            offset = int(value.split("=")[1].split("-")[0]) if value else 0
            self.send_response(206 if value else 200)
            if value:
                self.send_header(
                    "Content-Range", f"bytes {offset}-{len(payload) - 1}/{len(payload)}"
                )
            body = payload[offset:] if self.path != "/bad" else b"x" * len(payload)
            if self.path == "/short" and not value:
                body = payload[:1024]
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", payload, requests
    server.shutdown()
    server.server_close()
    thread.join()


def test_download_resumes_and_verifies_then_reuses_cache(download_server, tmp_path):
    url, payload, requests = download_server
    target = tmp_path / "model.bin"
    target.with_suffix(".bin.partial").write_bytes(payload[:1024])
    progress = []
    checksum = hashlib.sha256(payload).hexdigest()
    download_verified([url + "/ok"], target, checksum, len(payload), progress.append)
    assert requests == ["bytes=1024-"]
    assert target.read_bytes() == payload
    download_verified([url + "/ok"], target, checksum, len(payload), progress.append)
    assert len(requests) == 1
    assert progress[-1]["phase"] == "cached"


def test_bad_download_never_becomes_ready(download_server, tmp_path, monkeypatch):
    url, payload, _ = download_server
    monkeypatch.setattr("local_app.features.time.sleep", lambda _: None)
    target = tmp_path / "model.bin"
    with pytest.raises(RuntimeError, match="下载未完成"):
        download_verified(
            [url + "/bad"],
            target,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            lambda _: None,
        )
    assert not target.exists()


def test_short_response_retains_bytes_and_retries_with_range(
    download_server, tmp_path, monkeypatch
):
    url, payload, requests = download_server
    monkeypatch.setattr("local_app.features.time.sleep", lambda _: None)
    target = tmp_path / "model.bin"
    download_verified(
        [url + "/short"],
        target,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        lambda _: None,
    )
    assert requests == [None, "bytes=1024-"]
    assert target.read_bytes() == payload


def test_status_never_exposes_key(tmp_path):
    models = ModelService(tmp_path, MemoryCredentialStore())
    try:
        manager = FeatureManager(tmp_path, JobManager(tmp_path), models)
        manager.save_key("synthetic-value-for-local-test")
        assert manager.status()["video"]["key_saved"] is True
        assert "synthetic" not in str(manager.status())
        assert not (tmp_path / "credentials.json").exists()
    finally:
        models.close()


def test_new_runtime_invalidates_shared_readiness_but_keeps_model_cache(tmp_path):
    model = tmp_path / "models" / "bge-m3"
    model.mkdir(parents=True)
    (model / "cached.bin").write_bytes(b"keep")
    atomic_json(
        tmp_path / "features.json",
        {
            "semantic": {
                "ready": True,
                "model_path": str(model),
                "environment": "old-runtime",
            }
        },
    )
    manager = FeatureManager(tmp_path, JobManager(tmp_path))
    assert manager.status()["semantic"]["ready"] is False
    assert manager.status()["semantic"]["phase"] == "needs_prepare"
    assert (model / "cached.bin").read_bytes() == b"keep"


def test_interrupted_feature_is_not_stuck_preparing(tmp_path):
    atomic_json(
        tmp_path / "features.json", {"semantic": {"ready": False, "phase": "preparing"}}
    )
    manager = FeatureManager(tmp_path, JobManager(tmp_path))
    assert manager.status()["semantic"]["phase"] == "interrupted"


def test_deleted_feature_files_enable_repair(tmp_path):
    manager = FeatureManager(tmp_path, JobManager(tmp_path))
    manager._set("video", {"ready": True, "phase": "ready"})
    manager._set(
        "semantic",
        {"ready": True, "phase": "ready", "model_path": str(tmp_path / "missing")},
    )
    state = manager.status()
    assert state["video"]["ready"] is False
    assert state["semantic"]["ready"] is False
