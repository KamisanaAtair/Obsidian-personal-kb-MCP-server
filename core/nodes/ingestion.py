"""Host-delegated 摄取：prepare 取原文，finalize 校验并写 staged 草稿。

视频引用旁的自然语言说明保留在给 Host 的格式化 prompt 中。
prepare 不写 Vault 或索引；视频转写沿用现有模块及其临时文件行为。
"""

from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage

from config.prompts import INGESTION_SYSTEM, INGESTION_USER
from config.settings import get_settings
from core.state import KBState
from core.tools import session_store
from core.tools.obsidian_skill import _ensure_frontmatter, _force_status_staged
from core.tools.video_to_text import extract_video_file, extract_video_url, transcribe_video

logger = logging.getLogger(__name__)


async def ingestion_prepare_node(state: KBState) -> dict:
    """读取/转写来源，返回原文与供 Host 生成笔记的 prompt，不创建笔记。"""
    s = get_settings()
    user_input = state.get("user_input", "")
    source_type = state.get("source_type") or _detect_source_type(user_input)

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
    else:
        raw_content = user_input
        source_ref = "(direct input)"
        user_note = ""

    prepare_id = session_store.create_session(source_type, source_ref)
    prompt_for_host = INGESTION_SYSTEM + "\n\n" + INGESTION_USER.format(
        source_type=source_type,
        source_ref=source_ref,
        user_note=user_note or "（无）",
        raw_content=raw_content,
    )
    logger.info("[ingestion_prepare] 原文就绪，等待 Host 生成笔记")
    return {
        "prepare_id": prepare_id,
        "source_type": source_type,
        "raw_content": raw_content,
        "prompt_for_host": prompt_for_host,
        "error": None,
        "messages": [AIMessage(content="[Ingestion] 原文就绪，请 Host 生成笔记并调用 finalize")],
    }


async def ingestion_finalize_node(state: KBState) -> dict:
    """校验 Host 回传正文，从服务端会话补全来源，再强制写入 staged。"""
    prepare_id = state.get("prepare_id") or ""
    session = session_store.get_session(prepare_id)
    if session is None:
        return {"error": "prepare_id 无效或已过期，请重新调用 ingest_content_prepare"}

    note_content = state.get("note_content")
    if not isinstance(note_content, str) or not note_content.strip():
        return {"error": "note_content 不能为空，请提供 Host 生成的 Markdown 笔记正文"}

    s = get_settings()
    # 即使 Host 带了完整 frontmatter，也始终使用会话中的权威来源补全/覆盖。
    # 非法 YAML 在任何 Vault 写操作之前被拒绝。
    try:
        processed = _ensure_frontmatter(
            note_content, session["source_type"], session["source_ref"]
        )
        processed = _force_status_staged(processed, s)
    except ValueError as exc:
        return {"error": f"note_content frontmatter 无效：{exc}"}

    from core.tools.vault_io import create_staged_note

    out_path = await create_staged_note(processed, settings=s)
    rel_path = str(out_path.relative_to(s.vault_path)).replace("\\", "/")
    logger.info("[ingestion_finalize] 已创建 staged 笔记: %s", rel_path)
    return {
        "processed_note": processed,
        "note_path": rel_path,
        "error": None,
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
