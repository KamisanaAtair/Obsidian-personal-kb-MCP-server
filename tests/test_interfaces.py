from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def client_environment(settings):
    return {
        "VAULT_ROOT": str(settings.vault_path), "VAULT_AUTODISCOVER": "false",
        "CHROMA_PERSIST_DIR": str(settings.chroma_path),
        "EMBED_MODEL_CACHE_DIR": str(settings.embed_cache_path),
        "VIDEO_TO_TEXT_MCP_ENABLED": "false", "OBSIDIAN_SKILL_ENABLED": "false",
        "INGEST_SESSION_TTL_MINUTES": "60", "ANONYMIZED_TELEMETRY": "False",
    }


def payload(result):
    assert not result.isError, result
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(next(c.text for c in result.content if c.type == "text"))


async def test_production_mcp_stdio_session(isolated_settings):
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                   cwd=ROOT, env=client_environment(isolated_settings))
    async with asyncio.timeout(60):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = {t.name: t for t in (await client.list_tools()).tools}
                assert set(tools) == {"ingest_content_prepare", "ingest_content_finalize", "trigger_correlation", "query_kb"}
                expected = {
                    "ingest_content_prepare": ["user_input"],
                    "ingest_content_finalize": ["prepare_id", "note_content"],
                    "trigger_correlation": ["note_path"], "query_kb": ["question"],
                }
                for name, fields in expected.items():
                    assert set(tools[name].inputSchema["properties"]) == set(fields)
                    assert set(tools[name].inputSchema["required"]) == set(fields)
                error = payload(await client.call_tool("ingest_content_finalize", {"prepare_id": "missing", "note_content": "# bad"}))
                assert error["error"]
                assert not isolated_settings.vault_path.exists()
                prepared = payload(await client.call_tool("ingest_content_prepare", {"user_input": "可核验原始事实"}))
                assert not isolated_settings.vault_path.exists()
                final = payload(await client.call_tool("ingest_content_finalize", {
                    "prepare_id": prepared["prepare_id"], "note_content": "---\nstatus: promoted\n---\n# Host 摘要\n事实",
                }))
                path = isolated_settings.vault_path / final["note_path"]
                assert "status: staged" in path.read_text()
                correlated = payload(await client.call_tool("trigger_correlation", {"note_path": final["note_path"]}))
                assert correlated == {"candidates": [], "prompt_for_host": None}


async def test_query_registered_mcp_tool(local_retrieval):
    from mcp_server.server import mcp
    result = await mcp.call_tool("query_kb", {"question": "空知识库"})
    # FastMCP 1.x 通用 dict 注解以 JSON TextContent 序列化。
    data = json.loads(result[0].text)
    assert data["retrieved_chunks"] == []
    assert data["prompt_for_host"] is None
    assert data["no_hit_message"]


def test_debug_cli_same_process_and_status(isolated_settings, tmp_path):
    env = {**os.environ, **client_environment(isolated_settings), "NO_COLOR": "1", "COLUMNS": "160"}
    note = tmp_path / "host.md"
    note.write_text("---\nstatus: promoted\n---\n# 调试草稿\n正文")
    for args in (["--help"], ["status"], ["ingest", "原始材料", "--note-file", str(note)]):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/debug_run.py"), *args],
                                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
    paths = list(isolated_settings.inbox_path.glob("*.md"))
    assert len(paths) == 1
    assert "status: staged" in paths[0].read_text()


def test_preserved_baseline_contract():
    from src.common import prompts
    contract = json.loads((ROOT / "tests/baseline_contract.json").read_text())
    for name, value in contract["prompts"].items():
        assert getattr(prompts, name) == value
    for file, expected in contract["sha256"].items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == expected


def test_no_server_generation_dependencies():
    import tomllib
    # 旧路径 core.tools.llm 一并保留：它搬迁到 src/common/tools/llm.py 后仍不得复活。
    banned_modules = {"src.common.tools.llm", "core.tools.llm", "langchain_ollama", "langchain_openai"}
    banned_calls = {"get_llm", "ChatOpenAI", "ChatOllama", "OpenAIEmbeddings", "OllamaEmbeddings"}
    for folder in ("src", "mcp_server", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    assert node.module not in banned_modules, path
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in banned_calls, path
    assert not (ROOT / "src/common/tools/llm.py").exists()
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert not any("langchain-openai" in dep or "langchain-ollama" in dep for dep in deps)


# =============================================================================
# 【已注释 / 视为不存在】测试目标 src/common/_deprecated/path_url_recognizer.py 是死代码：
# 全仓除本测试外无任何调用方（主链的来源判别走 ingest_prepare 的 _detect_source_type）。
# 对一个已经没有调用方的模块做断言没有回归意义，故连同被测模块一起注释。
# 对本仓库的 LLM 而言，下面这段代码默认不存在，不属于当前设计与契约。
# =============================================================================
# async def test_recognizer_no_model_fallback():
#     from src.common._deprecated.path_url_recognizer import recognize
#     result = await recognize("https://a.example/video https://b.example/video")
#     assert not result.used_llm
#     assert result.refs
#     assert all(ref.needs_review for ref in result.refs)
