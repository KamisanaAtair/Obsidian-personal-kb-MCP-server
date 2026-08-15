"""Ingestion Agent 节点（图内，AI 判断价值：格式转换/结构化）。

职责（需求第4节①）：
- 接收视频链接 / 导入文本
- 视频链接 → 调视频转写（yt-dlp + whisper 三级 fallback）拿到转写文本
- 调 format_note 做格式化（LLM 优先，占位符时基础包装 fallback）
- 落地为一篇 status: staged 的笔记（写入 Inbox/，优先 Obsidian CLI，fallback 文件系统）

只写 state 的：source_type / raw_content / processed_note / note_path
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from config.settings import get_settings
from core.state import KBState
from core.tools.obsidian_skill import format_note
from core.tools.video_to_text import is_video_url, transcribe_video

logger = logging.getLogger(__name__)


async def ingestion_node(state: KBState) -> dict:
    """摄取节点：外部内容 → staged 草稿笔记。

    state 期望字段：
        user_input   : 用户描述（视频链接 / 文本内容）
        source_type  : video_url | raw_text | note_path（缺省自动判别）
    """
    s = get_settings()
    user_input = state.get("user_input", "")
    source_type = state.get("source_type") or _detect_source_type(user_input)

    # 1. 取原始文本：视频需转写，文本直接用
    if source_type == "video_url":
        raw_content = await transcribe_video(user_input)
        source_ref = user_input
    elif source_type == "note_path":
        from core.tools.vault_io import read_note

        meta = read_note(user_input, s)
        raw_content = meta.body
        source_ref = user_input
    else:  # raw_text
        raw_content = user_input
        source_ref = "(direct input)"

    # 2. 格式化为 Obsidian 笔记（format_note 内部：LLM 优先，占位符时基础包装）
    processed = await format_note(raw_content, source_type, source_ref, s)

    # 3. 落地为 staged 笔记到 Inbox/（create_staged_note 内部：CLI 优先，fallback 文件系统）
    from core.tools.vault_io import create_staged_note

    out_path = await create_staged_note(processed, settings=s)

    rel_path = str(out_path.relative_to(s.vault_path)).replace("\\", "/")
    logger.info("[ingestion] 摄取完成，staged 笔记: %s", rel_path)

    return {
        "source_type": source_type,
        "raw_content": raw_content,
        "processed_note": processed,
        "note_path": rel_path,
        "messages": [AIMessage(content=f"[Ingestion] 已生成 staged 笔记: {rel_path}")],
    }


def _detect_source_type(text: str) -> str:
    """简单判别来源类型（视频链接 / 纯文本）。"""
    if is_video_url(text):
        return "video_url"
    lowered = text.strip().lower()
    if lowered.startswith(("http://", "https://")):
        # 其他 http 链接暂按 raw_text 处理（未实现网页抓取）
        return "raw_text"
    return "raw_text"
