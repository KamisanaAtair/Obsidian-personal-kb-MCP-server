"""Correlation Agent 节点（图内，AI 判断价值：语义关联发现）。

职责（需求第4节③）：
- 仅对刚 promoted 的笔记运行
- 在 Vault 内做语义检索，找出相关旧笔记
- 输出"建议关联"列表（笔记名 + 关联理由），供本人决定是否手动加双链
- 不自动修改任何笔记文件（只读建议）

只写 state 的：related_notes
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage

from config.prompts import CORRELATION_SYSTEM, CORRELATION_USER
from config.settings import get_settings
from core.state import KBState
from core.tools.llm import get_llm
from core.tools.retriever import retrieve
from core.tools.vault_io import read_note

logger = logging.getLogger(__name__)


async def correlation_node(state: KBState) -> dict:
    """关联发现节点：对已 promoted 的笔记，输出建议关联列表（只读）。

    state 期望字段：
        note_path : 已 promoted 的笔记相对路径（必填）
    """
    s = get_settings()
    note_path = state.get("note_path") or state.get("user_input", "")

    # 1. 读取目标笔记内容
    try:
        meta = read_note(note_path, s)
    except FileNotFoundError:
        logger.error("[correlation] 笔记不存在: %s", note_path)
        return {"related_notes": [], "messages": [AIMessage(content=f"[Correlation] 笔记不存在: {note_path}")]}

    # 信任闸门兜底：只对 promoted 笔记运行
    if meta.status != "promoted":
        logger.warning(
            "[correlation] 笔记 status=%s 非 promoted，按需求第5节不运行关联发现", meta.status
        )
        return {
            "related_notes": [],
            "messages": [AIMessage(content=f"[Correlation] 笔记未 promoted，跳过: {note_path}")],
        }

    # 2. 增量刷新索引（保证人工 promote 后无需手动跑 index 即可被检索到）
    from core.tools.retriever import ensure_index_fresh

    ensure_index_fresh(s)

    # 3. 语义检索候选旧笔记（仅 promoted，物理隔离 staged）
    query_text = (meta.body or "")[:1000]
    candidates = retrieve(query_text, top_k=s.correlation_top_k, settings=s)
    # 剔除自身
    candidates = [c for c in candidates if c["path"] != note_path]

    if not candidates:
        logger.info("[correlation] 无候选笔记，关联建议为空")
        return {"related_notes": [], "messages": [AIMessage(content="[Correlation] 无候选关联笔记")]}

    # 4. LLM 判断关联性并输出建议（JSON 数组）
    related_notes: list[dict] = []
    try:
        llm = get_llm("correlation", s)
        candidates_json = json.dumps(
            [{"path": c["path"], "snippet": c["content"][:200], "score": c["score"]} for c in candidates],
            ensure_ascii=False,
            indent=2,
        )
        messages = [
            ("system", CORRELATION_SYSTEM),
            ("human", CORRELATION_USER.format(
                note_path=note_path, note_content=query_text, candidates_json=candidates_json,
            )),
        ]
        resp = await llm.ainvoke(messages)
        related_notes = _parse_correlation_response(resp.content, candidates)
    except Exception as e:  # noqa: BLE001
        # LLM 不可用时退化为按相似度直出（带占位理由）
        logger.warning("[correlation] LLM 调用失败，退化为相似度直出: %s", e)
        related_notes = [
            {"path": c["path"], "reason": f"语义相似度 {c['score']:.3f}", "score": c["score"]}
            for c in candidates
        ]

    logger.info("[correlation] 输出 %d 条建议关联", len(related_notes))
    return {
        "related_notes": related_notes,
        "messages": [AIMessage(content=f"[Correlation] 建议关联 {len(related_notes)} 条")],
    }


def _parse_correlation_response(content: str, candidates: list[dict]) -> list[dict]:
    """解析 LLM 输出的建议关联 JSON。容错处理。"""
    import re

    # 抽取首个 JSON 数组
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []

    # 用候选的真实 score 回填
    score_map = {c["path"]: c["score"] for c in candidates}
    result = []
    for it in items:
        path = it.get("path", "")
        result.append(
            {
                "path": path,
                "reason": it.get("reason", ""),
                "score": score_map.get(path, 0.0),
            }
        )
    return result
