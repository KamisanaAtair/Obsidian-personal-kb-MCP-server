"""Host-delegated 关联发现：只检索候选，关联理由由 Host 生成。

仅对 promoted 笔记运行；不修改笔记，也不自动添加双链。
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage

from config.prompts import CORRELATION_SYSTEM, CORRELATION_USER
from config.settings import get_settings
from core.state import KBState
from core.tools.retriever import retrieve
from core.tools.vault_io import read_note

logger = logging.getLogger(__name__)


async def correlation_node(state: KBState) -> dict:
    """对 promoted 笔记返回原始候选和 prompt，由 Host 完成关联判断。"""
    s = get_settings()
    note_path = state.get("note_path") or state.get("user_input", "")
    try:
        meta = read_note(note_path, s)
    except FileNotFoundError:
        logger.error("[correlation] 笔记不存在: %s", note_path)
        return {
            "candidates": [],
            "prompt_for_host": None,
            "messages": [AIMessage(content=f"[Correlation] 笔记不存在: {note_path}")],
        }

    # 信任闸门先于刷新/检索，未审核笔记不会触发任何候选召回。
    if meta.status != "promoted":
        logger.info("[correlation] 笔记未 promoted，跳过: %s", note_path)
        return {
            "candidates": [],
            "prompt_for_host": None,
            "messages": [AIMessage(content=f"[Correlation] 笔记未 promoted，跳过: {note_path}")],
        }

    from core.tools.retriever import ensure_index_fresh

    ensure_index_fresh(s)
    query_text = (meta.body or "")[:1000]
    chunks = retrieve(query_text, top_k=s.correlation_top_k, settings=s)
    candidates = [
        {"path": c["path"], "snippet": c["content"][:200], "score": c["score"]}
        for c in chunks
        if c["path"] != note_path and c.get("status", "promoted") == "promoted"
    ]
    if not candidates:
        return {
            "candidates": [],
            "prompt_for_host": None,
            "messages": [AIMessage(content="[Correlation] 无候选关联笔记")],
        }

    prompt_for_host = CORRELATION_SYSTEM + "\n\n" + CORRELATION_USER.format(
        note_path=note_path,
        note_content=query_text,
        candidates_json=json.dumps(candidates, ensure_ascii=False, indent=2),
    )
    logger.info("[correlation] 返回 %d 条候选供 Host 判断", len(candidates))
    return {
        "candidates": candidates,
        "prompt_for_host": prompt_for_host,
        "messages": [AIMessage(content=f"[Correlation] 已检索 {len(candidates)} 条候选，请 Host 判断关联")],
    }
