"""Obsidian 笔记格式化 —— 把原始文本结构化为规范 Markdown 笔记。

设计边界
--------
参考已安装的 obsidian skill（WorkBuddy 内置）的方法论：Obsidian 笔记 = plain Markdown +
frontmatter。但本系统目标是多 Host 通用，**不能依赖 Host 的 skill**，因此在本模块独立
实现格式化逻辑。

格式化职责（需求第4节①"调用 Obsidian skill 做格式化"）：
- 把视频转写文本 / 导入文本结构化为符合 Obsidian 规范的 Markdown
- 产出含 frontmatter 的笔记正文（status 固定为 staged，由后续 create_staged_note 强制）
- 主题分类用 tag，状态用 frontmatter 字段（需求第7节决策）

实现策略
--------
1. 优先用 LLM 做内容结构化（prompt 在 config/prompts.py 的 INGESTION_SYSTEM/USER）
2. LLM 不可用（占位符）时，fallback 到基础 frontmatter 包装：
   保留原文作为正文，生成最小可用 frontmatter，保证链路可验证
3. 落地到 Vault 由 vault_io.create_staged_note 负责（该函数会优先用 Obsidian CLI 创建，
   不可用 fallback 文件系统），本模块只负责产出 Markdown 内容

切换开关：.env OBSIDIAN_SKILL_ENABLED=true 时尝试用 CLI 落地（在 vault_io 层判断），
         与本模块的 LLM 格式化独立。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from config.prompts import INGESTION_SYSTEM, INGESTION_USER
from config.settings import Settings, get_settings
from core.tools.llm import get_llm

logger = logging.getLogger(__name__)


async def format_note(
    raw_content: str,
    source_type: str,
    source_ref: str,
    settings: Settings | None = None,
    user_note: str = "",
) -> str:
    """把原始文本格式化为 Obsidian 规范的 Markdown 笔记草稿。

    Parameters
    ----------
    raw_content : 原始文本（视频转写 / 导入文本）
    source_type : video_url | video_file | raw_text | note_path
    source_ref  : 原始链接或文件标识（已从混合输入中提取的纯引用）
    user_note   : 用户随视频引用一并输入的自然语言说明（如整理重点、意图）。
                  用户输入几乎总是"自然语言 + 视频引用"的混合，说明部分
                  是结构化笔记的重要上下文，不可丢弃。可为空串。

    Returns
    -------
    str : 含 frontmatter 的 Markdown 笔记正文（status 字段固定为 staged）
    """
    s = settings or get_settings()

    # 1. 优先用 LLM 做内容结构化
    if not s.llm_is_placeholder:
        try:
            note = await _format_with_llm(raw_content, source_type, source_ref, s, user_note)
            if note:
                return note
        except Exception as e:  # noqa: BLE001
            logger.warning("[obsidian_skill] LLM 格式化失败，fallback 到基础包装: %s", e)

    # 2. Fallback：基础 frontmatter 包装（LLM 占位符或调用失败时）
    logger.info("[obsidian_skill] 使用基础 frontmatter 包装（LLM 占位符或不可用）")
    return _basic_wrap(raw_content, source_type, source_ref, user_note)


async def _format_with_llm(
    raw_content: str,
    source_type: str,
    source_ref: str,
    settings: Settings,
    user_note: str = "",
) -> Optional[str]:
    """用 LLM + prompt 把原始文本结构化为规范笔记。"""
    llm = get_llm("ingest", settings)
    messages = [
        ("system", INGESTION_SYSTEM),
        ("human", INGESTION_USER.format(
            source_type=source_type,
            source_ref=source_ref,
            user_note=user_note or "（无）",
            raw_content=raw_content,
        )),
    ]
    resp = await llm.ainvoke(messages)
    content = resp.content if hasattr(resp, "content") else str(resp)

    # 校验：LLM 输出必须包含 frontmatter 且 status 字段合规
    if not _has_valid_frontmatter(content):
        logger.warning("[obsidian_skill] LLM 输出 frontmatter 缺失或格式异常，将补全")
        content = _ensure_frontmatter(content, source_type, source_ref)

    # 信任闸门兜底：强制 status=staged（即使 LLM 写了 promoted 也改回）
    content = _force_status_staged(content, settings)
    return content


def _basic_wrap(raw_content: str, source_type: str, source_ref: str, user_note: str = "") -> str:
    """基础 frontmatter 包装（LLM 不可用时的 fallback）。

    保留原文作为正文，生成最小可用 frontmatter。
    保证链路可验证，但笔记结构化程度低（待 LLM 接入后由 _format_with_llm 替代）。
    用户自然语言说明（user_note）以"用户说明"小节保留在正文中，不丢弃。
    """
    today = date.today().isoformat()
    # 尝试从原文提取标题（首个 # 标题或首行）
    title = _extract_title(raw_content)

    user_note_section = ""
    if user_note:
        user_note_section = f"## 用户说明\n\n{user_note}\n\n"

    return (
        "---\n"
        f"status: staged\n"
        f"source_type: {source_type}\n"
        f"source_ref: {source_ref}\n"
        f"created: {today}\n"
        "tags: []\n"
        "---\n\n"
        f"# {title}\n\n"
        "> ⚠️ 本笔记由基础包装生成（LLM 占位符模式），结构化程度低。\n"
        "> 接入真实 LLM 后将自动结构化为规范笔记。\n\n"
        f"{user_note_section}"
        "## 原始内容\n\n"
        f"{raw_content}\n"
    )


# ---------------------------------------------------------------------------
# Frontmatter 校验与修补
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def _has_valid_frontmatter(content: str) -> bool:
    """检查是否包含合法 frontmatter 块。"""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return False
    fm_text = m.group(1)
    # 至少包含 status 字段
    return bool(re.search(r"^status\s*:", fm_text, re.MULTILINE))


def _ensure_frontmatter(content: str, source_type: str, source_ref: str) -> str:
    """若无 frontmatter 或缺字段，补全 frontmatter。"""
    m = _FRONTMATTER_RE.match(content)
    today = date.today().isoformat()
    if not m:
        # 无 frontmatter，整体作为正文
        return (
            "---\n"
            f"status: staged\nsource_type: {source_type}\nsource_ref: {source_ref}\n"
            f"created: {today}\ntags: []\n---\n\n{content}"
        )
    # 有 frontmatter 但缺 status
    fm_text, body = m.group(1), m.group(2)
    if not re.search(r"^status\s*:", fm_text, re.MULTILINE):
        fm_text = f"status: staged\n{fm_text}"
    return f"---\n{fm_text}\n---\n\n{body}"


def _force_status_staged(content: str, settings: Settings) -> str:
    """信任闸门兜底：强制 status 字段为 staged。

    无论 LLM 输出什么 status 值，都改回 staged。
    Promotion 只能人工在 Obsidian 完成（需求第3、4节）。
    """
    import yaml

    m = _FRONTMATTER_RE.match(content)
    if not m:
        return content
    fm_text, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return content

    if str(fm.get(settings.note_status_field, "")) != "staged":
        fm[settings.note_status_field] = "staged"
        fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip("\n")
        content = f"---\n{fm_text}\n---\n\n{body}"
        logger.info("[obsidian_skill] 强制 status=staged（信任闸门兜底）")
    return content


def _extract_title(text: str) -> str:
    """从文本提取标题（首个 # 标题或首行非空文本）。"""
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()[:80]
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "未命名笔记")
    return first_line[:80]
