"""MCP Server 适配层（薄适配器，无业务逻辑）。

需求第5节工具粒度边界：
- 只暴露对应一次完整业务流程的 3 个工具：ingest_content / trigger_correlation / query_kb
- 不暴露内部原子操作（改 status、直接写文件）
- 不暴露任何能修改 status 的工具——Promotion 永远只能人工完成

业务逻辑全在 core/，本层只做：参数解析 → 调子图 → 格式化返回。
"""
