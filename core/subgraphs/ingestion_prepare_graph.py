"""Ingestion prepare 子图 —— 对应 MCP 工具 ingest_content_prepare。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from core.nodes.ingestion import ingestion_prepare_node
from core.state import KBState


def build_ingestion_prepare_graph():
    """构建单节点摄取 prepare 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("ingestion_prepare", ingestion_prepare_node)
    graph.add_edge(START, "ingestion_prepare")
    graph.add_edge("ingestion_prepare", END)
    return graph.compile()


ingestion_prepare_graph = build_ingestion_prepare_graph()
