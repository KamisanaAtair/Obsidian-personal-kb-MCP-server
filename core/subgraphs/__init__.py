"""三个独立子图：每个对应一个 MCP 工具入口。

需求第5节：每个工具各自对应独立的子图入口。
需求第11节决策：去除图内 Supervisor 路由节点——Host 选哪个 MCP 工具即完成路由，
图内二次判断是重复劳动。
"""

from core.subgraphs.ingestion_graph import build_ingestion_graph
from core.subgraphs.correlation_graph import build_correlation_graph
from core.subgraphs.retrieval_graph import build_retrieval_graph

__all__ = [
    "build_ingestion_graph",
    "build_correlation_graph",
    "build_retrieval_graph",
]
