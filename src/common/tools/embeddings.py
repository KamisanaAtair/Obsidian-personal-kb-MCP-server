"""本地 Embedding 工厂 —— 基于 BAAI/bge-m3 的 sentence-transformers 实现。

[公共文件] 被以下链调用：
  - correlate、query（间接：经 src/common/tools/retriever.py 与 hybrid_search.py）
  - 另被 scripts/download_embed_model.py 在安装期调用

设计要点
--------
1. **独立于 LLM provider**：embedding 可走 local（bge-m3），LLM 走 ollama/api，互不耦合。
2. **优先从魔搭社区（ModelScope）下载**：国内网络友好，fallback 到 HuggingFace。
3. **本地缓存**：首次下载后缓存到 ``embed_model_cache_dir``，后续直接加载无需联网。
4. **LangChain 兼容**：返回 ``HuggingFaceEmbeddings``，接口与 ``OllamaEmbeddings`` 一致，
   retriever 层无感知切换。

bge-m3 特性
-----------
- 1024 维稠密向量，支持多语言（中英等 100+ 语言）
- 可同时产出 dense / sparse / multi-vector(colbert) 三种表示；
  本项目 RAG 场景只需 dense，sentence-transformers 默认输出 dense。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.common.settings import Settings, get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 模型下载
# ---------------------------------------------------------------------------

def ensure_model_downloaded(settings: Settings | None = None) -> Path:
    """确保 bge-m3 模型已下载到本地缓存目录。

    下载策略：
    1. 如果 ``embed_model_cache_dir`` 已存在且包含模型文件（config.json），直接返回。
    2. 否则按 ``embed_model_source`` 从 ModelScope / HuggingFace 下载。

    Returns
    -------
    Path : 模型本地目录
    """
    s = settings or get_settings()
    cache_dir = s.embed_cache_path

    # 已下载过：检查关键文件是否存在
    if _is_model_present(cache_dir):
        logger.info("[embeddings] 模型已缓存于 %s，跳过下载", cache_dir)
        return cache_dir

    cache_dir.mkdir(parents=True, exist_ok=True)

    if s.embed_model_source == "modelscope":
        return _download_from_modelscope(s.embed_model_name, cache_dir)
    else:
        return _download_from_huggingface(s.embed_model_name, cache_dir)


def _is_model_present(path: Path) -> bool:
    """检查目录是否包含有效的模型文件。"""
    if not path.exists() or not path.is_dir():
        return False
    # bge-m3 的关键文件：config.json + 至少一个权重文件
    has_config = (path / "config.json").exists()
    has_weights = any(
        (path / f).exists()
        for f in ("pytorch_model.bin", "model.safetensors", "pytorch_model.safetensors")
    )
    # modelscope 下载可能把文件放在子目录里
    if not has_config:
        subdirs = [p for p in path.iterdir() if p.is_dir()]
        for sd in subdirs:
            if (sd / "config.json").exists():
                has_config = True
                has_weights = has_weights or any(
                    (sd / f).exists()
                    for f in ("pytorch_model.bin", "model.safetensors", "pytorch_model.safetensors")
                )
                if has_config and has_weights:
                    return True
    return has_config and has_weights


def _download_from_modelscope(model_name: str, cache_dir: Path) -> Path:
    """从魔搭社区下载模型。

    使用 modelscope.snapshot_download，支持断点续传。
    用 local_dir 直接下载到目标目录，避免 modelscope 的嵌套目录结构。
    """
    logger.info("[embeddings] 从魔搭社区下载 %s → %s", model_name, cache_dir)
    try:
        from modelscope import snapshot_download  # type: ignore
    except ImportError as e:
        raise ImportError(
            "modelscope 未安装。请运行: pip install modelscope"
        ) from e

    # 屏蔽 modelscope 的 SoftFileLock fallback 良性警告刷屏（Windows 下 os.link
    # 不可用会 fallback，属正常行为，但日志噪音很大）
    logging.getLogger("modelscope_hub").setLevel(logging.ERROR)

    downloaded = snapshot_download(
        model_name,
        local_dir=str(cache_dir),  # 直接下载到目标目录，不创建嵌套结构
    )
    downloaded_path = Path(downloaded)
    logger.info("[embeddings] 下载完成: %s", downloaded_path)

    return downloaded_path


def _download_from_huggingface(model_name: str, cache_dir: Path) -> Path:
    """从 HuggingFace 下载模型（fallback）。"""
    logger.info("[embeddings] 从 HuggingFace 下载 %s → %s", model_name, cache_dir)
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as e:
        raise ImportError(
            "huggingface_hub 未安装。请运行: pip install huggingface_hub"
        ) from e

    downloaded = snapshot_download(
        repo_id=model_name,
        local_dir=str(cache_dir),
    )
    logger.info("[embeddings] 下载完成: %s", downloaded)
    return Path(downloaded)


# ---------------------------------------------------------------------------
# Embedding 工厂
# ---------------------------------------------------------------------------

# 模块级单例：模型加载开销大，整个进程只加载一次
_embeddings_instance: Any = None


def get_local_embeddings(settings: Settings | None = None) -> Any:
    """返回基于本地 bge-m3 的 LangChain Embeddings 实例。

    单例缓存（模块级变量）：模型加载开销大，整个进程只加载一次。

    Returns
    -------
    HuggingFaceEmbeddings : LangChain 兼容的 embedding 接口
    """
    global _embeddings_instance
    if _embeddings_instance is not None:
        return _embeddings_instance

    s = settings or get_settings()

    try:
        from langchain_huggingface import HuggingFaceEmbeddings  # type: ignore
    except ImportError as e:
        raise ImportError(
            "langchain-huggingface 未安装。请运行: pip install langchain-huggingface"
        ) from e

    # 确保模型已下载
    model_path = ensure_model_downloaded(s)

    # 设备自适应：配置了 cuda 但运行环境不可用时回退 cpu（适配性优先，
    # 避免在无 GPU / CPU 版 torch 的机器上直接崩溃）
    device = _resolve_device(s.embed_device)

    # bge-m3 需要查询前加 "query: " 前缀（仅查询时），但 sentence-transformers
    # 默认不加。HuggingFaceEmbeddings 的 encode_kwargs 不支持分场景前缀，
    # 因此这里不加前缀——bge-m3 在不加前缀时仍有很好的效果（与官方推荐一致，
    # 仅在需要极致精度时才加前缀）。
    logger.info(
        "[embeddings] 加载 bge-m3: model_path=%s, device=%s",
        model_path, device,
    )

    _embeddings_instance = HuggingFaceEmbeddings(
        model_name=str(model_path),
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},  # bge-m3 推荐 L2 归一化
    )
    return _embeddings_instance


def _resolve_device(requested: str) -> str:
    """解析实际可用的推理设备。

    配置为 cuda 时校验运行环境（CUDA 版 torch + 可用显卡），
    不满足则回退 cpu 并记录警告，保证任何机器都能跑。
    """
    requested = (requested or "cpu").lower().strip()
    if requested != "cuda":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        logger.warning(
            "[embeddings] 配置 device=cuda 但 CUDA 不可用"
            "（CPU 版 torch 或无 GPU），回退 cpu"
        )
    except Exception as e:  # pragma: no cover - torch 异常属极端情况
        logger.warning("[embeddings] 校验 CUDA 失败（%s），回退 cpu", e)
    return "cpu"
