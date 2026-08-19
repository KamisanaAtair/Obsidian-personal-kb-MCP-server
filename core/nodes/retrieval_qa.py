"""Retrieval/QA Agent 节点（图内，AI 判断价值：检索增强回答）。

职责（需求第4节④）：
- 仅检索 status=promoted 的笔记（retriever 已做 metadata 物理隔离）
- 回答时附带引用来源笔记（可追溯）
- 信任闸门兜底：召回片段中若混入 staged（理论上不应发生），一律忽略不引用

只写 state 的：retrieved_chunks / answer
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from config.prompts import RETRIEVAL_QA_SYSTEM, RETRIEVAL_QA_USER
from config.settings import get_settings
from core.state import KBState
from core.tools.llm import get_llm
from core.tools.retriever import retrieve

logger = logging.getLogger(__name__)


async def retrieval_qa_node(state: KBState) -> dict:
    """检索问答节点：用户提问 → 仅基于 promoted 笔记回答 + 引用来源。

    state 期望字段：
        user_input : 用户提问
    """
    s = get_settings()
    question = state.get("user_input", "")

    # 1. 增量刷新索引（保证人工 promote 后无需手动跑 index 即可被检索到）
    from core.tools.retriever import ensure_index_fresh

    ensure_index_fresh(s)

    # 2. 检索 promoted 笔记片段（metadata 物理隔离 staged）
    chunks = retrieve(question, top_k=s.rag_top_k, settings=s)

    # 信任闸门兜底：万一混入 staged，强制丢弃（理论上不会发生，retriever 已过滤）
    chunks = [c for c in chunks if c.get("path")]

    if not chunks:
        no_hit = "信息不足：知识库中暂无相关 promoted 笔记可回答此问题。"
        return {
            "retrieved_chunks": [],
            "answer": no_hit,
            "messages": [AIMessage(content="[QA] 无命中 promoted 笔记")],
        }

    # 3. 拼 context block（带编号，便于引用）
    context_lines = []
    for i, c in enumerate(chunks, 1):
        source_tag = c.get("source", "dense")
        context_lines.append(
            f"[{i}] 笔记: {c['path']}\n"
            f"    (来源 {source_tag}, 分数 {c['score']:.3f}) {c['content']}"
        )
    context_block = "\n\n".join(context_lines)

    # 4. LLM 回答（基于片段，强制引用）
    try:
        llm = get_llm("qa", s)
        messages = [
            ("system", RETRIEVAL_QA_SYSTEM),
            ("human", RETRIEVAL_QA_USER.format(
                question=question, context_block=context_block,
            )),
        ]
        resp = await llm.ainvoke(messages)
        answer = resp.content
    except Exception as e:  # noqa: BLE001
        logger.warning("[qa] LLM 调用失败，退化为直出片段: %s", e)
        answer = "（LLM 不可用，直出命中片段）\n\n" + context_block

    logger.info("[qa] 回答完成，引用 %d 条笔记", len(chunks))
    return {
        "retrieved_chunks": chunks,
        "answer": answer,
        "messages": [AIMessage(content=f"[QA] 回答完成，引用 {len(chunks)} 条笔记")],
    }
