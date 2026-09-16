"""Ingestion finalize 子图 —— 对应 MCP 工具 ingest_content_finalize。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from core.nodes.ingestion import ingestion_finalize_node
from core.state import KBState


def build_ingestion_finalize_graph():
    """构建单节点摄取 finalize 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("ingestion_finalize", ingestion_finalize_node)
    graph.add_edge(START, "ingestion_finalize")
    graph.add_edge("ingestion_finalize", END)
    return graph.compile()


ingestion_finalize_graph = build_ingestion_finalize_graph()
