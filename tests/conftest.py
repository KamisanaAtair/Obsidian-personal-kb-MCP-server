"""隔离真实 Vault、模型与外部凭据，测试中不下载模型。"""
from __future__ import annotations

import hashlib

import pytest
from langchain_core.embeddings import Embeddings


class TestEmbeddings(Embeddings):
    """确定性测试替身，仅验证 Chroma 链路，不代表 bge-m3 语义质量。"""
    __test__ = False

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        data = hashlib.sha256(text.encode()).digest()
        return [(value - 127.5) / 127.5 for value in data[:16]]


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    from src.common.settings import get_settings
    config = {
        "VAULT_ROOT": str(tmp_path / "vault"), "VAULT_AUTODISCOVER": "false",
        "VAULT_INBOX_DIR": "Inbox", "NOTE_STATUS_FIELD": "status",
        "CHROMA_PERSIST_DIR": str(tmp_path / "index"),
        "EMBED_MODEL_CACHE_DIR": str(tmp_path / "models"),
        "EMBED_PROVIDER": "local", "VIDEO_TO_TEXT_MCP_ENABLED": "false",
        "OBSIDIAN_SKILL_ENABLED": "false", "INGEST_SESSION_TTL_MINUTES": "60",
        "ANONYMIZED_TELEMETRY": "False", "LANGSMITH_TRACING": "false",
    }
    for key, value in config.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    from src.common.tools import session_store
    session_store._sessions.clear()
    yield get_settings()
    session_store._sessions.clear()
    get_settings.cache_clear()


@pytest.fixture
def local_retrieval(monkeypatch):
    from src.common.tools import hybrid_search, retriever
    embeddings = TestEmbeddings()
    monkeypatch.setattr(retriever, "get_local_embeddings", lambda settings=None: embeddings)
    monkeypatch.setattr(hybrid_search, "get_local_embeddings", lambda settings=None: embeddings)
    return embeddings
