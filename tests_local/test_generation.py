"""Real worker/MCP transport tests with explicitly synthetic model responses."""

import asyncio
import json
import threading
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from local_app.models import ModelError
from tests_local.test_http import service as http_service
from tests_local.test_http import value_of
from tests_local.test_indexing import Embeddings


@pytest.fixture
def service(tmp_path):
    yield from http_service.__wrapped__(tmp_path)


def configured(runtime):
    settings = runtime.models.save_config(
        {
            "profile": {
                "name": "合成测试连接",
                "provider": "ollama",
                "model_id": "synthetic-test-only",
            }
        }
    )
    identity = settings["profiles"][0]["id"]
    runtime.models.save_config({"generation_mode": "independent", "default_profile": identity})
    return identity


def synthetic(snapshot, prompt, on_event=None):
    text = "# 合成测试笔记\n\nalpha 是用于协议回归的合成词。[1]"
    if on_event:
        on_event({"type": "delta", "text": text})
    return {
        "text": text,
        "model": {
            "provider": snapshot["provider"],
            "profile_id": snapshot["id"],
            "model_id": snapshot["model_id"],
            "config_revision": snapshot["config_revision"],
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "metrics": {"total_ms": 1},
    }


def finished(runtime, job_id):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        job = runtime.public_job(job_id)
        if job["status"] in {"succeeded", "failed", "interrupted"}:
            return job
        time.sleep(0.02)
    pytest.fail("任务没有在隔离测试时限内完成")


def test_independent_ingestion_checkpoint_retry_and_staged(service, tmp_path, monkeypatch):
    configured(service)
    vault = tmp_path / "vault"
    vault.mkdir()
    calls = []

    def generate(*args, **kwargs):
        calls.append(args[0])
        result = synthetic(*args, **kwargs)
        result["text"] = "---\ncreated: '1999-01-01'\nstatus: promoted\n---\n" + result["text"]
        return result

    monkeypatch.setattr(service.models, "generate", generate)
    finalize = service.kb.finalize
    fail = [True]

    def save(*args, **kwargs):
        if fail.pop() if fail else False:
            raise OSError("synthetic write failure")
        return finalize(*args, **kwargs)

    monkeypatch.setattr(service.kb, "finalize", save)
    first = service.submit_task(
        "ingest", {"user_input": "alpha", "vault_path": str(vault), "folder": "Inbox"}
    )
    assert finished(service, first["job_id"])["status"] == "failed"
    assert len(calls) == 1 and not list(vault.rglob("*.md"))
    service.jobs.retry(first["job_id"])
    done = finished(service, first["job_id"])
    assert done["status"] == "succeeded"
    assert len(calls) == 1
    note = Path(done["result"]["absolute_path"])
    assert "status: staged" in note.read_text()
    assert done["result"]["note_content"] == note.read_text()
    assert date.today().isoformat() in note.read_text()
    assert "1999-01-01" not in note.read_text()
    assert len(list(vault.rglob("*.md"))) == 1
    assert "checkpoints" not in done and "params" not in done
    session = service.jobs.checkpoint(first["job_id"], "prepared")
    with pytest.raises(ValueError, match="独立模型"):
        service.kb.finalize(session["prepare_id"], "# Host replacement")


def test_query_correlation_generated_results_revalidate_sources(service, tmp_path, monkeypatch):
    configured(service)
    monkeypatch.setattr(service.models, "generate", synthetic)
    service.kb._index.embedding_factory = Embeddings
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "source.md"
    note.write_text("---\nstatus: promoted\n---\n# alpha\nalpha 合成检索资料")
    target = vault / "target.md"
    target.write_text("---\nstatus: promoted\n---\n# alpha target\nalpha 合成目标")
    indexed = service.submit_task("index", {"vault_path": str(vault), "auto_sync": False})
    assert finished(service, indexed["job_id"])["status"] == "succeeded"
    queried = service.submit_task("query", {"question": "alpha", "vault_path": str(vault)})
    linked = service.submit_task(
        "correlation", {"note_path": "target.md", "vault_path": str(vault)}
    )
    for job in (queried, linked):
        result = finished(service, job["job_id"])["result"]
        assert result["answer"] and result["citations"]
        assert not result["prompt_for_host"] and "_validation" not in result
    note.write_text("---\nstatus: staged\n---\nalpha revoked")
    for job in (queried, linked):
        result = service.public_job(job["job_id"])["result"]
        assert result["status"] == "stale_result"
        assert "answer" not in result and "citations" not in result
        assert not service.stream_valid(job["job_id"])


def test_model_failure_no_fallback_or_note(service, tmp_path, monkeypatch):
    configured(service)
    vault = tmp_path / "vault"
    vault.mkdir()

    def fail(*args, **kwargs):
        raise ModelError("authentication_failed", "模型认证失败")

    monkeypatch.setattr(service.models, "generate", fail)
    job = service.submit_task("ingest", {"user_input": "alpha", "vault_path": str(vault)})
    result = finished(service, job["job_id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "authentication_failed"
    assert not list(vault.rglob("*.md"))


def test_running_preview_revoked_even_after_stream_disconnect(service, tmp_path, monkeypatch):
    configured(service)
    service.kb._index.embedding_factory = Embeddings
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "source.md"
    note.write_text("---\nstatus: promoted\n---\nalpha source")
    indexed = service.submit_task("index", {"vault_path": str(vault), "auto_sync": False})
    assert finished(service, indexed["job_id"])["status"] == "succeeded"
    started, release = threading.Event(), threading.Event()

    def slow(snapshot, prompt, on_event=None):
        on_event({"type": "delta", "text": "synthetic preview"})
        started.set()
        assert release.wait(10)
        return synthetic(snapshot, prompt)

    monkeypatch.setattr(service.models, "generate", slow)
    job = service.submit_task("query", {"question": "alpha", "vault_path": str(vault)})
    try:
        assert started.wait(5)
        assert service.jobs.events(job["job_id"])
        note.unlink()
        # The fallback GET path must invalidate a still-running answer as well.
        headers = {"Authorization": "Bearer " + service.auth["ui_token"]}
        with httpx.Client(base_url=service.url, headers=headers, trust_env=False) as client:
            result = client.get("/api/jobs/" + job["job_id"]).json()
        assert result["status"] == "running"
        assert result["result"]["status"] == "stale_result"
        assert service.jobs.events(job["job_id"]) == []
    finally:
        release.set()
    assert finished(service, job["job_id"])["status"] == "failed"


def test_ui_models_tasks_and_sse_auth(service, tmp_path, monkeypatch):
    configured(service)
    monkeypatch.setattr(service.models, "generate", synthetic)
    vault = tmp_path / "vault"
    vault.mkdir()
    headers = {"Authorization": "Bearer " + service.auth["ui_token"]}
    with httpx.Client(base_url=service.url, trust_env=False, headers=headers) as client:
        config = client.get("/api/models").json()
        assert {p["id"] for p in config["providers"]} == {
            "qwen",
            "kimi",
            "glm",
            "deepseek",
            "ollama",
            "custom",
        }
        assert "credential_ref" not in json.dumps(config)
        job = client.post(
            "/api/tasks", json={"kind": "ingest", "user_input": "alpha", "vault_path": str(vault)}
        ).json()
        identity = job["job_id"]
        assert (
            client.get(
                f"/api/jobs/{identity}",
                headers={"Authorization": "Bearer " + service.auth["token"]},
            ).status_code
            == 401
        )
        events = client.get(f"/api/jobs/{identity}/events")
        assert events.status_code == 200 and "text/event-stream" in events.headers["content-type"]
        values = [
            json.loads(line[6:]) for line in events.text.splitlines() if line.startswith("data: ")
        ]
        assert values[-1]["type"] == "result"
        assert values[-1]["job"]["result"]["status"] == "staged"
        assert client.get("/api/jobs/not-a-job").status_code == 404


@pytest.mark.asyncio
async def test_mcp_independent_mode_routes_without_host_generation(service, tmp_path, monkeypatch):
    configured(service)
    monkeypatch.setattr(service.models, "generate", synthetic)
    vault = tmp_path / "vault"
    vault.mkdir()
    headers = {"Authorization": "Bearer " + service.auth["token"]}
    async with httpx.AsyncClient(headers=headers, trust_env=False) as http:
        async with streamable_http_client(service.url + "/mcp", http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                args = {"user_input": "alpha", "vault_path": str(vault)}
                old = value_of(await session.call_tool("ingest_content_prepare", args))
                assert old["status"] == "independent_mode" and "prompt_for_host" not in old
                job = value_of(await session.call_tool("ingest_content", args))
                for _ in range(200):
                    state = value_of(await session.call_tool("get_job", {"job_id": job["job_id"]}))
                    if state["status"] in {"succeeded", "failed"}:
                        break
                    await asyncio.sleep(0.02)
                assert state["status"] == "succeeded"
                assert state["result"]["model"]["provider"] == "ollama"
                prepared = service.jobs.checkpoint(job["job_id"], "prepared")
                blocked = await session.call_tool(
                    "ingest_content_finalize",
                    {"prepare_id": prepared["prepare_id"], "note_content": "host"},
                )
                assert blocked.isError


@pytest.mark.asyncio
async def test_mode_switch_does_not_cancel_old_host_session(service, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    prepared = service.submit_task("ingest", {"user_input": "original", "vault_path": str(vault)})
    configured(service)
    headers = {"Authorization": "Bearer " + service.auth["token"]}
    async with httpx.AsyncClient(headers=headers, trust_env=False) as http:
        async with streamable_http_client(service.url + "/mcp", http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = value_of(
                    await session.call_tool(
                        "ingest_content_finalize",
                        {
                            "prepare_id": prepared["prepare_id"],
                            "note_content": "# Existing Host Task\nOriginal material",
                        },
                    )
                )
                assert result["status"] == "staged"
