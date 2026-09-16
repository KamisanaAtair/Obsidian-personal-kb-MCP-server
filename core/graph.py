"""图注册表：导出四个 Host-delegated 子图供 MCP / langgraph.json 引用。

- ingestion_prepare_graph  ← ingest_content_prepare
- ingestion_finalize_graph ← ingest_content_finalize
- correlation_graph        ← trigger_correlation
- retrieval_graph          ← query_kb

业务逻辑独立于触发方式，MCP Server 只负责薄适配。
"""

from core.subgraphs.ingestion_prepare_graph import ingestion_prepare_graph
from core.subgraphs.ingestion_finalize_graph import ingestion_finalize_graph
from core.subgraphs.correlation_graph import correlation_graph
from core.subgraphs.retrieval_graph import retrieval_graph

__all__ = [
    "ingestion_prepare_graph",
    "ingestion_finalize_graph",
    "correlation_graph",
    "retrieval_graph",
]
