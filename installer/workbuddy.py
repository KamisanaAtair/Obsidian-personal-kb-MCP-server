"""Conservatively merge only the installer-managed WorkBuddy MCP entry."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import urlsplit
from uuid import uuid4

MANAGED_PREFIX = "Personal KB managed installer"
DEFAULT_SERVER_ID = "obsidian-personal-kb-host"
_MAX_CONFIG_BYTES = 4 * 1024 * 1024


class ConfigError(ValueError):
    """Configuration was left unchanged because it could not be merged safely."""


def default_config_path() -> Path:
    return Path.home() / ".workbuddy" / "mcp.json"


def _reject_symlinks(path: Path) -> None:
    # Inspect lexical parents before resolve(), which would hide a symlink.
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ConfigError("WorkBuddy configuration path contains a symbolic link.")


def _read(path: Path) -> bytes | None:
    _reject_symlinks(path)
    try:
        if not path.is_file():
            if path.exists():
                raise ConfigError("WorkBuddy configuration path is not a regular file.")
            return None
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ConfigError(
                "WorkBuddy configuration is too large to merge automatically."
            )
        return path.read_bytes()
    except OSError as exc:
        raise ConfigError(
            "Cannot read WorkBuddy configuration; check file permissions."
        ) from exc


def _parse(raw: bytes | None) -> dict:
    if raw is None:
        return {}

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigError(
                    "WorkBuddy configuration has duplicate JSON keys; it was not changed."
                )
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ConfigError("WorkBuddy configuration contains a non-JSON numeric value.")

    try:
        value = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=unique_object,
            parse_constant=invalid_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(
            "WorkBuddy configuration is not valid UTF-8 JSON; it was not changed."
        ) from exc
    if not isinstance(value, dict):
        raise ConfigError("WorkBuddy configuration must be a JSON object.")
    if "mcpServers" in value and not isinstance(value["mcpServers"], dict):
        raise ConfigError("WorkBuddy mcpServers must be a JSON object.")
    return value


def is_managed_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    description = entry.get("description", "")
    if not isinstance(description, str) or not description.startswith(MANAGED_PREFIX):
        return False
    try:
        address = urlsplit(entry.get("url", ""))
        return (
            address.scheme == "http"
            and address.hostname == "127.0.0.1"
            and address.port is not None
            and address.path.rstrip("/") == "/mcp"
            and address.username is None
            and address.password is None
            and not address.query
            and not address.fragment
        )
    except (TypeError, ValueError):
        return False


def _fingerprint(raw: bytes | None) -> str | None:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _backup(path: Path, raw: bytes) -> Path:
    backup = path.with_name(f"{path.name}.backup-{time.time_ns()}-{uuid4().hex[:8]}")
    fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def merge_config(
    config_path: Path,
    server_entry: dict,
    server_id: str = DEFAULT_SERVER_ID,
) -> dict:
    """Atomically add/update our entry; never modify trust records or other entries.

    Existing ownership must match BOTH our description and a loopback /mcp URL.
    A malformed configuration or unowned same-ID entry is an error, not a reason
    to reset the file. Backups contain credentials and use owner-only permissions.
    Returns only paths and saved/noop flags, never the configuration or its tokens.
    """
    path = Path(os.path.abspath(config_path.expanduser()))
    if not isinstance(server_id, str) or not server_id:
        raise ConfigError("A nonempty server ID is required.")
    if not is_managed_entry(server_entry):
        raise ConfigError(
            "The new entry must be an installer-managed loopback MCP server."
        )
    # Reject non-JSON objects before making directories or backups.
    try:
        json.dumps(server_entry, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ConfigError("The MCP entry is not valid JSON data.") from exc

    for _attempt in range(3):
        before = _read(path)
        config = _parse(before)
        servers = config.setdefault("mcpServers", {})
        existing = servers.get(server_id)
        if server_id in servers and not is_managed_entry(existing):
            raise ConfigError(
                "An unrelated MCP entry already uses this server ID; it was not overwritten."
            )
        if existing == server_entry:
            return {"saved": True, "path": str(path), "backup": None, "noop": True}
        servers[server_id] = server_entry
        output = (
            json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
        if before is not None and before.startswith(b"\xef\xbb\xbf"):
            output = b"\xef\xbb\xbf" + output
        _reject_symlinks(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if _fingerprint(_read(path)) != _fingerprint(before):
            continue
        backup = _backup(path, before) if before is not None else None
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        temp = Path(temp_name)
        try:
            os.chmod(temp, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "wb") as stream:
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
            _reject_symlinks(path)
            if _fingerprint(_read(path)) != _fingerprint(before):
                continue
            os.replace(temp, path)
            saved = _parse(_read(path))
            if saved.get("mcpServers", {}).get(server_id) != server_entry:
                raise ConfigError(
                    "WorkBuddy configuration changed during verification; retry registration."
                )
            return {
                "saved": True,
                "path": str(path),
                "backup": str(backup) if backup else None,
                "noop": False,
            }
        finally:
            temp.unlink(missing_ok=True)
    raise ConfigError(
        "WorkBuddy configuration kept changing; retry after closing its settings editor."
    )
