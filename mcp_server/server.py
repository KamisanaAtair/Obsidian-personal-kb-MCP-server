"""Host-delegated MCP Server：四个工具，生成式判断由 Host 的对话模型执行。

摄取：prepare 返回原文和 prompt → Host 生成笔记 → finalize 写 staged 草稿。
关联/问答：一次调用返回检索数据和 prompt，Host 生成最终结果，无需回传。
不调用服务端生成模型，也不请求 MCP sampling。Promotion 仍需人工在 Obsidian 完成。

运行：python -m mcp_server.server（stdio 传输）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config.settings import get_settings
from core.graph import (
    correlation_graph,
    ingestion_finalize_graph,
    ingestion_prepare_graph,
    retrieval_graph,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("personal-kb-multiagent")

# prepare 结果落盘（JSONL，追加写）。用途：长视频转写可能超过 MCP 客户端
# 超时（服务端仍会完成转写），客户端拿不到响应时，Host 可从此文件恢复
# prepare_id / raw_content / prompt_for_host，直接调用 finalize，避免重复转写。
_PREPARE_LOG = Path(__file__).resolve().parents[1] / "logs" / "ingest_prepare.jsonl"


def _log_prepare_result(result: dict) -> None:
    """把 prepare 结果写入 JSONL 日志（失败不影响主流程）。

    注意：只序列化可 JSON 化的四个字段（图状态中还含 AIMessage 等对象）。
    """
    try:
        _PREPARE_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "prepare_id": result.get("prepare_id"),
            "source_type": result.get("source_type"),
            "raw_content": result.get("raw_content"),
            "prompt_for_host": result.get("prompt_for_host"),
        }
        with _PREPARE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except (OSError, TypeError) as e:
        logger.warning("[server] prepare 结果落盘失败: %s", e)


@mcp.tool()
async def ingest_content_prepare(user_input: str) -> dict:
    """摄取第一步：解析来源并读取/转写原文，不写笔记、不调用生成式 LLM。

    user_input 支持纯文本，或自然语言说明混合视频 URL / 本地视频文件路径。
    自然语言整理要求会保留在 prompt_for_host 中。

    Host 必须用自身对话模型执行返回的 prompt_for_host，生成完整 Markdown 笔记，
    随后调用 ingest_content_finalize(prepare_id, note_content) 保存。
    prepare_id 默认 60 分钟有效且仅保存在当前服务器进程；请在同一运行实例内完成。
    返回 {prepare_id, source_type, raw_content, prompt_for_host}。
    """
    result = await ingestion_prepare_graph.ainvoke({"user_input": user_input})
    _log_prepare_result(result)
    return {
        "prepare_id": result["prepare_id"],
        "source_type": result["source_type"],
        "raw_content": result["raw_content"],
        "prompt_for_host": result["prompt_for_host"],
    }


@mcp.tool()
async def ingest_content_finalize(prepare_id: str, note_content: str) -> dict:
    """摄取第二步：接收 Host 生成的完整 Markdown，校验并写入 Inbox/。

    prepare_id 必须来自本进程尚未过期的 ingest_content_prepare 调用。
    来源信息从服务端会话取回；无论 Host 声明何种状态，始终强制 staged。
    返回 {note_path} 或 {error}。遇到无效/过期会话请重新 prepare。
    保存后需用户在 Obsidian 审核并手动改为 promoted，才能用于知识库检索。
    """
    result = await ingestion_finalize_graph.ainvoke(
        {"prepare_id": prepare_id, "note_content": note_content}
    )
    if result.get("error"):
        return {"error": result["error"]}
    return {"note_path": result["note_path"]}


@mcp.tool()
async def trigger_correlation(note_path: str) -> dict:
    """对 promoted 笔记检索关联候选，返回 {candidates, prompt_for_host}。

    note_path 是相对 Vault 根目录的路径。未 promoted、缺失或无候选时返回空列表
    和 null prompt。有效候选为 {path, snippet, score}。
    Host 用自身模型执行 prompt_for_host，生成关联理由并直接向用户展示，
    无需回调本服务器。本工具不修改笔记；用户决定是否手动添加双链。
    """
    result = await correlation_graph.ainvoke({"note_path": note_path})
    return {
        "candidates": result.get("candidates", []),
        "prompt_for_host": result.get("prompt_for_host"),
    }


@mcp.tool()
async def query_kb(question: str) -> dict:
    """检索 promoted 笔记，返回 {retrieved_chunks, prompt_for_host, no_hit_message}。

    调用时按 mtime 增量刷新索引。命中片段包含 content/path/score/source；
    Host 用自身模型执行 prompt_for_host，生成带引用的答案并直接向用户展示，
    无需回调服务器。无命中时 prompt_for_host 为 null，直接展示 no_hit_message。
    staged 笔记不进入检索。本工具不生成答案，也不修改笔记。
    """
    result = await retrieval_graph.ainvoke({"user_input": question})
    return {
        "retrieved_chunks": result.get("retrieved_chunks", []),
        "prompt_for_host": result.get("prompt_for_host"),
        "no_hit_message": result.get("no_hit_message"),
    }


def main() -> None:
    """启动 MCP Server（stdio 传输）。"""
    s = get_settings()
    logger.info(
        "启动 Host-delegated MCP Server | Vault=%s | stub_mode=%s",
        s.vault_root,
        s.is_stub_mode,
    )
    if s.is_stub_mode:
        logger.warning(
            "视频转写或 Obsidian CLI 配置未全部启用；"
            "视频可能使用占位转写，笔记可通过文件系统写入。请检查 .env。"
        )
    mcp.run()


if __name__ == "__main__":
    main()
