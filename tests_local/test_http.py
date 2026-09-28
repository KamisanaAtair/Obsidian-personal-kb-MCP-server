"""Exercise the real HTTP MCP protocol against isolated data and notebook folders."""

import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest
import uvicorn

from local_app.server import Runtime, create_app


def value_of(result):
    assert not result.isError
    return result.structuredContent or json.loads(result.content[0].text)


@pytest.fixture
def service(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    runtime = Runtime(tmp_path / "data", port, tmp_path / "workbuddy" / "mcp.json")
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(runtime),
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    yield runtime
    server.should_exit = True
    thread.join(10)
    assert not thread.is_alive()


def test_http_auth_origin_and_configuration_preservation(service):
    runtime = service
    path = runtime.workbuddy_config
    path.parent.mkdir()
    original = {
        "mcpServers": {"existing": {"command": "existing-tool"}},
        "preferences": {"keep": True},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    with httpx.Client(base_url=runtime.url, trust_env=False) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.post("/mcp", json={}).status_code == 401
        headers = {"Authorization": "Bearer " + runtime.auth["ui_token"]}
        assert (
            client.get(
                "/api/status", headers={**headers, "Origin": "https://foreign.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/status", headers={**headers, "Host": "foreign.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/status",
                headers={"Authorization": "Bearer " + runtime.auth["token"]},
            ).status_code
            == 401
        )
        assert client.post("/api/register", headers=headers, json={}).status_code == 200
        installed = json.loads(path.read_text())
        assert installed["preferences"] == original["preferences"]
        assert installed["mcpServers"]["existing"] == original["mcpServers"]["existing"]
        entry = installed["mcpServers"]["obsidian-personal-kb-host"]
        assert entry["url"] == runtime.url + "/mcp"
        assert entry["type"] == "streamableHttp"
        assert (
            client.post("/api/register", headers=headers, json={}).json()["noop"]
            is True
        )
        state = client.get("/api/status", headers=headers).json()
        assert state["registration"]["saved"] is True
        assert (
            state["mcp"]["last_activity"] is None
        )  # Saving configuration does not imply trust.
        assert "token" not in json.dumps(state)


@pytest.mark.asyncio
async def test_real_sdk_handshake_text_save_and_background_status(service, tmp_path):
    runtime = service
    vault = tmp_path / "用户笔记库"
    vault.mkdir()
    headers = {"Authorization": "Bearer " + runtime.auth["token"]}
    async with httpx.AsyncClient(headers=headers, trust_env=False) as http:
        async with streamable_http_client(runtime.url + "/mcp", http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "personal-kb-local"
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {
                    "get_status",
                    "ingest_content_prepare",
                    "ingest_content_finalize",
                    "start_index",
                    "query_kb",
                    "get_job",
                } <= names
                prepared = await session.call_tool(
                    "ingest_content_prepare",
                    {
                        "user_input": "今天学习了增量索引。",
                        "vault_path": str(vault),
                        "folder": "技术/检索",
                    },
                )
                assert not prepared.isError
                value = value_of(prepared)
                saved = await session.call_tool(
                    "ingest_content_finalize",
                    {
                        "prepare_id": value["prepare_id"],
                        "note_content": "---\nstatus: promoted\n---\n# 增量索引\n只处理变化的文件。",
                    },
                )
                assert not saved.isError
                result = value_of(saved)
                note = Path(result["absolute_path"])
                assert note.parent == vault / "技术" / "检索"
                assert "status: staged" in note.read_text()
                assert runtime.kb.status()["scopes"] == []
                query = value_of(
                    await session.call_tool(
                        "query_kb",
                        {"question": "增量索引是什么？", "vault_path": str(vault)},
                    )
                )
                for _ in range(100):
                    job = value_of(
                        await session.call_tool("get_job", {"job_id": query["job_id"]})
                    )
                    if job["status"] in {"succeeded", "failed"}:
                        break
                    await asyncio.sleep(0.02)
                assert job["status"] == "succeeded"
                assert job["result"]["status"] == "not_indexed"
                assert runtime.last_mcp_activity is not None
                assert all("result" not in item for item in runtime.status()["jobs"])


def test_basic_server_import_does_not_load_heavy_components():
    code = "import local_app.server, sys; assert not {'torch','sentence_transformers','chromadb','langgraph'} & set(sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, timeout=20
    )
    assert result.returncode == 0, result.stderr.decode()
