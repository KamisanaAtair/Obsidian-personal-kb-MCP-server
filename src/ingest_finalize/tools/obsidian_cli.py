"""Obsidian CLI 适配层 —— 独立封装，不依赖任何 Host 的 skill。

[调用链] ingest_finalize —— 仅被 MCP 工具 ingest_content_finalize 一条链调用
  上游: src/vault_io.py（create_staged_note 落盘时优先尝试 CLI）
  本文件存活的能力只有 detect_cli / create_note，其余函数已注释（见文末墓碑说明）。

设计背景
--------
本系统目标是多 Host（Codex / Claude Code / WorkBuddy 等）通用，不能假设 Host 自带
obsidian skill。参考两个开源 CLI 的能力，在本模块独立封装适配层：

1. obsidian-official-cli（命令 `obs`，需 Obsidian 1.12+ 且 Obsidian 运行中）
   - 官方出品，115 命令，功能最全
   - 通过 IPC 连接运行中的 Obsidian 桌面端
   - 创建笔记会自动更新 [[wikilinks]] 双向链接
   - 命令示例：obs create name="X" content="..." / obs property:set ... / obs search query="..."
   - 文件引用：file="笔记名"（wikilink 风格）或 path="folder/note.md"（精确路径）

2. yakitrak obsidian-cli（命令 `obsidian-cli`，Go 实现，第三方）
   - 功能较少但够用（search/create/move/delete/print-default/list）
   - ⚠️ 依赖按命令分两类（与 obsidian skill 文档一致，修正此前"不依赖 Obsidian 运行"的误导）：
     · create / move / open / daily：走 obsidian:// URI，需 Obsidian 桌面端安装并注册 URI handler
       （不必前台运行，但须能响应 obsidian:// 协议）——无 Obsidian 桌面端时这些命令会失败
     · print-default / list / search / search-content / print：直接读文件系统 / obsidian.json，
       不需要 Obsidian 运行（vault 本身是普通文件夹）
   - 命令示例：obsidian-cli create "Folder/note" --content "..."  （需 Obsidian URI handler）
              obsidian-cli print-default --path-only             （仅读配置，不需 Obsidian）

适配策略
--------
- 启动时探测可用 CLI：优先 `obs`（官方，自动更新双链），其次 `obsidian-cli`（yakitrak），
  都不可用则标记 filesystem-only 模式
- ⚠️ fallback 语义：官方 obs 失败时，yakitrak 的 create/move 因同样依赖 Obsidian 桌面端
  大概率也失败，真正能兜底"无 Obsidian 桌面端"环境的只有文件系统直接写入。yakitrak 的价值
  主要在 print-default/search/list 等不依赖 Obsidian 运行的只读操作（见 vault_resolver.py）。
- 本模块当前只保留 Ingestion 落盘需要的核心操作：create
  （property_set / read / search / move 已确认无调用方，见文末注释）
- 不暴露改 status 的便捷接口——status 修改只能人工在 Obsidian 完成（信任闸门）
- 所有命令异步执行，避免阻塞事件循环

⚠️ 信任闸门：本模块不提供任何能修改 status 字段的封装。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from src.common.settings import Settings, get_settings

logger = logging.getLogger(__name__)

CliKind = Literal["official", "yakitrak", "none"]


@dataclass
class CliAvailability:
    """CLI 可用性探测结果。"""
    kind: CliKind
    command: Optional[str]   # 实际可用的命令名（obs / obsidian-cli / None）

    @property
    def available(self) -> bool:
        return self.kind != "none"


_availability: Optional[CliAvailability] = None  # 单例缓存


def detect_cli() -> CliAvailability:
    """探测可用的 Obsidian CLI（单例缓存）。

    探测顺序：官方 `obs` → yakitrak `obsidian-cli` → none（fallback 文件系统）
    """
    global _availability
    if _availability is not None:
        return _availability

    if shutil.which("obs"):
        _availability = CliAvailability(kind="official", command="obs")
        logger.info("[obsidian_cli] 使用官方 CLI: obs")
    elif shutil.which("obsidian-cli"):
        _availability = CliAvailability(kind="yakitrak", command="obsidian-cli")
        logger.info("[obsidian_cli] 使用 yakitrak CLI: obsidian-cli")
    else:
        _availability = CliAvailability(kind="none", command=None)
        logger.warning(
            "[obsidian_cli] 未检测到 Obsidian CLI（obs / obsidian-cli 均不在 PATH）。"
            "将 fallback 到文件系统直接读写。如需自动更新双链等能力，请安装：\n"
            "  - 官方 CLI（推荐，需 Obsidian 1.12+ 运行）：Obsidian Settings → General → Enable CLI，并将 Obsidian 加入 PATH\n"
            "  - 或 yakitrak CLI：brew install yakitrak/yakitrak/obsidian-cli\n"
            "注意：yakitrak CLI 的 create/move/open 仍依赖 Obsidian 桌面端（obsidian:// URI handler）；"
            "仅 print-default/search/list 不依赖 Obsidian 运行。无 Obsidian 桌面端时只能用文件系统 fallback。"
        )
    return _availability


async def create_note(
    name: str,
    content: str,
    settings: Settings | None = None,
) -> Optional[str]:
    """创建笔记。返回笔记标识（官方 CLI 返回 wikilink 名，yakitrak 返回路径），
    不可用返回 None（调用方 fallback 文件系统）。

    Parameters
    ----------
    name : 笔记名（可含相对路径如 "Inbox/新笔记"）
    content : 笔记正文
    """
    s = settings or get_settings()
    avail = detect_cli()
    if not avail.available:
        return None

    if avail.kind == "official":
        # 官方 CLI：obs create name="X" content="..."
        # 注意：官方 CLI 通过 Obsidian URI 创建，content 中的特殊字符需谨慎
        cmd = [avail.command, "create", f'name={name}', f"content={content}"]
        result = await _run_async(cmd)
        if result.returncode == 0:
            logger.info("[obsidian_cli] 官方 CLI 创建笔记成功: %s", name)
            return name
        logger.warning("[obsidian_cli] 官方 CLI 创建失败（rc=%d）: %s", result.returncode, result.stderr[:200])
        return None

    if avail.kind == "yakitrak":
        # yakitrak：obsidian-cli create "Folder/note" --content "..."
        # ⚠️ 走 obsidian:// URI，需 Obsidian 桌面端安装并注册 URI handler（与官方 obs 同依赖）。
        # 无 Obsidian 桌面端时此路径会失败，调用方 fallback 文件系统
        # （见 src/vault_io.py 的 create_staged_note）。
        cmd = [avail.command, "create", name, "--content", content]
        result = await _run_async(cmd)
        if result.returncode == 0:
            logger.info("[obsidian_cli] yakitrak CLI 创建笔记成功: %s", name)
            return name
        logger.warning(
            "[obsidian_cli] yakitrak CLI 创建失败（rc=%d）: %s。"
            "create 走 obsidian:// URI，需 Obsidian 桌面端安装并响应 URI handler。",
            result.returncode,
            result.stderr[:200],
        )
        return None

    return None


# ---------------------------------------------------------------------------
# 【已注释 —— 对 LLM 默认不存在】
# property_set / read_note / search / move_note 在本次纵切中经全仓引用扫查确认
# 无任何调用方，属死代码。保留注释仅供人工追溯历史，**不代表当前设计契约**：
# 对本仓库的 LLM 而言，下面这段代码默认不存在，不应被引用、不应被当作可用接口，
# 也不应据此推断本系统具备这些能力。
#
# 仍然存活的只有：detect_cli（被 vault_io.create_staged_note 探测 CLI）与 create_note（CLI 优先落盘）。
# 若将来需要只读检索能力，正确做法是在对应链的 tools/ 下重新实现并登记调用方，
# 而不是取消本注释。
# ---------------------------------------------------------------------------
# async def property_set(
#     file: str,
#     name: str,
#     value: str,
#     settings: Settings | None = None,
# ) -> bool:
#     """设置笔记的 frontmatter 属性（仅官方 CLI 支持）。
#
#     ⚠️ 信任闸门：显式拒绝设置 status 字段。
#     Promotion 只能人工在 Obsidian 完成，任何代码路径都不能改 status。
#     """
#     if name == "status":
#         logger.error(
#             "[obsidian_cli] 拒绝通过代码修改 status 字段（信任闸门）。"
#             "Promotion 只能人工在 Obsidian 中完成。"
#         )
#         return False
#
#     s = settings or get_settings()
#     avail = detect_cli()
#     if not avail.available or avail.kind != "official":
#         logger.debug("[obsidian_cli] property_set 需官方 CLI，当前不可用，跳过")
#         return False
#
#     cmd = [avail.command, "property:set", f"name={name}", f"value={value}", f"file={file}"]
#     result = await _run_async(cmd)
#     return result.returncode == 0
#
#
# async def read_note(
#     file: str,
#     settings: Settings | None = None,
# ) -> Optional[str]:
#     """读取笔记内容（官方 CLI 支持）。"""
#     avail = detect_cli()
#     if not avail.available or avail.kind != "official":
#         return None
#
#     cmd = [avail.command, "read", f"file={file}"]
#     result = await _run_async(cmd)
#     if result.returncode == 0:
#         return result.stdout
#     logger.warning("[obsidian_cli] read 失败: %s", result.stderr[:200])
#     return None
#
#
# async def search(
#     query: str,
#     settings: Settings | None = None,
# ) -> Optional[str]:
#     """搜索笔记（官方 CLI 用 search，yakitrak 用 search-content）。
#
#     返回原始文本输出，由调用方解析。不可用返回 None。
#     """
#     avail = detect_cli()
#     if not avail.available:
#         return None
#
#     if avail.kind == "official":
#         cmd = [avail.command, "search", f"query={query}"]
#     else:
#         cmd = [avail.command, "search-content", query]
#
#     result = await _run_async(cmd)
#     if result.returncode == 0:
#         return result.stdout
#     return None
#
#
# async def move_note(
#     src: str,
#     dst: str,
#     settings: Settings | None = None,
# ) -> bool:
#     """移动/重命名笔记（yakitrak 支持 move，会自动更新双链）。
#
#     官方 CLI 暂无明确 move 命令（可通过 eval 间接实现，但风险高，本期不封装）。
#     """
#     avail = detect_cli()
#     if not avail.available or avail.kind != "yakitrak":
#         logger.debug("[obsidian_cli] move 需 yakitrak CLI，当前不可用，跳过")
#         return False
#
#     cmd = [avail.command, "move", src, dst]
#     result = await _run_async(cmd)
#     return result.returncode == 0


async def _run_async(cmd: list[str]) -> asyncio.subprocess.Process:
    """异步执行命令，返回带 stdout/stderr 的 CompletedProcess。"""
    import subprocess as sp
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return sp.CompletedProcess(
        args=cmd,
        returncode=proc.returncode or 0,
        stdout=stdout.decode(errors="ignore"),
        stderr=stderr.decode(errors="ignore"),
    )
