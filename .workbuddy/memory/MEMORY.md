# 项目长期记忆 — personal-kb-multiagent

## 项目概述
个人知识库多智能体系统：LangGraph 多 agent + MCP Server，整合 Obsidian Vault、视频转文档 MCP、Obsidian 整理 skill，以 MCP Server 形式对外暴露给 Host（Claude Code/Codex/WorkBuddy）调用。需求文档：`D:/Obsidian/User Data Library/Computer Study/personal-kb-multiagent-requirements.md`（v0.2-draft）。

## 技术栈
LangGraph + LangChain + MCP + Chroma（本地向量库）+ Ollama（默认本地 LLM/embedding）/ API key 模型（占位符）。Python 3.13。

## 核心架构约定（必须遵守）
- **信任闸门**：status 字段（staged/promoted），staged 物理不可检索（metadata filter status=promoted），不靠阈值
- **工具粒度边界**：MCP 只暴露 3 个业务流程级工具（ingest_content/trigger_correlation/query_kb），不暴露内部原子操作（改 status、写文件）
- **Promotion 只能人工**：任何代码/MCP 都不能改 status，只能人工在 Obsidian 完成
- **无图内 Supervisor**：Host 选 MCP 工具即路由，图内不二次判断
- **core/ 与触发方式解耦**：MCP Server 是薄适配层，业务逻辑全在 core/
- **status 用 frontmatter 字段不用 tag**：状态互斥单值
- **字段单一写入归属**：每个 state 字段只由一个 agent 写，避免互相覆盖
- **向量索引两级刷新**：query_kb/trigger_correlation 入口自动调 `ensure_index_fresh` 按 mtime manifest 增量索引（manifest 记录 chunk_ids，按 ids 删旧再 add），promote 后无需手动跑 index；`index_vault()` 全量重建幂等（先 delete_collection 再重建）。manifest 在 `chroma_path/index_manifest.json`
- **Vault 路径动态解析（不硬编码）**：core/tools/vault_resolver.py 的 `resolve_vault_path()` 按 obsidian skill 规范解析（obsidian-cli print-default → obsidian.json open:true → None）。settings.vault_path 优先动态解析，fallback .env 的 VAULT_ROOT；vault_root 默认空串。测试用 vault_autodiscover=false 隔离
- **yakitrak CLI 依赖按命令区分**：create/move/open 走 obsidian:// URI 需 Obsidian 桌面端安装（与官方 obs 同依赖）；仅 print-default/search/list 不依赖 Obsidian 运行。无 Obsidian 桌面端时真正兜底只有文件系统

## 已接入能力（参考开源 skill 方法论独立实现，不依赖 Host skill）
1. 视频转文本：core/tools/video_to_text.py（yt-dlp CC 字幕 + whisper 三级 fallback）
2. Obsidian CLI 适配层：core/tools/obsidian_cli.py（官方 obs / yakitrak / 文件系统 三级 fallback）
3. 笔记格式化：core/tools/obsidian_skill.py（LLM 优先，占位符时基础包装 fallback）
4. Vault 路径动态解析：core/tools/vault_resolver.py（obsidian-cli print-default / obsidian.json open:true，去硬编码）

## 占位待接入
1. 真实 LLM key / Ollama 模型名 → .env（当前占位符，format_note 走基础包装 fallback）
2. 其他关键 MCP server / tools

## 多 Host 通用原则（重要）
- 系统目标是 Codex/Claude Code/WorkBuddy 等多 Host 通用
- core/tools/ 独立实现所有能力，不依赖任何 Host 自带的 skill
- 可参考开源 skill 的方法论，但不调用 skill 本身

## 目录结构关键路径
- config/settings.py：集中配置
- core/state.py：KBState schema
- core/graph.py：三子图注册表（langgraph dev 入口）
- core/nodes/、core/subgraphs/、core/tools/
- mcp_server/server.py：MCP 适配层
- scripts/debug_run.py：第一层调试入口
- tests/test_smoke.py：冒烟测试

## 运行环境
- 受管理 Python: C:\Users\ALive\.workbuddy\binaries\python\envs\default\Scripts\python.exe
- 依赖装在该 venv；pip install -e ".[dev]"
- `langchain-text-splitters` 是 retriever 运行依赖（MarkdownHeaderTextSplitter/RecursiveCharacterTextSplitter），已在 pyproject 声明并装 venv
