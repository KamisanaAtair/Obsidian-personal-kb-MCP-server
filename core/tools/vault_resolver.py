"""Vault 路径动态解析 —— 遵循 obsidian skill 规范，不硬编码。

背景
----
此前 settings.vault_root 默认值硬编码为 "D:/Obsidian/User Data Library"，
换机器/换 vault 名就得手动改 .env。obsidian skill 明确警告：

    Avoid writing hardcoded vault paths into scripts;
    prefer reading the config or using print-default.

Obsidian 桌面端把所有已知 vault 记录在 obsidian.json（真相来源）：
    - Windows: %APPDATA%/obsidian/obsidian.json
    - macOS:   ~/Library/Application Support/obsidian/obsidian.json
    - Linux:   $XDG_CONFIG_HOME/obsidian/obsidian.json
格式：{"vaults": {"<id>": {"path": "...", "open": true|false, "ts": ...}}}
"open": true 即当前活动 vault（多窗口时可能有多个）。

解析顺序（resolve_vault_path）
    1. `obsidian-cli print-default --path-only`（yakitrak CLI，只读配置，不需 Obsidian 运行）
    2. 读 obsidian.json，取 "open": true 的 vault（多个取第一个）
    3. 返回 None —— 调用方（settings.vault_path）fallback 到 .env 的 vault_root

本模块不依赖 config.settings，避免循环导入；纯函数 + lru_cache。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess as sp
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _obsidian_json_path() -> Path:
    """跨平台定位 obsidian.json（Obsidian 桌面端的 vault 注册表）。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / "obsidian" / "obsidian.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    # linux / 其他
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "obsidian" / "obsidian.json"


def _resolve_via_obsidian_json() -> Optional[Path]:
    """读 obsidian.json，取 "open": true 的 vault（多窗口取第一个）。

    不需要 Obsidian 运行，只需 Obsidian 桌面端曾安装并注册过 vault。
    """
    obs_json = _obsidian_json_path()
    if not obs_json.exists():
        return None
    try:
        data = json.loads(obs_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("[vault_resolver] obsidian.json 解析失败: %s", e)
        return None

    vaults = data.get("vaults", {})
    if not isinstance(vaults, dict):
        return None

    # 优先 "open": true 的（当前活动）
    for vid, vinfo in vaults.items():
        if not isinstance(vinfo, dict):
            continue
        if vinfo.get("open") is True:
            p = vinfo.get("path")
            if p and Path(p).exists():
                logger.info("[vault_resolver] obsidian.json 命中 open vault: %s", p)
                return Path(p)

    # 无 open 标记（Obsidian 未运行）：退而取第一个存在的 vault
    for vid, vinfo in vaults.items():
        if not isinstance(vinfo, dict):
            continue
        p = vinfo.get("path")
        if p and Path(p).exists():
            logger.info("[vault_resolver] obsidian.json 无 open vault，取首个: %s", p)
            return Path(p)

    return None


def _resolve_via_cli() -> Optional[Path]:
    """调 `obsidian-cli print-default --path-only`（yakitrak CLI，只读配置）。

    不需要 Obsidian 运行；需要 obsidian-cli 已 set-default。
    """
    if not shutil.which("obsidian-cli"):
        return None
    try:
        r = sp.run(
            ["obsidian-cli", "print-default", "--path-only"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (sp.SubprocessError, OSError) as e:
        logger.debug("[vault_resolver] obsidian-cli print-default 调用失败: %s", e)
        return None
    if r.returncode != 0:
        return None
    p = r.stdout.strip()
    if p and Path(p).exists():
        logger.info("[vault_resolver] obsidian-cli 解析 vault: %s", p)
        return Path(p)
    return None


@lru_cache
def resolve_vault_path() -> Optional[Path]:
    """动态解析当前活动 vault 路径（不硬编码）。

    顺序：obsidian-cli print-default → obsidian.json(open:true) → None。

    Returns
    -------
    Optional[Path]
        解析成功返回 vault 根路径；失败返回 None，由调用方 fallback 到 .env。
    """
    # 1. obsidian-cli print-default（最快，用户已显式 set-default）
    p = _resolve_via_cli()
    if p is not None:
        return p
    # 2. obsidian.json（不需 CLI，直接读 Obsidian 桌面端注册表）
    p = _resolve_via_obsidian_json()
    if p is not None:
        return p
    # 3. None —— 调用方 fallback
    logger.debug("[vault_resolver] 动态解析失败，将 fallback 到 settings.vault_root")
    return None
