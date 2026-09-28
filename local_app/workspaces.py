"""Explicit vault paths, bounded folders and private atomic local state."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
from typing import Any


_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_SYSTEM = {"$recycle.bin", "system volume information", "node_modules", "__pycache__"}


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def atomic_json(path: Path, value: Any) -> None:
    """A replacement never exposes a partially written file; state is owner-only."""
    private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def is_link(path: Path) -> bool:
    """Also reject Windows junctions/reparse points, without following them."""
    try:
        stat = path.lstat()
        return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def hidden_component(name: str) -> bool:
    return name.startswith(".") or name.lower() in _SYSTEM


def _check_components(path: Path) -> None:
    cursor = Path(path.anchor)
    for component in path.parts[1:]:
        cursor /= component
        if is_link(cursor):
            raise ValueError("不允许符号链接或目录联接；请指定实际笔记库路径")


def canonical_vault(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请在本次任务中明确指定笔记库的绝对路径")
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("笔记库必须是明确的绝对路径")
    # macOS /var and /tmp are system aliases; a selected root is canonicalized
    # once. Descendants are checked separately and may never redirect traversal.
    if is_link(path):
        raise ValueError("请指定笔记库的实际目录，不能选择链接")
    root = path.resolve(strict=True)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError("请选择现有的笔记库文件夹，不能使用磁盘根目录")
    if hidden_component(root.name):
        raise ValueError("不能把隐藏目录或系统目录作为笔记库")
    return root


def vault_id(root: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:24]


def normalize_folder(root: Path, value: str = "", *, allow_missing: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError("目录必须是字符串")
    value = value.strip()
    if not value or value == ".":
        return ""
    value = value.replace("\\", "/")
    path = Path(value)
    if PureWindowsPath(value).is_absolute() and not path.is_absolute():
        raise ValueError("目录路径不属于本机文件系统")
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            raise ValueError("目标目录必须位于指定笔记库内") from None
    parts = path.parts
    for part in parts:
        if part in {"..", "."} or hidden_component(part):
            raise ValueError("不允许越界目录、隐藏目录或系统目录")
        if (
            re.search(r'[<>:"|?*\x00-\x1f]', part)
            or part.endswith((" ", "."))
            or part.split(".")[0].upper() in _RESERVED
        ):
            raise ValueError("目录包含不兼容 Windows 的名称")
    target = root.joinpath(*parts)
    cursor = root
    for part in parts:
        cursor /= part
        if is_link(cursor):
            raise ValueError("目录中不能包含符号链接或目录联接")
        if cursor.exists() and not cursor.is_dir():
            raise ValueError("分类目录不能是文件")
    if not target.resolve().is_relative_to(root):
        raise ValueError("目标目录越出笔记库")
    if not allow_missing and not target.is_dir():
        raise ValueError("指定目录不存在")
    return path.as_posix() if parts else ""


def safe_note_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("笔记路径无效")
    normalize_folder(root, path.parent.as_posix())
    if hidden_component(path.name) or path.suffix.lower() != ".md":
        raise ValueError("仅允许可见 Markdown 笔记")
    target = root / path
    if is_link(target) or not target.resolve().is_relative_to(root):
        raise ValueError("笔记路径包含链接或越界")
    return target


def normalized_dirs(root: Path, values: list[str] | None) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or any(
        not isinstance(item, str) for item in values
    ):
        raise ValueError("目录范围必须是字符串列表")
    return sorted(set(normalize_folder(root, item) for item in values))


def in_scope(relative: str, policy: dict, folders: list[str] | None = None) -> bool:
    path = Path(relative)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(hidden_component(part) for part in path.parts)
    ):
        return False
    relative = path.as_posix()

    def within(folder: str) -> bool:
        return not folder or relative.startswith(folder.rstrip("/") + "/")

    includes = policy.get("include_dirs", [])
    if includes and not any(within(item) for item in includes):
        return False
    if any(within(item) for item in policy.get("exclude_dirs", [])):
        return False
    return folders is None or not folders or any(within(item) for item in folders)


def safe_title(text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = match.group(1) if match else "未命名笔记"
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:80].rstrip(" .")
    if not title or title.split(".")[0].upper() in _RESERVED:
        title = "笔记_" + (title or "未命名")
    return title
