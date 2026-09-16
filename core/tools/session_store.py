"""摄取 prepare/finalize 配对使用的单进程内存会话。

会话不持久化，进程重启后失效；TTL 内允许重复 finalize（每次产生新草稿）。
没有后台任务，get_session 顺手清理过期条目。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from config.settings import get_settings

_sessions: dict[str, dict] = {}


def create_session(source_type: str, source_ref: str) -> str:
    """记录服务端确认的来源和 UTC 创建时间，返回 uuid4 prepare_id。"""
    prepare_id = str(uuid4())
    _sessions[prepare_id] = {
        "source_type": source_type,
        "source_ref": source_ref,
        "created_at": datetime.now(timezone.utc),
    }
    return prepare_id


def get_session(prepare_id: str) -> dict | None:
    """惰性清理超过 TTL 的会话；有效时返回副本，否则返回 None。"""
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=get_settings().ingest_session_ttl_minutes)
    expired = [
        key for key, session in _sessions.items()
        if now - session["created_at"] >= ttl
    ]
    for key in expired:
        del _sessions[key]
    session = _sessions.get(prepare_id)
    return session.copy() if session is not None else None
