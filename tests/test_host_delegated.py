from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import yaml
from pydantic import ValidationError

from src.common.settings import Settings
from src.common.graph_registry import ingestion_finalize_graph, ingestion_prepare_graph
from src import vault_io
from src.common.tools import session_store
from mcp_server.server import (
    ingest_content_finalize,
    ingest_content_prepare,
    query_kb,
    trigger_correlation,
)


def write_note(settings, name, status, body):
    path = settings.vault_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nstatus: {status}\n---\n\n# {name}\n\n{body}\n", encoding="utf-8")
    return path


async def test_prepare_raw_no_business_writes(isolated_settings):
    result = await ingest_content_prepare("# 原始记录\n这是待整理的事实。")
    assert set(result) == {"prepare_id", "source_type", "raw_content", "prompt_for_host"}
    assert result["source_type"] == "raw_text"
    assert "这是待整理的事实" in result["prompt_for_host"]
    assert session_store.get_session(result["prepare_id"])["source_ref"] == "(direct input)"
    assert not isolated_settings.vault_path.exists()
    assert not isolated_settings.chroma_path.exists()


async def test_prepare_video_stub_preserves_instructions(isolated_settings):
    result = await ingest_content_prepare("请重点整理方法 https://www.bilibili.com/video/BV1test")
    assert result["source_type"] == "video_url"
    assert "重点整理方法" in result["prompt_for_host"]
    assert "stub" in result["raw_content"].lower() or "占位" in result["raw_content"]
    assert session_store.get_session(result["prepare_id"])["source_ref"].endswith("BV1test")
    assert not isolated_settings.vault_path.exists()
    assert not isolated_settings.chroma_path.exists()


@pytest.mark.parametrize("frontmatter", [
    "", "---\nstatus: promoted\n---\n",
    "---\nstatus: promoted\nsource_type: video_file\nsource_ref: forged\ntags: [rag]\n---\n",
])
async def test_finalize_staged_and_authoritative_sources(frontmatter, isolated_settings):
    prepared = await ingest_content_prepare("原始材料")
    result = await ingest_content_finalize(prepared["prepare_id"], frontmatter + "# Host 笔记\n\n正文事实")
    assert set(result) == {"note_path"}
    assert result["note_path"].startswith("Inbox/")
    content = (isolated_settings.vault_path / result["note_path"]).read_text()
    fm = vault_io.parse_frontmatter(content)
    assert fm["status"] == "staged"
    assert fm["source_type"] == "raw_text"
    assert fm["source_ref"] == "(direct input)"
    assert "created" in fm and "tags" in fm
    assert "正文事实" in content


@pytest.mark.parametrize("content", ["", "   ", "---\nstatus: [broken\n---\nbody", "---\n- item\n---\nbody", "---\nscalar\n---\nbody"])
async def test_bad_finalize_content_no_write(content, isolated_settings):
    prepared = await ingest_content_prepare("材料")
    result = await ingest_content_finalize(prepared["prepare_id"], content)
    assert result.get("error")
    assert not isolated_settings.vault_path.exists()


@pytest.mark.parametrize("expired", [False, True])
async def test_invalid_or_expired_session_crosses_real_graph(expired, isolated_settings):
    prepare_id = "unknown-id"
    if expired:
        prepare_id = session_store.create_session("raw_text", "source")
        session_store._sessions[prepare_id]["created_at"] = datetime.now(timezone.utc) - timedelta(minutes=61)
    graph_result = await ingestion_finalize_graph.ainvoke({"prepare_id": prepare_id, "note_content": "# test"})
    assert graph_result["error"]
    result = await ingest_content_finalize(prepare_id, "# test")
    assert result.get("error")
    assert not isolated_settings.vault_path.exists()
    assert session_store.get_session(prepare_id) is None


def test_session_copy_and_lazy_cleanup():
    active = session_store.create_session("raw_text", "trusted")
    old = session_store.create_session("raw_text", "old")
    session_store._sessions[old]["created_at"] -= timedelta(minutes=61)
    value = session_store.get_session(active)
    value["source_ref"] = "forged"
    assert session_store.get_session(active)["source_ref"] == "trusted"
    assert old not in session_store._sessions
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ingest_session_ttl_minutes=0)


async def test_source_with_yaml_special_characters(isolated_settings):
    source_ref = 'https://example.test/video?a=1: 2\nstatus: promoted'
    prepare_id = session_store.create_session("video_url", source_ref)
    result = await ingest_content_finalize(prepare_id, "# 内容")
    content = (isolated_settings.vault_path / result["note_path"]).read_text()
    fm = vault_io.parse_frontmatter(content)
    assert fm["source_ref"] == source_ref
    assert fm["status"] == "staged"


async def test_note_path_graph_compatibility(isolated_settings):
    write_note(isolated_settings, "input.md", "promoted", "原笔记正文")
    before = list(isolated_settings.vault_path.rglob("*.md"))
    result = await ingestion_prepare_graph.ainvoke({"user_input": "input.md", "source_type": "note_path"})
    assert "原笔记正文" in result["raw_content"]
    assert session_store.get_session(result["prepare_id"])["source_ref"] == "input.md"
    assert list(isolated_settings.vault_path.rglob("*.md")) == before


@pytest.mark.parametrize("exists", [False, True])
async def test_correlation_gate_before_retrieval(exists, isolated_settings, monkeypatch):
    from src.correlate.nodes import correlation
    from src.common.tools import retriever
    if exists:
        write_note(isolated_settings, "draft.md", "staged", "不可检索内容")
    refresh = Mock(side_effect=AssertionError("must not refresh"))
    retrieve = Mock(side_effect=AssertionError("must not retrieve"))
    monkeypatch.setattr(retriever, "ensure_index_fresh", refresh)
    monkeypatch.setattr(correlation, "retrieve", retrieve)
    assert await trigger_correlation("draft.md") == {"candidates": [], "prompt_for_host": None}
    refresh.assert_not_called()
    retrieve.assert_not_called()


async def test_correlation_candidates_without_generation(isolated_settings, monkeypatch):
    from src.correlate.nodes import correlation
    from src.common.tools import retriever
    write_note(isolated_settings, "source.md", "promoted", "RAG 检索")
    monkeypatch.setattr(retriever, "ensure_index_fresh", lambda settings: {})
    monkeypatch.setattr(correlation, "retrieve", lambda *args, **kwargs: [
        {"path": "source.md", "content": "self", "score": 0.1},
        {"path": "other.md", "content": "related", "score": 0.9},
    ])
    result = await trigger_correlation("source.md")
    assert result["candidates"] == [{"path": "other.md", "snippet": "related", "score": 0.9}]
    assert "related" in result["prompt_for_host"]


@pytest.mark.parametrize("hybrid", [False, True])
async def test_real_chroma_retrieval_and_demotion(hybrid, isolated_settings, local_retrieval):
    from src.common.tools import retriever
    from langchain_chroma import Chroma
    isolated_settings.hybrid_search_enabled = hybrid
    write_note(isolated_settings, "approved.md", "promoted", "可信的 RAG 检索资料")
    write_note(isolated_settings, "secret.md", "staged", "不可检索的秘密")
    assert retriever.index_vault() == 1
    store = Chroma(collection_name=isolated_settings.rag_collection_name,
                   persist_directory=str(isolated_settings.chroma_path), embedding_function=local_retrieval)
    # 此 staged 夹具与查询不匹配；本测试不覆盖外部污染 BM25 索引后的匹配词召回。
    store.add_texts(["不可检索的秘密"], metadatas=[{"path": "secret.md", "status": "staged"}])
    result = await query_kb("RAG 检索资料")
    assert result["no_hit_message"] is None
    assert result["prompt_for_host"]
    assert result["retrieved_chunks"]
    assert {c["path"] for c in result["retrieved_chunks"]} == {"approved.md"}
    assert all("source" in c for c in result["retrieved_chunks"])
    assert "不可检索的秘密" not in result["prompt_for_host"]
    write_note(isolated_settings, "approved.md", "staged", "降回草稿")
    result = await query_kb("RAG")
    assert result["retrieved_chunks"] == []
    assert result["prompt_for_host"] is None
    assert result["no_hit_message"]


async def test_real_empty_index_no_hit(isolated_settings, local_retrieval):
    result = await query_kb("空库问题")
    assert result["retrieved_chunks"] == []
    assert result["prompt_for_host"] is None
    assert result["no_hit_message"]


def test_frontmatter_serializes_as_mapping():
    from src.ingest_finalize.tools.obsidian_skill import _ensure_frontmatter
    value = _ensure_frontmatter("# 文本", "raw_text", "来源")
    assert isinstance(yaml.safe_load(value.split("---", 2)[1]), dict)
