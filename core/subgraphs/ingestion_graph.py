"""Ingestion 子图 —— 对应 MCP 工具 ingest_content。

入口：单一 ingestion_node，输出 staged 草稿笔记。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from core.nodes.ingestion import ingestion_node
from core.state import KBState


def build_ingestion_graph():
    """构建 Ingestion 子图（已编译）。

    结构：START → ingestion_node → END
    （MVP 单节点即可；后续若 ingestion 内需多步，可在此扩展。）
    """
    graph = StateGraph(KBState)
    graph.add_node("ingestion", ingestion_node)
    graph.add_edge(START, "ingestion")
    graph.add_edge("ingestion", END)
    return graph.compile()


# 供 langgraph.json 引用（模块级编译实例）
ingestion_graph = build_ingestion_graph()
