"""冒烟测试：验证框架结构可导入、子图可编译、状态 Schema 正确。

这些测试不依赖 LLM / 外部 MCP，纯结构验证（第一层调试的自动化版本）。
运行：pytest
"""

from __future__ import annotations


def test_state_schema_fields():
    """KBState 含需求第6节定义的全部字段。"""
    from core.state import KBState

    # TypedDict 在运行时不强制，但字段应存在于 __annotations__
    annotations = KBState.__annotations__
    expected = {
        "user_input",
        "source_type",
        "raw_content",
        "processed_note",
        "note_path",
        "related_notes",
        "related_note_links",
        "retrieved_chunks",
        "answer",
        "messages",
    }
    missing = expected - set(annotations.keys())
    assert not missing, f"KBState 缺少字段: {missing}"


def test_settings_loads_with_placeholders():
    """配置在占位符状态下可正常加载。"""
    from config.settings import get_settings

    s = get_settings()
    assert s.note_status_field == "status"
    # 占位符阶段应为 stub 模式
    assert s.is_stub_mode is True
    assert s.llm_provider in ("ollama", "api")


def test_subgraphs_compile():
    """三个子图可正常编译（不依赖运行时 LLM）。"""
    from core.subgraphs.correlation_graph import build_correlation_graph
    from core.subgraphs.ingestion_graph import build_ingestion_graph
    from core.subgraphs.retrieval_graph import build_retrieval_graph

    ig = build_ingestion_graph()
    cg = build_correlation_graph()
    rg = build_retrieval_graph()
    assert ig is not None
    assert cg is not None
    assert rg is not None


def test_graph_registry_exports_three():
    """graph.py 注册表导出三个子图。"""
    from core.graph import correlation_graph, ingestion_graph, retrieval_graph

    assert ingestion_graph is not None
    assert correlation_graph is not None
    assert retrieval_graph is not None


def test_vault_io_status_enforcement(tmp_path):
    """create_staged_note 强制 status=staged（信任闸门）。"""
    import asyncio
    from core.tools.vault_io import create_staged_note, get_note_status
    from config.settings import Settings

    vault = tmp_path / "vault"
    vault.mkdir()
    settings = Settings(
        vault_root=str(vault),
        vault_inbox_dir="Inbox",
        vault_autodiscover=False,  # 测试隔离：禁用动态解析
    )

    # 故意写一个 status=promoted 的笔记内容
    evil = "---\nstatus: promoted\n---\n\n# 想偷渡的笔记\n\n内容"
    # create_staged_note 现为 async（修复 is_running() 死代码），用 asyncio.run 驱动
    out = asyncio.run(create_staged_note(evil, settings=settings))

    content = out.read_text(encoding="utf-8")
    status = get_note_status(content, settings)
    # 关键：必须被强制改回 staged
    assert status == "staged", "信任闸门失效：create_staged_note 应强制 status=staged"


def test_mcp_server_tool_count():
    """MCP Server 仅暴露 3 个业务流程级工具，不含改 status 等原子操作。"""
    from mcp_server.server import mcp

    tools = mcp._tool_manager._tools  # FastMCP 内部注册表
    names = set(tools.keys())
    expected = {"ingest_content", "trigger_correlation", "query_kb"}
    assert names == expected, f"MCP 工具集不匹配: {names}"
    # 安全断言：绝不包含能改 status 的工具
    forbidden = {"promote_note", "set_status", "write_note", "set_frontmatter"}
    assert not (names & forbidden), f"暴露了禁止的原子操作工具: {names & forbidden}"


def test_video_to_text_stub_fallback():
    """视频转写在 ENABLED=false 时走 stub（无依赖环境可验证）。"""
    import asyncio
    from core.tools.video_to_text import transcribe_video
    from config.settings import Settings

    settings = Settings(video_to_text_mcp_enabled=False)
    # 注意：transcribe_video 用单例 settings，这里主要验证 stub 输出格式
    result = asyncio.run(transcribe_video("https://www.bilibili.com/video/BV1xxxxx"))
    assert "STUB" in result, "stub 模式应返回占位文本"
    assert "BV1xxxxx" in result


def test_video_url_detection():
    """视频链接判别覆盖主流平台。"""
    from core.tools.video_to_text import is_video_url

    assert is_video_url("https://www.bilibili.com/video/BV1abc")
    assert is_video_url("https://b23.tv/abc123")
    assert is_video_url("https://www.youtube.com/watch?v=abc")
    assert is_video_url("https://youtu.be/abc")
    assert not is_video_url("这是一段普通文本")
    assert not is_video_url("https://example.com/page")


def test_format_note_basic_wrap_when_llm_placeholder():
    """LLM 占位符时，format_note fallback 到基础 frontmatter 包装。"""
    import asyncio
    from core.tools.obsidian_skill import format_note
    from config.settings import Settings

    settings = Settings(llm_provider="ollama", ollama_ingest_model="PLACEHOLDER_xxx")
    result = asyncio.run(
        format_note("原始内容示例", "raw_text", "(test)", settings)
    )
    assert result.startswith("---\n"), "应有 frontmatter"
    assert "status: staged" in result, "status 必须为 staged"
    assert "原始内容示例" in result


def test_format_note_forces_status_staged():
    """format_note 即使 LLM 输出 promoted，也强制改回 staged（信任闸门）。"""
    from core.tools.obsidian_skill import _force_status_staged
    from config.settings import Settings

    settings = Settings()
    evil = "---\nstatus: promoted\n---\n\n# 想偷渡\n\n内容"
    safe = _force_status_staged(evil, settings)
    assert "status: staged" in safe
    assert "status: promoted" not in safe


def test_obsidian_cli_refuses_status_change():
    """Obsidian CLI 适配层拒绝通过代码改 status（信任闸门）。"""
    import asyncio
    from core.tools.obsidian_cli import property_set
    from config.settings import Settings

    settings = Settings()
    result = asyncio.run(property_set("note", "status", "promoted", settings))
    assert result is False, "property_set 必须拒绝设置 status 字段"


def test_obsidian_cli_detect_returns_valid_kind():
    """detect_cli 返回合法的 CliAvailability。"""
    from core.tools.obsidian_cli import detect_cli, CliAvailability

    avail = detect_cli()
    assert isinstance(avail, CliAvailability)
    assert avail.kind in ("official", "yakitrak", "none")


# ---------------------------------------------------------------------------
# 索引幂等性 + 增量刷新（修复问题1+3 的回归保护）
# 用 FakeEmbeddings 绕开 ollama，直接验证 chroma 层逻辑
# ---------------------------------------------------------------------------

class _FakeEmbeddings:
    """确定性假 embedding：sha256 前 16 字节归一化，不依赖 ollama。"""

    def embed_documents(self, texts):
        import hashlib
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:16]] for t in texts]

    def embed_query(self, text):
        import hashlib
        return [b / 255 for b in hashlib.sha256(text.encode()).digest()[:16]]


def _index_settings(tmp_path):
    from config.settings import Settings
    vault = tmp_path / "vault"
    vault.mkdir()
    chroma_dir = tmp_path / "chroma"
    return Settings(
        vault_root=str(vault),
        vault_inbox_dir="Inbox",
        chroma_persist_dir=str(chroma_dir),
        obsidian_skill_enabled=False,
        vault_autodiscover=False,  # 测试隔离：禁用动态解析，强制用 tmp vault_root
    )


def test_index_vault_idempotent_no_duplicate(tmp_path, monkeypatch):
    """index_vault 重复调用不累积重复 chunk（修复问题3）。"""
    pytest = __import__("pytest")
    pytest.importorskip("langchain_chroma")

    from core.tools import retriever as R

    monkeypatch.setattr(R, "get_embeddings", lambda s=None: _FakeEmbeddings())
    s = _index_settings(tmp_path)
    vault = s.vault_path

    # 一篇 promoted 笔记
    (vault / "note1.md").write_text(
        "---\nstatus: promoted\n---\n\n# 测试笔记\n\n## 章节\n内容示例 ABC\n",
        encoding="utf-8",
    )

    Chroma = R._import_chroma()[0]

    n1 = R.index_vault(s)
    assert n1 == 1
    vs1 = Chroma(
        collection_name=s.rag_collection_name,
        embedding_function=_FakeEmbeddings(),
        persist_directory=str(s.chroma_path),
    )
    count1 = vs1._collection.count()
    assert count1 > 0, "首次索引应有 chunk"

    # 第二次全量索引——修复前会翻倍累积，修复后应等量（先 delete_collection 再重建）
    n2 = R.index_vault(s)
    assert n2 == 1
    vs2 = Chroma(
        collection_name=s.rag_collection_name,
        embedding_function=_FakeEmbeddings(),
        persist_directory=str(s.chroma_path),
    )
    count2 = vs2._collection.count()

    assert count1 == count2, (
        f"index_vault 非幂等：重复调用累积了重复 chunk（{count1} → {count2}）"
    )


def test_ensure_index_fresh_incremental(tmp_path, monkeypatch):
    """ensure_index_fresh 基于 mtime manifest 做增量索引（修复问题1）。"""
    pytest = __import__("pytest")
    pytest.importorskip("langchain_chroma")

    import os
    import time
    from core.tools import retriever as R

    monkeypatch.setattr(R, "get_embeddings", lambda s=None: _FakeEmbeddings())
    s = _index_settings(tmp_path)
    vault = s.vault_path

    # 初始：一篇 promoted
    (vault / "a.md").write_text(
        "---\nstatus: promoted\n---\n\n# A\n内容甲\n", encoding="utf-8"
    )

    # 1. 首次：manifest 不存在 → 全量重建
    r1 = R.ensure_index_fresh(s)
    assert r1["rebuilt"] is True
    assert r1["total"] == 1

    # 2. 无变化 → 增量为空
    r2 = R.ensure_index_fresh(s)
    assert r2["rebuilt"] is False
    assert (r2["added"], r2["updated"], r2["removed"]) == (0, 0, 0)
    assert r2["total"] == 1

    # 3. 新增 b.md + 修改 a.md（用 os.utime 强制 mtime 变化，避免依赖 sleep 精度）
    (vault / "b.md").write_text(
        "---\nstatus: promoted\n---\n\n# B\n内容乙\n", encoding="utf-8"
    )
    (vault / "a.md").write_text(
        "---\nstatus: promoted\n---\n\n# A\n内容甲修改\n", encoding="utf-8"
    )
    future = time.time() + 1000
    os.utime(vault / "a.md", (future, future))

    r3 = R.ensure_index_fresh(s)
    assert r3["added"] == 1, f"应新增 1，实际 {r3}"
    assert r3["updated"] == 1, f"应更新 1，实际 {r3}"
    assert r3["total"] == 2

    # 4. 删除 b.md → removed=1
    (vault / "b.md").unlink()
    r4 = R.ensure_index_fresh(s)
    assert r4["removed"] == 1, f"应删除 1，实际 {r4}"
    assert r4["total"] == 1

    # 5. 检索仍命中 a.md（增量后向量库内容正确）
    hits = R.retrieve("内容", settings=s)
    assert any(h["path"] == "a.md" for h in hits), f"应命中 a.md，实际 {hits}"


# ---------------------------------------------------------------------------
# Vault 路径动态解析（修复硬编码反模式，遵循 obsidian skill 规范）
# ---------------------------------------------------------------------------

def test_resolve_vault_path_via_obsidian_json_open(tmp_path, monkeypatch):
    """resolve_vault_path 从 obsidian.json 解析 open:true vault。"""
    import json
    from core.tools import vault_resolver as VR

    VR.resolve_vault_path.cache_clear()
    monkeypatch.setattr(VR, "_resolve_via_cli", lambda: None)

    vault_a = tmp_path / "vaultA"
    vault_a.mkdir()
    vault_b = tmp_path / "vaultB"
    vault_b.mkdir()
    obs_json = tmp_path / "obsidian.json"
    obs_json.write_text(
        json.dumps(
            {
                "vaults": {
                    "id1": {"path": str(vault_a), "open": False, "ts": 1},
                    "id2": {"path": str(vault_b), "open": True, "ts": 2},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(VR, "_obsidian_json_path", lambda: obs_json)

    p = VR.resolve_vault_path()
    assert p == vault_b, f"应返回 open:true 的 vault_b，实际 {p}"
    VR.resolve_vault_path.cache_clear()


def test_resolve_vault_path_no_open_falls_to_first(tmp_path, monkeypatch):
    """obsidian.json 无 open 标记（Obsidian 未运行）时取首个存在路径。"""
    import json
    from core.tools import vault_resolver as VR

    VR.resolve_vault_path.cache_clear()
    monkeypatch.setattr(VR, "_resolve_via_cli", lambda: None)

    vault_a = tmp_path / "vaultA"
    vault_a.mkdir()
    obs_json = tmp_path / "obsidian.json"
    obs_json.write_text(
        json.dumps({"vaults": {"id1": {"path": str(vault_a), "ts": 1}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(VR, "_obsidian_json_path", lambda: obs_json)

    assert VR.resolve_vault_path() == vault_a
    VR.resolve_vault_path.cache_clear()


def test_resolve_vault_path_missing_json_returns_none(tmp_path, monkeypatch):
    """obsidian.json 不存在 → None（调用方 fallback .env）。"""
    from core.tools import vault_resolver as VR

    VR.resolve_vault_path.cache_clear()
    monkeypatch.setattr(VR, "_resolve_via_cli", lambda: None)
    monkeypatch.setattr(VR, "_obsidian_json_path", lambda: tmp_path / "nope.json")

    assert VR.resolve_vault_path() is None
    VR.resolve_vault_path.cache_clear()


def test_vault_path_property_autodiscover_prefers_resolved(tmp_path, monkeypatch):
    """vault_path: autodiscover=True 时动态解析优先于 .env vault_root。"""
    from config.settings import Settings
    from core.tools import vault_resolver as VR

    VR.resolve_vault_path.cache_clear()
    resolved = tmp_path / "discovered_vault"
    resolved.mkdir()
    monkeypatch.setattr(VR, "resolve_vault_path", lambda: resolved)

    # vault_root 故意设一个不同路径，验证被动态解析覆盖
    s = Settings(vault_root=str(tmp_path / "should_be_ignored"), vault_autodiscover=True)
    assert s.vault_path == resolved, "autodiscover=True 应优先动态解析"


def test_vault_path_property_disabled_uses_vault_root(tmp_path, monkeypatch):
    """vault_path: autodiscover=False 时直接用 vault_root（测试隔离保证）。"""
    from config.settings import Settings
    from core.tools import vault_resolver as VR

    VR.resolve_vault_path.cache_clear()
    resolved = tmp_path / "discovered_vault"
    resolved.mkdir()
    monkeypatch.setattr(VR, "resolve_vault_path", lambda: resolved)

    explicit = tmp_path / "explicit"
    explicit.mkdir()
    s = Settings(vault_root=str(explicit), vault_autodiscover=False)
    assert s.vault_path == explicit, "autodiscover=False 应直接用 vault_root，不受动态解析影响"
