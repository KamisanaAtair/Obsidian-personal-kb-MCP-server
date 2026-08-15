"""图注册表：导出三个子图，供 langgraph dev / langgraph.json 引用。

需求第9节：core/ 与触发方式解耦，langgraph dev 将 core/graph.py 编译后的图
直接跑成本地 REST 服务；MCP Server 层只是其上的薄适配器。

三个图分别对应三个 MCP 工具入口：
- ingestion_graph   ← ingest_content
- correlation_graph  ← trigger_correlation
- retrieval_graph    ← query_kb
"""

from core.subgraphs.ingestion_graph import ingestion_graph
from core.subgraphs.correlation_graph import correlation_graph
from core.subgraphs.retrieval_graph import retrieval_graph

__all__ = ["ingestion_graph", "correlation_graph", "retrieval_graph"]
