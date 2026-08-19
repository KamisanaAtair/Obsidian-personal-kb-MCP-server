"""LLM 工厂：按 Agent 角色返回对应 LLM 实例。

支持两种 provider（由 LLM_PROVIDER 切换）：
- ollama：本地，默认，无需 API key（需本地启动 ollama 并 pull 模型）
- api   ：API key 模型，当前 key 为占位符，后续填入 .env

模型路由（需求第11节，待跑真实数据定档）：
- ingest       : Ingestion Agent 用的模型
- correlation   : Correlation Agent 用的模型
- qa           : Retrieval/QA Agent 用的模型
"""

from __future__ import annotations

import logging
from typing import Literal

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

Role = Literal["ingest", "correlation", "qa"]


def get_llm(role: Role, settings: Settings | None = None):
    """按角色返回 LLM 实例。

    Parameters
    ----------
    role : ingest | correlation | qa
    settings : 可选，默认用单例配置

    Returns
    -------
    BaseChatModel（langchain 接口，调用方不关心具体后端）
    """
    s = settings or get_settings()

    if s.llm_provider == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore

        model_map = {
            "ingest": s.ollama_ingest_model,
            "correlation": s.ollama_correlation_model,
            "qa": s.ollama_qa_model,
        }
        model = model_map[role]
        if model.startswith("PLACEHOLDER"):
            logger.warning(
                "[LLM] Ollama %s 模型仍为占位符（%s），调用将失败。"
                "请在 .env 填入真实模型名（如 qwen2.5:7b）。",
                role,
                model,
            )
        return ChatOllama(model=model, base_url=s.ollama_base_url, temperature=0.2)

    if s.llm_provider == "api":
        from langchain_openai import ChatOpenAI  # type: ignore

        if s.openai_api_key.startswith("PLACEHOLDER"):
            logger.warning(
                "[LLM] API key 仍为占位符（%s），调用将失败。请在 .env 填入真实 key。",
                s.openai_api_key,
            )
        model_map = {
            "ingest": s.openai_ingest_model,
            "correlation": s.openai_correlation_model,
            "qa": s.openai_qa_model,
        }
        return ChatOpenAI(
            model=model_map[role],
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
            temperature=0.2,
        )

    raise ValueError(f"未知 LLM_PROVIDER: {s.llm_provider}")


def get_embeddings(settings: Settings | None = None):
    """返回 embedding 模型（RAG 用）。

    路由优先级：
    1. ``embed_provider`` 显式配置（local / ollama / api）
    2. fallback 到 ``llm_provider``（向后兼容）

    - local  : 本地 BAAI/bge-m3（sentence-transformers，优先从魔搭社区下载）
    - ollama : Ollama 本地 embedding（如 nomic-embed-text）
    - api    : OpenAI 兼容 API embedding
    """
    s = settings or get_settings()
    provider = s.embed_provider

    # 向后兼容：embed_provider 未显式配置时 fallback 到 llm_provider
    # （pydantic 默认值已是 "local"，仅当 .env 显式设了非 local 才走其他分支）

    if provider == "local":
        from core.tools.embeddings import get_local_embeddings

        return get_local_embeddings(s)

    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings  # type: ignore

        if s.ollama_embed_model.startswith("PLACEHOLDER"):
            logger.warning(
                "[LLM] Ollama embedding 模型仍为占位符（%s）。请在 .env 填入真实模型名（如 nomic-embed-text）。",
                s.ollama_embed_model,
            )
        return OllamaEmbeddings(model=s.ollama_embed_model, base_url=s.ollama_base_url)

    if provider == "api":
        from langchain_openai import OpenAIEmbeddings  # type: ignore

        if s.openai_api_key.startswith("PLACEHOLDER"):
            logger.warning("[LLM] API key 仍为占位符，embedding 调用将失败。")
        # API embedding 模型名复用 qa 槽位或可单独配置；此处用占位符
        return OpenAIEmbeddings(
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
            model="PLACEHOLDER_EMBED_MODEL",
        )

    raise ValueError(f"未知 embed_provider: {provider}")
