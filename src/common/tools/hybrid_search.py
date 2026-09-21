"""混合检索 —— BM25 稀疏检索 + 向量 Dense 检索 + RRF 融合。

[公共文件] 被以下链调用：
  - correlate、query（间接：唯一调用方是 src/common/tools/retriever.py）

参考方案
--------
- LangChain EnsembleRetriever + BM25Retriever 的方法论（RRF 融合）
- thistleknot/bm25-chroma 的加权 RRF 实现（bm25_ratio 控制两路权重）
- rank_bm25.BM25Okapi 作为稀疏检索引擎，jieba 做中文分词

设计要点
--------
1. **BM25 索引从 Chroma 已存储文档构建**：保证与向量库完全同步，无需独立持久化。
   索引刷新（index_vault / ensure_index_fresh）后调 ``invalidate_bm25_cache()`` 失效缓存。
2. **模块级缓存**：BM25 索引构建开销 O(N)，同一进程内只构建一次，索引变更后失效重建。
3. **中文分词**：优先 jieba（中英混合笔记效果好），jieba 不可用时 fallback 简单分词。
4. **加权 RRF 融合**：score(d) = w_sparse/(k+rank_sparse) + w_dense/(k+rank_dense)，k=60 经验常数。
   RRF 只用排名不用原始分数，天然避免 BM25 与 cosine 不可比的问题。
5. **信任闸门**：BM25 检索同样只作用于 status=promoted 的 chunk（索引时已物理打标，
   BM25 索引从 Chroma 读取时天然只含 promoted chunk）。
6. **优雅降级**：rank_bm25 / jieba 未安装或 BM25 索引为空时，自动退化为纯向量检索，
   不阻塞主链路。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any, List, Optional, Tuple

from src.common.settings import Settings, get_settings
from src.common.tools.embeddings import get_local_embeddings

logger = logging.getLogger(__name__)

# RRF 经验常数（来自 Cormack & Matusevych 2011 论文，业界标准值）
_RRF_K_DEFAULT = 60


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------

_jieba_available: Optional[bool] = None


def _tokenize(text: str) -> List[str]:
    """对文本分词，供 BM25 使用。

    优先 jieba（中英混合效果好），不可用时 fallback 到简单空格+字符分词。
    结果已过滤空白 token。
    """
    global _jieba_available
    if _jieba_available is None:
        try:
            import jieba  # noqa: F401  # type: ignore
            _jieba_available = True
        except ImportError:
            _jieba_available = False
            logger.warning(
                "[hybrid] jieba 未安装，BM25 将使用简单分词（中文效果较差）。"
                "建议 pip install jieba"
            )

    if _jieba_available:
        import jieba  # type: ignore
        return [t for t in jieba.cut(text) if t.strip()]

    # fallback：英文按空格分，中文按单字拆（粗粒度但能用）
    tokens: List[str] = []
    for raw in text.split():
        buf = ""
        for ch in raw:
            if "\u4e00" <= ch <= "\u9fff":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(ch)
            else:
                buf += ch
        if buf:
            tokens.append(buf)
    return tokens


# ---------------------------------------------------------------------------
# BM25 索引
# ---------------------------------------------------------------------------

class BM25Index:
    """BM25 稀疏检索索引。

    从 Chroma collection 的已存储文档构建，保证与向量库内容完全同步。
    线程安全（构建后只读）。
    """

    def __init__(self, chunks: List[dict]):
        """从 chunk 列表构建 BM25 索引。

        Parameters
        ----------
        chunks : [{content, path, header_path, chunk_id}]
            chunk_id 是 Chroma 分配的 id，用作去重 key
        """
        self._chunks = chunks
        self._tokenized_corpus = [_tokenize(c["content"]) for c in chunks]
        self._bm25 = self._build_bm25()
        self._count = len(chunks)

    def _build_bm25(self):
        """构建 BM25Okapi 实例。"""
        if not self._chunks:
            return None
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("[hybrid] rank_bm25 未安装，BM25 检索不可用。pip install rank_bm25")
            return None
        # BM25Okapi 要求 corpus 非空
        if not any(self._tokenized_corpus):
            return None
        return BM25Okapi(self._tokenized_corpus)

    def search(self, query: str, top_n: int = 20) -> List[dict]:
        """BM25 检索，返回 top_n 个 chunk（带 bm25_score）。

        Returns
        -------
        list[dict] : [{content, path, header_path, chunk_id, score, source: "bm25"}]
                     按 bm25_score 降序
        """
        if self._bm25 is None or self._count == 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)

        # 取 top_n（按分数降序）
        n = min(top_n, self._count)
        # argsort 降序取前 n
        ranked_indices = sorted(range(self._count), key=lambda i: scores[i], reverse=True)[:n]

        results = []
        for idx in ranked_indices:
            score = float(scores[idx])
            if score <= 0:
                continue  # 过滤零分（无任何词命中）
            chunk = self._chunks[idx]
            results.append({
                "content": chunk["content"],
                "path": chunk.get("path", "unknown"),
                "header_path": chunk.get("header_path", ""),
                "chunk_id": chunk.get("chunk_id", ""),
                "score": score,
                "source": "bm25",
            })
        return results

    @property
    def count(self) -> int:
        return self._count


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

_bm25_cache: dict[str, Tuple[int, BM25Index]] = {}
_bm25_lock = threading.Lock()


def _cache_key(settings: Settings) -> str:
    return f"{settings.chroma_path}|{settings.rag_collection_name}"


def invalidate_bm25_cache(settings: Settings | None = None) -> None:
    """失效 BM25 索引缓存。

    在 index_vault / ensure_index_fresh 修改向量库后调用，保证下次检索时重建 BM25。
    """
    global _bm25_cache
    s = settings or get_settings()
    key = _cache_key(s)
    with _bm25_lock:
        _bm25_cache.pop(key, None)
    logger.debug("[hybrid] BM25 缓存已失效: %s", key)


def _get_bm25_index(vectorstore, settings: Settings) -> Optional[BM25Index]:
    """获取 BM25 索引（带缓存）。

    从 Chroma collection 的已存储文档构建，保证与向量库同步。
    索引为空或构建失败时返回 None（调用方据此降级为纯向量检索）。
    """
    key = _cache_key(settings)
    with _bm25_lock:
        cached = _bm25_cache.get(key)
        if cached is not None:
            count, index = cached
            # 校验当前 collection 数量是否与缓存一致
            try:
                current_count = vectorstore._collection.count()
            except Exception:  # noqa: BLE001
                current_count = count  # 无法获取数量时信任缓存
            if current_count == count:
                return index if index.count > 0 else None
            # 数量变了，缓存失效
            _bm25_cache.pop(key, None)

    # 从 Chroma 读取全部文档构建 BM25 索引
    try:
        raw = vectorstore._collection.get(include=["documents", "metadatas"])
    except Exception as e:  # noqa: BLE001
        logger.warning("[hybrid] 从 Chroma 读取文档失败，BM25 不可用: %s", e)
        return None

    ids = raw.get("ids", [])
    documents = raw.get("documents", [])
    metadatas = raw.get("metadatas", [])

    if not documents:
        with _bm25_lock:
            _bm25_cache[key] = (0, BM25Index([]))
        return None

    chunks = []
    for i, doc_text in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) else {}
        chunks.append({
            "content": doc_text,
            "path": meta.get("path", "unknown"),
            "header_path": meta.get("header_path", ""),
            "chunk_id": ids[i] if i < len(ids) else "",
        })

    index = BM25Index(chunks)
    with _bm25_lock:
        _bm25_cache[key] = (len(chunks), index)
    logger.info("[hybrid] BM25 索引构建完成: %d 个 chunk", index.count)
    return index if index.count > 0 else None


# ---------------------------------------------------------------------------
# RRF 融合
# ---------------------------------------------------------------------------

def _chunk_key(chunk: dict) -> str:
    """生成 chunk 的去重 key（content 的 hash，避免内存问题）。"""
    content = chunk.get("content", "")
    path = chunk.get("path", "")
    return hashlib.md5(f"{path}::{content[:200]}".encode()).hexdigest()


def reciprocal_rank_fusion(
    dense_results: List[dict],
    sparse_results: List[dict],
    k: int = _RRF_K_DEFAULT,
    weights: Tuple[float, float] = (0.5, 0.5),
) -> List[dict]:
    """加权倒数排序融合（Reciprocal Rank Fusion）。

    公式: score(d) = w_dense * 1/(k + rank_dense) + w_sparse * 1/(k + rank_sparse)

    只用排名不用原始分数，天然避免 BM25 与 cosine 不可比的问题。
    在两路都出现的 chunk 得分叠加，排名更靠前。

    Parameters
    ----------
    dense_results : 向量检索结果（已按相似度降序）
    sparse_results : BM25 检索结果（已按 bm25 分数降序）
    k : RRF 平滑常数，默认 60（业界标准）
    weights : (w_dense, w_sparse)，默认 (0.5, 0.5) 等权

    Returns
    -------
    list[dict] : 融合后结果（按 RRF 分数降序），每条含 rrf_score 字段
    """
    w_dense, w_sparse = weights
    scores: dict[str, float] = {}
    chunk_map: dict[str, dict] = {}

    # 向量路
    for rank, chunk in enumerate(dense_results):
        key = _chunk_key(chunk)
        if key not in scores:
            scores[key] = 0.0
            chunk_map[key] = dict(chunk)  # 浅拷贝保留原始字段
        scores[key] += w_dense * (1.0 / (k + rank + 1))

    # BM25 路
    for rank, chunk in enumerate(sparse_results):
        key = _chunk_key(chunk)
        if key not in scores:
            scores[key] = 0.0
            # 如果向量路已有，保留向量路的 chunk 信息；否则用 BM25 的
            if key not in chunk_map:
                chunk_map[key] = dict(chunk)
        scores[key] += w_sparse * (1.0 / (k + rank + 1))

    # 按融合分数降序排列
    ranked_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    results = []
    for key in ranked_keys:
        chunk = chunk_map[key]
        chunk["score"] = scores[key]        # 用 RRF 分数覆盖（便于下游统一处理）
        chunk["source"] = "hybrid"           # 标记来源为混合检索
        results.append(chunk)
    return results


# ---------------------------------------------------------------------------
# 混合检索主入口
# ---------------------------------------------------------------------------

def hybrid_retrieve(
    query: str,
    top_k: int = 6,
    settings: Settings | None = None,
    embeddings: Any = None,
) -> List[dict]:
    """混合检索：BM25 + 向量并行 → RRF 融合 → 取 top_k。

    信任闸门：BM25 索引从 Chroma 读取（只含 status=promoted 的 chunk），
    向量路也带 metadata filter，双路都物理隔离 staged。

    优雅降级：
    - rank_bm25 / jieba 未安装 → 纯向量检索
    - BM25 索引为空 → 纯向量检索
    - 向量库不可用 → 返回空列表（不抛异常）

    Parameters
    ----------
    query : 用户查询
    top_k : 最终返回的 chunk 数
    settings : 配置（含权重、RRF k、候选倍数等）
    embeddings : embedding 实例（可选）。由调用方传入可保证测试 monkeypatch 生效，
                 None 时内部自行 get_local_embeddings()

    Returns
    -------
    list[dict] : [{content, path, header_path, score(rrf), source}]
    """
    s = settings or get_settings()

    from langchain_chroma import Chroma

    # embeddings 由调用方传入（保证 retriever.py 的 monkeypatch 传递生效）
    if embeddings is None:
        embeddings = get_local_embeddings(s)
    vectorstore = Chroma(
        collection_name=s.rag_collection_name,
        embedding_function=embeddings,
        persist_directory=str(s.chroma_path),
    )

    # 候选数：每路取 top_k * multiplier，融合后再截断到 top_k
    candidate_n = max(top_k * s.hybrid_candidate_multiplier, top_k)

    # ---- 向量路（Dense）----
    dense_results: List[dict] = []
    try:
        results = vectorstore.similarity_search_with_score(
            query,
            k=candidate_n,
            filter={"status": "promoted"},
        )
        for doc, score in results:
            dense_results.append({
                "content": doc.page_content,
                "path": doc.metadata.get("path", "unknown"),
                "header_path": doc.metadata.get("header_path", ""),
                "score": float(score),
                "source": "dense",
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("[hybrid] 向量检索失败: %s", e)

    # ---- BM25 路（Sparse）----
    sparse_results: List[dict] = []
    bm25_index = _get_bm25_index(vectorstore, s)
    if bm25_index is not None:
        sparse_results = bm25_index.search(query, top_n=candidate_n)

    # ---- 融合 ----
    if not dense_results and not sparse_results:
        return []

    # 只有一路有结果时，直接用该路结果（无需融合）
    if not sparse_results:
        logger.debug("[hybrid] BM25 无结果，退化为纯向量检索")
        return dense_results[:top_k]
    if not dense_results:
        logger.debug("[hybrid] 向量无结果，退化为纯 BM25 检索")
        return sparse_results[:top_k]

    weights = (1.0 - s.hybrid_bm25_weight, s.hybrid_bm25_weight)
    fused = reciprocal_rank_fusion(
        dense_results,
        sparse_results,
        k=s.hybrid_rrf_k,
        weights=weights,
    )
    logger.info(
        "[hybrid] 融合完成: dense=%d, sparse=%d → fused=%d, 取 top %d",
        len(dense_results), len(sparse_results), len(fused), top_k,
    )
    return fused[:top_k]
