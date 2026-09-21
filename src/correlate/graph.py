"""链3 关联发现的图 —— 对应 MCP 工具 trigger_correlation。

[调用链] correlate（tool -> node -> graph 的第 3 层）
  node: src/correlate/nodes/correlation.py
  工具: 无链独占工具；全部来自 src/common/（retriever、hybrid_search、vault_io）

入口：单一 correlation_node，对 promoted 笔记返回候选与 Host 生成 prompt（只读）。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.correlate.nodes.correlation import correlation_node
from src.common.state import KBState


def build_correlation_graph():
    """构建 Correlation 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("correlation", correlation_node)
    graph.add_edge(START, "correlation")
    graph.add_edge("correlation", END)
    return graph.compile()


# 供 langgraph.json 引用（模块级编译实例）
correlation_graph = build_correlation_graph()
