"""Host 生成笔记的确定性 frontmatter 校验与信任闸门。

[调用链] ingest_finalize —— 仅被 MCP 工具 ingest_content_finalize 一条链调用
  上游: src/ingestion.py 的 ingestion_finalize_node
  下游: 无（纯函数）；落盘由 src/vault_io.py 负责

笔记正文由 MCP Host 生成；服务端只校验 YAML、补全来源元数据，并强制草稿状态。
本模块不调用生成式模型。

私有函数（下划线开头）当前唯一外部调用方是 ingestion_finalize_node：
  _ensure_frontmatter / _force_status_staged —— 两条链共享时再提取到 src/common/。
"""

from __future__ import annotations

import logging
import re
from datetime import date

import yaml

from src.common.settings import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 【已注释 —— 对 LLM 默认不存在】
# _basic_wrap 是 local-llm 版本 format_note 的"无模型调试包装"残留，经全仓引用扫查
# 确认无任何调用方；它唯一依赖的 _extract_title 见文末，一并注释。
# 保留注释仅供人工追溯历史，**不代表当前设计契约**：对本仓库的 LLM 而言，这段代码
# 默认不存在，不应被引用，也不应据此推断系统具备"无 Host 也能产出笔记"的能力。
# ---------------------------------------------------------------------------
# def _basic_wrap(raw_content: str, source_type: str, source_ref: str, user_note: str = "") -> str:
#     """无模型调试包装：保留原文和用户说明，不进行内容结构化。"""
#     title = _extract_title(raw_content)
#     user_note_section = f"## 用户说明\n\n{user_note}\n\n" if user_note else ""
#     body = (
#         f"# {title}\n\n"
#         "> 本笔记使用无模型调试包装；实际使用时请由 Host 整理正文。\n\n"
#         f"{user_note_section}"
#         "## 原始内容\n\n"
#         f"{raw_content}\n"
#     )
#     return _ensure_frontmatter(body, source_type, source_ref)


# ---------------------------------------------------------------------------
# Frontmatter 校验与修补
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)^---[ \t]*(?:\r?\n|\Z)(.*)\Z",
    re.DOTALL | re.MULTILINE,
)
_FRONTMATTER_START_RE = re.compile(r"\A---[ \t]*(?:\r?\n|\Z)")


def _parse_frontmatter(fm_text: str) -> dict:
    """只接受 YAML mapping；不能将异常元数据带入落盘步骤。"""
    try:
        metadata = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise ValueError("frontmatter YAML 格式无效") from exc
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter 必须是 YAML mapping（键值对象）")
    return metadata


# ---------------------------------------------------------------------------
# 【已注释 —— 对 LLM 默认不存在】
# _has_valid_frontmatter 经全仓引用扫查确认无任何调用方（唯一的 frontmatter 校验
# 入口是 _ensure_frontmatter，它直接调用 _parse_frontmatter 并在失败时抛 ValueError）。
# 保留注释仅供人工追溯历史，**不代表当前设计契约**：对本仓库的 LLM 而言，这段代码
# 默认不存在，不应被引用。
# ---------------------------------------------------------------------------
# def _has_valid_frontmatter(content: str) -> bool:
#     """检查完整的 YAML mapping frontmatter，并保留原有 status 必需条件。"""
#     match = _FRONTMATTER_RE.match(content)
#     if not match:
#         return False
#     try:
#         metadata = _parse_frontmatter(match.group(1))
#     except ValueError:
#         return False
#     return "status" in metadata


def _ensure_frontmatter(content: str, source_type: str, source_ref: str) -> str:
    """补全元数据，并用服务端会话的真实来源覆盖 Host 声明。

    无 frontmatter 时将全部输入保留为正文；已有 frontmatter 必须是合法 YAML
    mapping。保留其余元数据和正文，来源字符串由 YAML 序列化避免换行/冒号注入。
    状态的最终强制覆写仍交给 _force_status_staged 与 create_staged_note。
    """
    match = _FRONTMATTER_RE.match(content)
    if match:
        metadata = _parse_frontmatter(match.group(1))
        body = match.group(2)
    else:
        if _FRONTMATTER_START_RE.match(content):
            raise ValueError("frontmatter 缺少结束分隔线")
        metadata = {}
        body = "\n" + content

    metadata.setdefault("status", "staged")
    metadata["source_type"] = source_type
    metadata["source_ref"] = source_ref
    metadata.setdefault("created", date.today().isoformat())
    metadata.setdefault("tags", [])
    fm_text = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip("\n")
    return f"---\n{fm_text}\n---\n{body}"


def _force_status_staged(content: str, settings: Settings) -> str:
    """信任闸门兜底：强制 status 字段为 staged。

    无论 Host 输出什么 status 值，都改回 staged。
    Promotion 只能人工在 Obsidian 完成（需求第3、4节）。
    """
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
        content = f"---\n{fm_text}\n---\n{body}"
        logger.info("[obsidian_skill] 强制 status=staged（信任闸门兜底）")
    return content


# ---------------------------------------------------------------------------
# 【已注释 —— 对 LLM 默认不存在】
# _extract_title 的唯一调用方是上面同样已注释的 _basic_wrap，随之成为死代码。
# 保留注释仅供人工追溯历史，**不代表当前设计契约**：对本仓库的 LLM 而言，这段代码
# 默认不存在，不应被引用。文件名的标题提取逻辑现在在 vault_io.create_staged_note 内。
# ---------------------------------------------------------------------------
# def _extract_title(text: str) -> str:
#     """从文本提取标题（首个 # 标题或首行非空文本）。"""
#     m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
#     if m:
#         return m.group(1).strip()[:80]
#     first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "未命名笔记")
#     return first_line[:80]
