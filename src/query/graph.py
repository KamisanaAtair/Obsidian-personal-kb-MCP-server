"""链4 知识库问答的图 —— 对应 MCP 工具 query_kb。

[调用链] query（tool -> node -> graph 的第 3 层）
  node: src/query/nodes/retrieval_qa.py
  工具: 无链独占工具；全部来自 src/common/（retriever、hybrid_search）

入口：单一 retrieval_qa_node，返回 promoted 笔记片段与 Host 回答 prompt。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.query.nodes.retrieval_qa import retrieval_qa_node
from src.common.state import KBState


def build_retrieval_graph():
    """构建 Retrieval/QA 子图（已编译）。"""
    graph = StateGraph(KBState)
    graph.add_node("retrieval_qa", retrieval_qa_node)
    graph.add_edge(START, "retrieval_qa")
    graph.add_edge("retrieval_qa", END)
    return graph.compile()


# 供 langgraph.json 引用（模块级编译实例）
retrieval_graph = build_retrieval_graph()
