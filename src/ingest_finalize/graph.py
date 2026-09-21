"""链2 摄取 finalize 的图 —— 对应 MCP 工具 ingest_content_finalize。

[调用链] ingest_finalize（tool -> node -> graph 的第 3 层）
  node: src/ingestion.py（ingestion_finalize_node）
  工具: src/ingest_finalize/tools/obsidian_skill.py、obsidian_cli.py
  公共: src/ingestion.py、src/vault_io.py、src/common/tools/session_store.py（取回 prepare 阶段的服务端权威来源）
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.ingestion import ingestion_finalize_node
from src.common.state import KBState


def build_ingestion_finalize_graph():
    """构建单节点摄取 finalize 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("ingestion_finalize", ingestion_finalize_node)
    graph.add_edge(START, "ingestion_finalize")
    graph.add_edge("ingestion_finalize", END)
    return graph.compile()


ingestion_finalize_graph = build_ingestion_finalize_graph()
