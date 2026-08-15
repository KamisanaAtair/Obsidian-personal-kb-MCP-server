"""核心包：业务逻辑层，与触发方式（MCP / CLI / 测试）解耦。

导入路径设计：
- core.state.KBState          —— 状态 schema
- core.graph.*                —— 三个子图（langgraph dev 入口）
- core.subgraphs.*            —— 子图定义
- core.nodes.*                —— 节点实现
- core.tools.*                —— 内部工具（不对外暴露，MCP 层不直接调用）
"""
