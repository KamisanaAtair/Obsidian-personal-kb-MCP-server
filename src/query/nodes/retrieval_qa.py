"""链4 知识库问答的节点：返回 promoted 片段与 prompt，Host 合成答案。

[调用链] query —— 唯一入口 MCP 工具 query_kb
  上游: src/query/graph.py
  下游: src/common/tools/retriever.py（ensure_index_fresh + retrieve）
        src/common/prompts.py（RETRIEVAL_QA_SYSTEM / RETRIEVAL_QA_USER）
  本链无 tools/ 目录：它只消费公共检索能力，不持有独占工具。
注意：本链虽名为「问答」，但对 Vault 并非只读——ensure_index_fresh 会增量写索引。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from src.common.prompts import RETRIEVAL_QA_SYSTEM, RETRIEVAL_QA_USER
from src.common.settings import get_settings
from src.common.state import KBState
from src.common.tools.retriever import retrieve

logger = logging.getLogger(__name__)


async def retrieval_qa_node(state: KBState) -> dict:
    """提问 → 检索 promoted 片段，返回供 Host 执行的引用式回答 prompt。"""
    s = get_settings()
    question = state.get("user_input", "")

    from src.common.tools.retriever import ensure_index_fresh

    ensure_index_fresh(s)
    chunks = retrieve(question, top_k=s.rag_top_k, settings=s)
    # retriever 已以 metadata 过滤 promoted；若上游显式传来其他状态，再丢弃。
    chunks = [
        {**c, "source": c.get("source", "dense")}
        for c in chunks
        if c.get("path") and c.get("status", "promoted") == "promoted"
    ]
    if not chunks:
        no_hit = "信息不足：知识库中暂无相关 promoted 笔记可回答此问题。"
        return {
            "retrieved_chunks": [],
            "prompt_for_host": None,
            "no_hit_message": no_hit,
            "messages": [AIMessage(content="[QA] 无命中 promoted 笔记")],
        }

    context_lines = []
    for i, c in enumerate(chunks, 1):
        context_lines.append(
            f"[{i}] 笔记: {c['path']}\n"
            f"    (来源 {c['source']}, 分数 {c['score']:.3f}) {c['content']}"
        )
    prompt_for_host = RETRIEVAL_QA_SYSTEM + "\n\n" + RETRIEVAL_QA_USER.format(
        question=question, context_block="\n\n".join(context_lines)
    )
    logger.info("[qa] 返回 %d 条片段供 Host 合成答案", len(chunks))
    return {
        "retrieved_chunks": chunks,
        "prompt_for_host": prompt_for_host,
        "no_hit_message": None,
        "messages": [AIMessage(content=f"[QA] 已检索 {len(chunks)} 条片段，请 Host 生成带引用的回答")],
    }
