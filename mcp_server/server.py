"""MCP Server：对外暴露 3 个业务流程级工具。

工具清单（需求第5节）：
- ingest_content(source, source_type?)            → Ingestion Agent，输出 staged 笔记
- trigger_correlation(note_path)                   → Correlation Agent，输出建议关联（只读）
- query_kb(question)                               → Retrieval/QA Agent，答案 + 引用来源

运行方式：
    python -m mcp_server.server

⚠️ 不暴露的工具（信任闸门安全边界）：
- 改 status / promote_note  → 永不暴露，只能人工在 Obsidian 完成
- 直接写笔记文件            → 永不暴露
- 直接改双链                → 永不暴露（Correlation 只输出建议）

业务逻辑全在 core/ 子图，本层不含业务逻辑（需求第9节适配层原则）。
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from config.settings import get_settings
from core.graph import correlation_graph, ingestion_graph, retrieval_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("personal-kb-multiagent")


@mcp.tool()
async def ingest_content(source: str, source_type: str = "") -> str:
    """摄取外部内容为 Obsidian 笔记草稿。

    把视频或导入文本转成一篇 status=staged 的笔记，落地到 Inbox/ 目录。
    该笔记需人工审核确认（在 Obsidian 中把 status 改为 promoted）后才可被检索。

    Parameters
    ----------
    source : str
        用户输入。支持两种视频来源，且几乎总是与自然语言说明混合出现
        （如"帮我转写这个视频 https://b23.tv/xxx，重点整理方法论"）：
        - 自然语言 + 视频链接（Bilibili/YouTube 等支持站点）
        - 自然语言 + 本地视频文件路径（mp4/mkv/mov 等格式，路径需存在）
        - 纯文本内容
        系统会自动从混合输入中提取视频引用并保留自然语言说明作为笔记上下文。
    source_type : str, optional
        来源类型：video_url | video_file | raw_text | note_path。留空时自动判别。

    Returns
    -------
    str : 摄取结果说明（笔记相对路径与状态）。
    """
    st = source_type or None
    result = await ingestion_graph.ainvoke(
        {"user_input": source, "source_type": st}
    )
    note_path = result.get("note_path", "")
    return (
        f"已生成 staged 草稿笔记：{note_path}\n"
        f"状态：staged（未审核，暂不可被检索）\n"
        f"下一步：在 Obsidian 中审核该笔记，确认无误后将 frontmatter 的 status 改为 promoted。\n"
        f"提升后无需手动刷新索引——下次调用 query_kb / trigger_correlation 会自动按 mtime "
        f"增量索引新 promoted 笔记；也可用 `python scripts/debug_run.py index` 强制全量重建。"
    )


@mcp.tool()
async def trigger_correlation(note_path: str) -> str:
    """对一篇已 promoted 的笔记触发关联发现。

    仅对 status=promoted 的笔记运行：先自动按 mtime 增量刷新向量索引（保证刚
    promote 的笔记已被检索到），再在知识库内做语义检索，找出相关的旧笔记，
    输出"建议关联"列表（笔记路径 + 关联理由）。本工具只读，不修改任何笔记文件，
    也不自动加双链——是否加双链由用户在 Obsidian 中手动决定。

    Parameters
    ----------
    note_path : str
        已 promoted 的笔记相对路径（相对 Vault 根目录）。

    Returns
    -------
    str : 建议关联列表（只读建议）。
    """
    result = await correlation_graph.ainvoke({"note_path": note_path})
    related = result.get("related_notes", [])

    if not related:
        return f"笔记 {note_path}：暂无有意义的关联建议。"

    lines = [f"笔记 {note_path} 的建议关联（共 {len(related)} 条，仅建议，不自动改文件）："]
    for i, item in enumerate(related, 1):
        lines.append(f"{i}. {item.get('path', '?')}")
        lines.append(f"   理由：{item.get('reason', '（无）')}")
        lines.append(f"   相似度：{item.get('score', 0):.3f}")
    lines.append("\n提示：如需建立双链，请在 Obsidian 中手动添加 [[双向链接]]。")
    return "\n".join(lines)


@mcp.tool()
async def query_kb(question: str) -> str:
    """检索个人知识库回答问题。

    仅检索 status=promoted 的笔记（已通过人工审核），回答时附带引用来源，
    便于逐条核实。未审核的 staged 笔记不会被检索到。调用时会自动按 mtime 增量
    刷新向量索引，保证刚 promote 的笔记可被检索。

    Parameters
    ----------
    question : str
        用户提问。

    Returns
    -------
    str : 答案（含引用来源清单）。
    """
    result = await retrieval_graph.ainvoke({"user_input": question})
    answer = result.get("answer", "（无回答）")
    chunks = result.get("retrieved_chunks", [])

    header = f"引用笔记数：{len(chunks)}\n{'=' * 40}\n\n"
    return header + answer


def main() -> None:
    """启动 MCP Server（stdio 传输）。"""
    s = get_settings()
    logger.info(
        "启动 MCP Server | Vault=%s | stub_mode=%s",
        s.vault_root,
        s.is_stub_mode,
    )
    if s.is_stub_mode:
        logger.warning(
            "⚠️ 处于 STUB 模式：视频转文档 MCP / Obsidian skill 未接入，"
            "对应能力走占位实现。待用户提供代码/配置后在 .env 开启。"
        )
    mcp.run()


if __name__ == "__main__":
    main()
