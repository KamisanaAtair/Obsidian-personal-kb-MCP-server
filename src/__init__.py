"""按调用链纵切的项目根包。

一级结构：
- src/ingest_prepare/   链1 摄取 prepare（MCP: ingest_content_prepare）
- src/ingest_finalize/  链2 摄取 finalize（MCP: ingest_content_finalize）
- src/correlate/        链3 关联发现（MCP: trigger_correlation）
- src/query/            链4 知识库问答（MCP: query_kb）
- src/common/           公共层：被多条链共用的文件（含 tools/ 子目录）
- src/*.py              顶层共享文件：被多条链共用的**单个文件**，不拆分，直接放根目录

链文件夹内部按 tool -> node -> graph 分层：
    <chain>/tools/     该链独占的工具
    <chain>/nodes/     该链独占的节点（没有独占节点时该目录不存在）
    <chain>/graph.py   该链的编译后图

顶层共享文件（被多条链调用且不做文件拆分）：
    src/ingestion.py   prepare 与 finalize 两个节点同源同文件（+ 共用辅助函数）
    src/vault_io.py    Vault 读侧多链共用，写侧只服务 ingest_finalize

摄取链的 prepare / finalize 被成本边界拆成两条链，故计为两个一级文件夹。
依赖方向约定：common/ 与顶层共享文件不得 import 链目录；唯一例外是
src/common/graph_registry.py（组合根，已在文件头声明）。
"""
