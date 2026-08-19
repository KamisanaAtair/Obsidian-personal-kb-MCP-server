"""Ingestion Agent 节点（图内，AI 判断价值：格式转换/结构化）。

职责（需求第4节①）：
- 接收用户输入（视频链接 / 本地视频文件路径 / 导入文本）
- ⚠️ 关键设计前提：用户输入**几乎总是自然语言与视频引用的组合**
  （如"帮我转写这个视频 https://b23.tv/xxx，重点整理方法论"），
  纯 URL / 纯路径的输入并不存在。因此必须先从混合文本中：
    a) 提取真正的视频引用（URL 或本地文件路径）→ 交给转写
    b) 剩余的自然语言部分作为"用户说明"→ 传给 format_note 做上下文
- 视频引用 → 调视频转写（URL: CC 字幕+whisper；本地文件: ffmpeg+whisper）
- 调 format_note 做格式化（LLM 优先，占位符时基础包装 fallback）
- 落地为一篇 status: staged 的笔记（写入 Inbox/，优先 Obsidian CLI，fallback 文件系统）

只写 state 的：source_type / raw_content / processed_note / note_path
"""

from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage

from config.settings import get_settings
from core.state import KBState
from core.tools.obsidian_skill import format_note
from core.tools.video_to_text import extract_video_file, extract_video_url, transcribe_video

logger = logging.getLogger(__name__)


async def ingestion_node(state: KBState) -> dict:
    """摄取节点：外部内容 → staged 草稿笔记。

    state 期望字段：
        user_input   : 用户输入（自然语言 + 视频链接/文件路径/文本内容的混合）
        source_type  : video_url | video_file | raw_text | note_path（缺省自动判别）
    """
    s = get_settings()
    user_input = state.get("user_input", "")
    source_type = state.get("source_type") or _detect_source_type(user_input)

    # 1. 分离"视频引用"与"用户自然语言说明"，再取原始文本
    if source_type == "video_url":
        source_ref = extract_video_url(user_input) or user_input.strip()
        user_note = _strip_ref(user_input, source_ref)
        raw_content = await transcribe_video(source_ref)
    elif source_type == "video_file":
        source_ref = extract_video_file(user_input) or user_input.strip()
        user_note = _strip_ref(user_input, source_ref)
        raw_content = await transcribe_video(source_ref)
    elif source_type == "note_path":
        from core.tools.vault_io import read_note

        meta = read_note(user_input, s)
        raw_content = meta.body
        source_ref = user_input
        user_note = ""
    else:  # raw_text
        raw_content = user_input
        source_ref = "(direct input)"
        user_note = ""

    if user_note:
        logger.info("[ingestion] 用户说明已并入笔记上下文: %s", user_note[:60])

    # 2. 格式化为 Obsidian 笔记（format_note 内部：LLM 优先，占位符时基础包装；
    #    用户自然语言说明 user_note 作为结构化上下文一并传入，不丢弃）
    processed = await format_note(raw_content, source_type, source_ref, s, user_note=user_note)

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
    """从混合输入判别来源类型。

    用户输入通常是"自然语言 + 视频引用"的组合，判别依据是**文本中是否包含**
    视频引用，而非整段文本是否就是引用：
    - 含视频站链接           → video_url
    - 含本地视频文件路径     → video_file（路径存在且扩展名为视频格式）
    - 其他                   → raw_text（note_path 需显式指定，不做自动判别）
    """
    if extract_video_url(text):
        return "video_url"
    if extract_video_file(text):
        return "video_file"
    return "raw_text"


def _strip_ref(text: str, ref: str) -> str:
    """从用户输入中去掉视频引用（URL/文件路径），剩余部分即用户自然语言说明。

    例如 "帮我转写这个视频 https://b23.tv/xxx，重点整理方法论"
      → "帮我转写这个视频，重点整理方法论"
    """
    if not ref:
        return ""
    note = text.replace(ref, " ")
    note = re.sub(r"\s+", " ", note).strip()
    return note
