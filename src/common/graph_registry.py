"""图注册表：导出四条链的编译后图，供 MCP / langgraph.json / scripts 引用。

[公共文件] 被以下链调用：四条链全部。
本文件是组合根——它是唯一从各链目录导入的公共文件；各链目录之间不允许互相导入。
改图变量名或链目录名时，必须同步 langgraph.json 与 mcp_server/server.py。

- ingestion_prepare_graph  ← ingest_content_prepare
- ingestion_finalize_graph ← ingest_content_finalize
- correlation_graph        ← trigger_correlation
- retrieval_graph          ← query_kb

业务逻辑独立于触发方式，MCP Server 只负责薄适配。
"""

from src.ingest_prepare.graph import ingestion_prepare_graph
from src.ingest_finalize.graph import ingestion_finalize_graph
from src.correlate.graph import correlation_graph
from src.query.graph import retrieval_graph

__all__ = [
    "ingestion_prepare_graph",
    "ingestion_finalize_graph",
    "correlation_graph",
    "retrieval_graph",
]
