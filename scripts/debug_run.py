"""host-delegated 调试入口：返回数据/提示词，同进程模拟 Host 回调。

[适配层] 本脚本不属于任何一条链——它是四条链的命令行调试入口。

    命令                    链
    prepare / ingest        链1+链2 摄取（同进程模拟 prepare→Host→finalize）
    correlate               链3 关联发现
    query                   链4 知识库问答
    index                   src/common/tools/retriever.py 的索引刷新（被链3/链4 触发的那部分）
    status                  只读巡检（Vault / 配置 / 笔记计数）
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# 同时支持 python scripts/debug_run.py 和已安装的 kb-debug。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import typer
from rich.console import Console

from src.common.settings import get_settings

console = Console()
app = typer.Typer(help="host-delegated 调试：生成工作由 Host 完成。", no_args_is_help=True)


def _setup_logging():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)


def _show(result: dict):
    import json
    console.print_json(json.dumps(result, ensure_ascii=False, default=str))


@app.command()
def ingest(
    source: str,
    note_file: Path | None = typer.Option(None, help="Host 生成的 Markdown 文件；缺省时显示 prompt 后询问路径"),
    source_type: str = typer.Option("", help="可选：video_url|video_file|raw_text|note_path；仅调试图支持"),
):
    """同进程 prepare → 显示 prompt → 读取 Host 正文 → finalize。"""
    _setup_logging()
    from src.common.graph_registry import ingestion_finalize_graph, ingestion_prepare_graph
    if source_type not in ("", "video_url", "video_file", "raw_text", "note_path"):
        raise typer.BadParameter("未知 source_type")

    async def run():
        prepared = await ingestion_prepare_graph.ainvoke(
            {"user_input": source, "source_type": source_type or None}
        )
        if prepared.get("error"):
            _show({"error": prepared["error"]})
            raise typer.Exit(1)
        _show({key: prepared.get(key) for key in
               ("prepare_id", "source_type", "raw_content", "prompt_for_host")})
        path = note_file
        if path is None:
            console.print("把 prompt_for_host 交给 Host 生成 Markdown；保持此进程运行。")
            value = typer.prompt("保存正文后输入文件路径（留空结束，不落盘）", default="")
            if not value.strip():
                console.print("已结束；prepare_id 随进程退出失效。")
                return
            path = Path(value.strip()).expanduser()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            _show({"error": str(exc)})
            raise typer.Exit(1) from exc
        result = await ingestion_finalize_graph.ainvoke(
            {"prepare_id": prepared["prepare_id"], "note_content": content}
        )
        if result.get("error"):
            _show({"error": result["error"]})
            raise typer.Exit(1)
        _show({"note_path": result["note_path"]})

    asyncio.run(run())


@app.command()
def prepare(source: str):
    """只预览原始内容和 prompt；退出后会话失效，不能跨 CLI 进程 finalize。"""
    from mcp_server.server import ingest_content_prepare
    _show(asyncio.run(ingest_content_prepare(source)))
    console.print("此进程即将结束，prepare_id 不可用于另一进程。完整调试请使用 ingest。")


@app.command()
def correlate(note_path: str):
    """返回候选片段和 Host 提示词；关联理由由 Host 生成。"""
    _setup_logging()
    from mcp_server.server import trigger_correlation
    _show(asyncio.run(trigger_correlation(note_path)))


@app.command()
def query(question: str):
    """返回检索片段和 Host 提示词；答案由 Host 生成。"""
    _setup_logging()
    from mcp_server.server import query_kb
    _show(asyncio.run(query_kb(question)))


@app.command()
def index():
    """重建 promoted 笔记索引（使用本地 bge-m3）。"""
    _setup_logging()
    from src.common.tools.retriever import index_vault
    _show({"indexed_notes": index_vault()})


@app.command()
def status():
    """查看配置与笔记统计；不加载 Embedding 模型。"""
    from src.vault_io import list_promoted_notes, list_staged_notes
    s = get_settings()
    _show({
        "architecture": "host-delegated",
        "vault": str(s.vault_path), "inbox": str(s.inbox_path),
        "generation": "Host", "session_ttl_minutes": s.ingest_session_ttl_minutes,
        "embedding": s.embed_model_name, "embedding_device": s.embed_device,
        "embedding_cache": str(s.embed_cache_path),
        "video_transcription": "enabled" if s.video_to_text_mcp_enabled else "STUB",
        "obsidian_cli": s.obsidian_skill_enabled,
        "promoted_notes": len(list_promoted_notes(s)),
        "staged_notes": len(list_staged_notes(s)),
    })


if __name__ == "__main__":
    app()
