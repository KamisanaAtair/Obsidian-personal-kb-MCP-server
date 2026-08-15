"""Vault 读写 + status 管理（仅内部使用，MCP 不暴露）。

⚠️ 信任闸门核心（需求第3、4、5节、术语表）：
- status 字段（staged/promoted）是本系统唯一的信任闸门。
- Promotion（改 status）只能由人工在 Obsidian 中完成，任何 MCP 工具都不具备此权限。
- 因此本模块提供"读取 status"与"创建 staged 笔记"的能力，但**不提供通过代码改 status 的对外入口**。
  create_note 永远写 status=staged；改 status 的人工动作不经过本模块对外函数。

提供能力：
- create_staged_note   : 写入一篇 status=staged 的草稿笔记到 Inbox/
- read_note            : 读取笔记全文
- get_note_status      : 读取某笔记的 status
- list_promoted_notes  : 列出所有 promoted 笔记（供 retriever 索引）
- parse_frontmatter    : 解析 frontmatter
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

from config.settings import get_settings

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


@dataclass
class NoteMeta:
    """笔记元信息。"""

    path: Path          # 绝对路径
    rel_path: str       # 相对 Vault 根目录的路径
    status: str         # staged | promoted | unknown
    frontmatter: dict   # 完整 frontmatter
    body: str           # 正文（去 frontmatter 后）


def _parse_note(content: str) -> tuple[dict, str]:
    """解析 Markdown 笔记的 frontmatter 与正文。"""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        logger.warning("[vault_io] frontmatter 解析失败，按空处理")
        return {}, content
    return fm, m.group(2)


def parse_frontmatter(content: str) -> dict:
    """仅解析 frontmatter。"""
    return _parse_note(content)[0]


def get_note_status(content: str, settings=None) -> str:
    """读取笔记的 status 字段值。"""
    s = settings or get_settings()
    fm = parse_frontmatter(content)
    return str(fm.get(s.note_status_field, "unknown"))


def read_note(rel_path: str, settings=None) -> NoteMeta:
    """读取 Vault 内某篇笔记（相对路径）。"""
    s = settings or get_settings()
    p = s.vault_path / rel_path
    content = p.read_text(encoding="utf-8")
    fm, body = _parse_note(content)
    return NoteMeta(
        path=p,
        rel_path=rel_path,
        status=str(fm.get(s.note_status_field, "unknown")),
        frontmatter=fm,
        body=body,
    )


async def create_staged_note(
    note_content: str,
    filename: Optional[str] = None,
    settings=None,
) -> Path:
    """把一篇笔记落地到 Inbox/，强制 status=staged。

    安全保证：本函数永远写 staged，不接受外部传入 promoted——
    即使 note_content 内 frontmatter 写了 promoted 也会被强制改回 staged。
    Promotion 只能人工在 Obsidian 完成（需求第4节方式B）。

    落地策略：
    - OBSIDIAN_SKILL_ENABLED=true 且检测到 Obsidian CLI 时，优先用 CLI 创建（自动更新双链等）
    - 否则 fallback 文件系统直接写入

    Note: 本函数为 async，因唯一调用方 ingestion_node 是 async def（经 ainvoke 触发）。
    此前用 asyncio.get_event_loop().is_running() 判断是否 fallback 文件系统——但在
    async 调用链中 loop 必然在运行，is_running() 恒为 True，CLI 优先路径是死代码。
    现改为 async，直接 await cli_create_note，CLI 路径才能真正生效。
    """
    s = settings or get_settings()
    inbox = s.inbox_path
    inbox.mkdir(parents=True, exist_ok=True)

    # 强制 status=staged：解析 frontmatter 后覆写 status 字段
    fm, body = _parse_note(note_content)
    fm[s.note_status_field] = "staged"
    fm.setdefault("created", date.today().isoformat())

    safe_content = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body

    if filename is None:
        # 用标题首行或时间戳生成文件名
        title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if title_match:
            stem = re.sub(r'[\\/:*?"<>|]', "_", title_match.group(1).strip())[:60]
        else:
            stem = f"note_{date.today().isoformat()}"
        filename = f"{stem}.md"

    out_path = inbox / filename
    counter = 1
    while out_path.exists():
        out_path = inbox / f"{Path(filename).stem}_{counter}.md"
        counter += 1

    # 优先尝试 Obsidian CLI 创建（自动更新双链等）；失败则文件系统写入
    if s.obsidian_skill_enabled:
        try:
            from core.tools.obsidian_cli import create_note as cli_create_note, detect_cli

            avail = detect_cli()
            if avail.available:
                rel_name = f"{s.vault_inbox_dir}/{Path(filename).stem}"
                created = await cli_create_note(rel_name, safe_content, s)
                if created:
                    # CLI 创建成功，但仍写一份到文件系统保证可读（CLI 可能走 URI）
                    out_path.write_text(safe_content, encoding="utf-8")
                    logger.info("[vault_io] 已通过 Obsidian CLI 创建 staged 笔记: %s", rel_name)
                    return out_path
                logger.debug("[vault_io] CLI 创建未成功，fallback 文件系统")
        except Exception as e:  # noqa: BLE001
            logger.warning("[vault_io] Obsidian CLI 创建失败，fallback 文件系统: %s", e)

    # Fallback：文件系统直接写入
    out_path.write_text(safe_content, encoding="utf-8")
    logger.info("[vault_io] 已创建 staged 笔记（文件系统）: %s", out_path)
    return out_path


def list_promoted_notes(settings=None) -> list[NoteMeta]:
    """列出 Vault 内所有 status=promoted 的笔记（供 retriever 索引）。"""
    s = settings or get_settings()
    vault = s.vault_path
    if not vault.exists():
        logger.warning("[vault_io] Vault 根目录不存在: %s", vault)
        return []

    promoted = []
    for md in vault.rglob("*.md"):
        if ".obsidian" in md.parts or md.parent.name.startswith("."):
            continue
        try:
            content = md.read_text(encoding="utf-8")
            status = get_note_status(content, s)
            if status == "promoted":
                fm, body = _parse_note(content)
                promoted.append(
                    NoteMeta(
                        path=md,
                        rel_path=str(md.relative_to(vault)).replace("\\", "/"),
                        status=status,
                        frontmatter=fm,
                        body=body,
                    )
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("[vault_io] 跳过无法解析的笔记 %s: %s", md, e)
    return promoted


def list_staged_notes(settings=None) -> list[NoteMeta]:
    """列出 Vault 内所有 status=staged 的笔记（供人工审核队列展示，调试用）。"""
    s = settings or get_settings()
    vault = s.vault_path
    if not vault.exists():
        return []
    staged = []
    for md in vault.rglob("*.md"):
        if ".obsidian" in md.parts or md.parent.name.startswith("."):
            continue
        try:
            content = md.read_text(encoding="utf-8")
            if get_note_status(content, s) == "staged":
                fm, body = _parse_note(content)
                staged.append(
                    NoteMeta(
                        path=md,
                        rel_path=str(md.relative_to(vault)).replace("\\", "/"),
                        status="staged",
                        frontmatter=fm,
                        body=body,
                    )
                )
        except Exception:  # noqa: BLE001
            continue
    return staged
