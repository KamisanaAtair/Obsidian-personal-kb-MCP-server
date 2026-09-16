"""Retrieval/QA 子图 —— 对应 MCP 工具 query_kb。

入口：单一 retrieval_qa_node，返回 promoted 笔记片段与 Host 回答 prompt。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from core.nodes.retrieval_qa import retrieval_qa_node
from core.state import KBState


def build_retrieval_graph():
    """构建 Retrieval/QA 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("retrieval_qa", retrieval_qa_node)
    graph.add_edge(START, "retrieval_qa")
    graph.add_edge("retrieval_qa", END)
    return graph.compile()


# 供 langgraph.json 引用（模块级编译实例）
retrieval_graph = build_retrieval_graph()
