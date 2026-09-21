"""MCP Server 适配层（薄适配器，无业务逻辑）。

需求第5节工具粒度边界：
- 只暴露对应一条调用链的 4 个工具：
  ingest_content_prepare / ingest_content_finalize / trigger_correlation / query_kb
- 不暴露内部原子操作（改 status、直接写文件）
- 不暴露任何能修改 status 的工具——Promotion 永远只能人工完成

业务逻辑全在 src/ 下的四个链目录（ingest_prepare / ingest_finalize / correlate / query）
与 src/common/，本层只做：参数解析 → 调该链的图 → 格式化返回。
"""
