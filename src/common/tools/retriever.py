"""RAG 检索器 —— 仅检索 status=promoted 的笔记。

[公共文件] 被以下链调用：
  - correlate   ensure_index_fresh + retrieve
  - query       ensure_index_fresh + retrieve
  - 另被 scripts/debug_run.py index 调用 index_vault（全量重建）
本文件同时承担两条链的两种职责：L4 索引刷新与检索本身。若要按链再细看，
ensure_index_fresh/index_vault 属「索引刷新链」，retrieve/hybrid_retrieve 属「检索」。

信任闸门物理隔离（需求第3、6节）：
- 向量库写入时给每条文档打 metadata: {status: promoted}。
- 检索时强制 metadata filter status=promoted，staged 笔记物理上不会进入召回。
- 这不是阈值调节，是架构保证：未审核内容"不可被检索"。

索引策略（两级）：
- index_vault()           : 全量（重新）索引。幂等——先 delete_collection 再重建。
  供 scripts/debug_run.py index 强制全量刷新，以及 manifest 缺失时自动 fallback。
- ensure_index_fresh()    : 基于 mtime manifest 的增量索引。在 query_kb /
  trigger_correlation 子图入口自动调用，保证人工 promote 后无需手动跑 index
  即可被检索到（修复"向量索引从未在生产链路自动刷新"的缺口）。

manifest（chroma_path/index_manifest.json）记录每篇 promoted 笔记的：
    {rel_path: {"mtime": float, "chunk_ids": [str, ...]}}
增量时比对 vault 当前 mtime，仅对 新增/修改 的笔记重新切分索引（先按 ids 删旧
chunk 再 add），对 vault 中已不存在的笔记删其 chunk。重复调用安全，不累积重复。
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from src.common.settings import Settings, get_settings
from src.common.tools.embeddings import get_local_embeddings
from src.vault_io import NoteMeta, list_promoted_notes
from langchain_chroma import Chroma
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 切分
# ---------------------------------------------------------------------------

def _split_note(note: NoteMeta) -> List[Any]:
    """把单篇 promoted 笔记切成可检索的文档块。"""
    headers = [
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
    ]
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)

    chunks = []
    try:
        md_chunks = md_splitter.split_text(note.body)
        for mc in md_chunks:
            for tc in text_splitter.split_text(mc.page_content):
                chunks.append(
                    {
                        "content": tc,
                        "path": note.rel_path,
                        "status": "promoted",  # 物理打标
                        "header_path": mc.metadata.get("h1", "")
                        + " > "
                        + mc.metadata.get("h2", "")
                        + " > "
                        + mc.metadata.get("h3", ""),
                    }
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("[retriever] 切分失败 %s: %s", note.rel_path, e)
    return chunks


def _index_one_note(vectorstore, note: NoteMeta) -> List[str]:
    """把单篇笔记切分后写入向量库，返回新增 chunk 的 ids。"""
    chunks = _split_note(note)
    if not chunks:
        return []
    texts = [c["content"] for c in chunks]
    metadatas = [
        {
            "path": c["path"],
            "status": "promoted",  # 关键：物理打标 promoted
            "header_path": c["header_path"],
        }
        for c in chunks
    ]
    # add_texts 返回 ids 列表（langchain_chroma 默认生成 uuid），供增量删除用
    ids = vectorstore.add_texts(texts, metadatas=metadatas)
    return list(ids)


# ---------------------------------------------------------------------------
# manifest（mtime 增量索引的基础）
# ---------------------------------------------------------------------------

def _manifest_path(settings: Settings):
    return settings.chroma_path / "index_manifest.json"


def _mtime(path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _load_manifest(path) -> Optional[dict]:
    """加载 manifest。不存在或解析失败返回 None（调用方据此全量重建）。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[retriever] manifest 解析失败，将全量重建: %s", e)
        return None


def _save_manifest(path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("[retriever] manifest 写入失败（不影响本次索引，但下次会重复全量）: %s", e)


def _delete_chunks(vectorstore, ids: List[str], rel_path: str) -> None:
    """按 ids 删除旧 chunk，失败仅记日志（不阻塞后续索引）。"""
    if not ids:
        return
    try:
        vectorstore.delete(ids=ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("[retriever] 删除旧 chunk 失败 %s: %s", rel_path, e)


# ---------------------------------------------------------------------------
# 全量索引（幂等）—— debug_run.py index / manifest 缺失 fallback
# ---------------------------------------------------------------------------

def index_vault(settings=None) -> int:
    """全量（重新）索引所有 promoted 笔记。

    幂等：先 delete_collection 再重建，重复调用不会累积重复 chunk。
    同时写入 manifest，作为后续 ensure_index_fresh 增量的基线。

    Returns
    -------
    int : 索引的笔记数
    """
    s = settings or get_settings()

    promoted = list_promoted_notes(s)
    embeddings = get_local_embeddings(s)
    s.chroma_path.mkdir(parents=True, exist_ok=True)

    # 幂等：先删除旧集合再重建（修复此前"只 add 不清空"导致重复 chunk 的问题）
    vectorstore = Chroma(
        collection_name=s.rag_collection_name,
        embedding_function=embeddings,
        persist_directory=str(s.chroma_path),
    )
    try:
        vectorstore.delete_collection()
        logger.info("[retriever] 已删除旧集合，开始全量重建")
    except Exception as e:  # noqa: BLE001
        logger.debug("[retriever] 删除集合失败（可能首次创建）: %s", e)
    # delete_collection 后需重新构造实例，新集合在首次 add 时自动创建
    vectorstore = Chroma(
        collection_name=s.rag_collection_name,
        embedding_function=embeddings,
        persist_directory=str(s.chroma_path),
    )

    manifest: dict = {}
    total_notes = 0
    total_chunks = 0
    for note in promoted:
        ids = _index_one_note(vectorstore, note)
        manifest[note.rel_path] = {"mtime": _mtime(note.path), "chunk_ids": ids}
        total_notes += 1
        total_chunks += len(ids)

    _save_manifest(_manifest_path(s), manifest)
    # 索引变更后失效 BM25 缓存，下次检索时重建
    from src.common.tools.hybrid_search import invalidate_bm25_cache
    invalidate_bm25_cache(s)
    logger.info(
        "[retriever] 全量索引完成：%d 篇 promoted 笔记 / %d 个块", total_notes, total_chunks
    )
    return total_notes


# ---------------------------------------------------------------------------
# 增量索引 —— query_kb / trigger_correlation 入口自动调用
# ---------------------------------------------------------------------------

def ensure_index_fresh(settings=None) -> dict:
    """增量刷新索引：基于 mtime manifest，只更新 新增/修改/删除 的 promoted 笔记。

    在 query_kb / trigger_correlation 子图入口自动调用，保证人工 promote 后无需
    手动跑 `debug_run.py index` 即可被检索到。

    降级：embedding/向量库不可用时（如占位符模式），记 warning 并返回空变更，
    不抛异常——query 仍可继续（命中为空），不阻塞主链路。

    Returns
    -------
    dict : {"added": int, "updated": int, "removed": int, "total": int, "rebuilt": bool}
    """
    s = settings or get_settings()
    try:
        return _ensure_index_fresh_impl(s)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[retriever] 增量索引失败，跳过（query 仍可继续，可能命中为空）: %s", e
        )
        return {
            "added": 0,
            "updated": 0,
            "removed": 0,
            "total": 0,
            "rebuilt": False,
            "error": str(e),
        }


def _ensure_index_fresh_impl(s: Settings) -> dict:
    manifest_path = _manifest_path(s)

    promoted = list_promoted_notes(s)
    current: dict[str, NoteMeta] = {n.rel_path: n for n in promoted}
    current_mtimes: dict[str, float] = {p: _mtime(n.path) for p, n in current.items()}

    prev = _load_manifest(manifest_path)

    # manifest 缺失/损坏 → 全量重建（幂等），保证与向量库一致
    if prev is None:
        n = index_vault(s)
        return {
            "added": n,
            "updated": 0,
            "removed": 0,
            "total": n,
            "rebuilt": True,
        }

    embeddings = get_local_embeddings(s)
    s.chroma_path.mkdir(parents=True, exist_ok=True)
    vectorstore = Chroma(
        collection_name=s.rag_collection_name,
        embedding_function=embeddings,
        persist_directory=str(s.chroma_path),
    )

    added, updated, removed = 0, 0, 0

    # 1. 新增 / 修改
    for rel_path, note in current.items():
        mtime = current_mtimes[rel_path]
        prev_entry = prev.get(rel_path)
        if prev_entry is None:
            ids = _index_one_note(vectorstore, note)
            prev[rel_path] = {"mtime": mtime, "chunk_ids": ids}
            added += 1
            logger.debug("[retriever] 增量新增笔记: %s", rel_path)
        elif float(prev_entry.get("mtime", 0)) != mtime:
            _delete_chunks(vectorstore, list(prev_entry.get("chunk_ids", [])), rel_path)
            ids = _index_one_note(vectorstore, note)
            prev[rel_path] = {"mtime": mtime, "chunk_ids": ids}
            updated += 1
            logger.debug("[retriever] 增量更新笔记: %s", rel_path)

    # 2. 删除（vault 里没了，但 manifest 里有：笔记被删 / 被降级回 staged）
    for rel_path in list(prev.keys()):
        if rel_path not in current:
            _delete_chunks(vectorstore, list(prev[rel_path].get("chunk_ids", [])), rel_path)
            del prev[rel_path]
            removed += 1
            logger.debug("[retriever] 增量删除笔记: %s", rel_path)

    _save_manifest(manifest_path, prev)
    # 索引变更后失效 BM25 缓存，下次检索时重建
    from src.common.tools.hybrid_search import invalidate_bm25_cache
    invalidate_bm25_cache(s)

    total = len(current)
    logger.info(
        "[retriever] 增量索引完成：新增 %d / 更新 %d / 删除 %d / 当前 promoted %d",
        added, updated, removed, total,
    )
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "total": total,
        "rebuilt": False,
    }


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------

def retrieve(
    query: str,
    top_k: int | None = None,
    settings=None,
) -> List[dict]:
    """检索 promoted 笔记片段。

    信任闸门：metadata filter status=promoted 强制过滤，
    staged 笔记即使被误索引也不会被召回。

    混合检索（settings.hybrid_search_enabled=True 时启用）：
    BM25 稀疏 + 向量 Dense 并行 → RRF 融合，兼顾关键词精度与语义相似。
    关闭时退回纯向量检索。
    """
    s = settings or get_settings()
    k = top_k or s.rag_top_k
    embeddings = get_local_embeddings(s)

    # 混合检索路径
    if s.hybrid_search_enabled:
        from src.common.tools.hybrid_search import hybrid_retrieve
        try:
            return hybrid_retrieve(query, top_k=k, settings=s, embeddings=embeddings)
        except Exception as e:  # noqa: BLE001
            logger.warning("[retriever] 混合检索失败，降级为纯向量检索: %s", e)
            # 落入下方纯向量检索（复用已构造的 embeddings）
    vectorstore = Chroma(
        collection_name=s.rag_collection_name,
        embedding_function=embeddings,
        persist_directory=str(s.chroma_path),
    )

    # 关键：metadata filter 物理隔离 staged
    results = vectorstore.similarity_search_with_score(
        query,
        k=k,
        filter={"status": "promoted"},
    )

    chunks = []
    for doc, score in results:
        chunks.append(
            {
                "content": doc.page_content,
                "path": doc.metadata.get("path", "unknown"),
                "score": float(score),
                "header_path": doc.metadata.get("header_path", ""),
            }
        )
    return chunks
