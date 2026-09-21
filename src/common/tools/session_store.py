"""摄取 prepare/finalize 配对使用的单进程内存会话。

[公共文件] 被以下链调用：
  - ingest_prepare   创建会话（create_session）
  - ingest_finalize  取回会话（get_session）

这是全仓唯一的跨调用可变状态，是「成本转嫁」把摄取拆成两段后留下的产物：
会话只活在内存里，进程重启/客户端超时即失效（ASR 分支为此另加了一份 JSONL 落盘兜底）。

会话不持久化，进程重启后失效；TTL 内允许重复 finalize（每次产生新草稿）。
没有后台任务，get_session 顺手清理过期条目。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.common.settings import get_settings

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
