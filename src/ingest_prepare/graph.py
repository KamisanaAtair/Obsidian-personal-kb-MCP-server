"""链1 摄取 prepare 的图 —— 对应 MCP 工具 ingest_content_prepare。

[调用链] ingest_prepare（tool -> node -> graph 的第 3 层）
  node: src/ingestion.py（ingestion_prepare_node）
  工具: src/ingest_prepare/tools/video_to_text.py
  公共: src/common/tools/session_store.py、src/vault_io.py、src/common/prompts.py
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.ingestion import ingestion_prepare_node
from src.common.state import KBState


def build_ingestion_prepare_graph():
    """构建单节点摄取 prepare 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("ingestion_prepare", ingestion_prepare_node)
    graph.add_edge(START, "ingestion_prepare")
    graph.add_edge("ingestion_prepare", END)
    return graph.compile()


ingestion_prepare_graph = build_ingestion_prepare_graph()
