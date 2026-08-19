"""下载 BAAI/bge-m3 embedding 模型到本地缓存。

优先从魔搭社区（ModelScope）下载，国内网络友好。
首次下载约 2.2GB（含模型权重 + tokenizer + 配置）。

用法：
    python scripts/download_embed_model.py              # 从魔搭社区下载 bge-m3
    python scripts/download_embed_model.py --source huggingface  # 从 HuggingFace 下载

下载完成后，模型缓存在 models/bge-m3/ 目录，后续 get_embeddings() 直接加载无需联网。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()
app = typer.Typer(help="下载 BAAI/bge-m3 embedding 模型")


@app.command()
def main(
    source: str = typer.Option(
        "modelscope",
        "--source",
        "-s",
        help="下载源：modelscope（默认，国内推荐）| huggingface",
    ),
):
    """下载 bge-m3 模型到本地缓存目录。"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from config.settings import Settings

    settings = Settings(embed_model_source=source)
    console.print(Panel.fit(
        f"模型: {settings.embed_model_name}\n"
        f"来源: {source}\n"
        f"缓存: {settings.embed_cache_path}\n"
        f"设备: {settings.embed_device}",
        title="Embedding 模型下载",
        style="cyan",
    ))

    from core.tools.embeddings import ensure_model_downloaded

    try:
        path = ensure_model_downloaded(settings)
        console.print(f"\n[green bold]下载完成！[/green bold]")
        console.print(f"模型路径: {path}")
        console.print(f"\n[dim]后续 get_embeddings() 将直接从此路径加载，无需联网。[/dim]")
    except Exception as e:
        console.print(f"\n[red bold]下载失败：[/red bold] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
