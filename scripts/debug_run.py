"""第一层调试入口（需求第9节）：绕开 MCP / Host，直接调用 core 子图。

用法：
    python scripts/debug_run.py                # 交互菜单
    python scripts/debug_run.py ingest <视频链接或文本>
    python scripts/debug_run.py correlate <笔记相对路径>
    python scripts/debug_run.py query <问题>
    python scripts/debug_run.py index           # 索引 promoted 笔记到本地向量库
    python scripts/debug_run.py status          # 查看配置与 Vault 状态

设计目的：
生产环境只通过 MCP 被 Host 调用，但开发阶段每次经 Host 调试成本高（token+判断波动）。
本脚本直接驱动 core，验证核心业务逻辑本身对不对。
"""

from __future__ import annotations

import asyncio
import logging
import sys

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

from config.settings import get_settings

console = Console()
app = typer.Typer(help="个人知识库多智能体系统 — 第一层调试入口（绕开 MCP/Host）")


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


@app.command()
def ingest(source: str, source_type: str = typer.Option("", help="video_url|raw_text|note_path，留空自动判别")):
    """摄取外部内容为 staged 草稿笔记。"""
    _setup_logging()
    from core.graph import ingestion_graph

    async def run():
        result = await ingestion_graph.ainvoke(
            {"user_input": source, "source_type": source_type or None}
        )
        console.print(Panel.fit(
            f"笔记路径: {result.get('note_path', '?')}\n"
            f"状态: staged（需人工 promote）",
            title="Ingestion 结果",
            style="cyan",
        ))

    asyncio.run(run())


@app.command()
def correlate(note_path: str):
    """对已 promoted 的笔记触发关联发现。"""
    _setup_logging()
    from core.graph import correlation_graph

    async def run():
        result = await correlation_graph.ainvoke({"note_path": note_path})
        related = result.get("related_notes", [])
        if not related:
            console.print("[yellow]暂无关联建议[/yellow]")
            return
        for i, item in enumerate(related, 1):
            console.print(f"[cyan]{i}.[/cyan] {item.get('path', '?')}")
            console.print(f"   理由: {item.get('reason', '（无）')}")
            console.print(f"   相似度: {item.get('score', 0):.3f}")

    asyncio.run(run())


@app.command()
def query(question: str):
    """检索知识库回答问题。"""
    _setup_logging()
    from core.graph import retrieval_graph

    async def run():
        result = await retrieval_graph.ainvoke({"user_input": question})
        console.print(Panel.fit(
            result.get("answer", "（无回答）"),
            title=f"QA 回答（引用 {len(result.get('retrieved_chunks', []))} 条）",
            style="green",
        ))

    asyncio.run(run())


@app.command()
def index():
    """扫描 Vault，把所有 promoted 笔记索引入本地向量库。"""
    _setup_logging()
    from core.tools.retriever import index_vault

    n = index_vault()
    console.print(f"[green]已索引 {n} 篇 promoted 笔记[/green]")


@app.command()
def status():
    """查看当前配置与 Vault 状态。"""
    _setup_logging()
    s = get_settings()
    from core.tools.vault_io import list_promoted_notes, list_staged_notes

    promoted = list_promoted_notes(s)
    staged = list_staged_notes(s)
    console.print(Panel.fit(
        f"Vault: {s.vault_root}\n"
        f"Inbox: {s.inbox_path}\n"
        f"LLM provider: {s.llm_provider}\n"
        f"Stub 模式: {s.is_stub_mode}\n"
        f"视频转文档 MCP: {'已启用' if s.video_to_text_mcp_enabled else 'STUB（待接入）'}\n"
        f"Obsidian skill: {'已启用' if s.obsidian_skill_enabled else 'STUB（待接入）'}\n"
        f"\n笔记统计:\n"
        f"  promoted: {len(promoted)} 篇\n"
        f"  staged:    {len(staged)} 篇",
        title="系统状态",
        style="magenta",
    ))
    if staged:
        console.print("\n[dim]待审队列（staged）:[/dim]")
        for m in staged[:20]:
            console.print(f"  - {m.rel_path}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # 无参数时进入交互菜单（简化版）
        console.print("[bold]调试入口[/bold] 可用命令:")
        console.print("  ingest <视频链接或文本> [--source-type video_url|raw_text|note_path]")
        console.print("  correlate <笔记相对路径>")
        console.print("  query <问题>")
        console.print("  index          # 索引 promoted 笔记")
        console.print("  status         # 查看配置与 Vault 状态")
    app()
