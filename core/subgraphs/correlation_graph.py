"""Correlation 子图 —— 对应 MCP 工具 trigger_correlation。

入口：单一 correlation_node，对刚 promoted 的笔记输出建议关联（只读）。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from core.nodes.correlation import correlation_node
from core.state import KBState


def build_correlation_graph():
    """构建 Correlation 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("correlation", correlation_node)
    graph.add_edge(START, "correlation")
    graph.add_edge("correlation", END)
    return graph.compile()


# 供 langgraph.json 引用（模块级编译实例）
correlation_graph = build_correlation_graph()
