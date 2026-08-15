# personal-kb-multiagent — Agent Context Prompt

> 本文件面向 LLM Agent，帮助其快速理解项目全貌并准确参与开发。

---

## 项目一句话

基于 LangGraph 的个人知识库多智能体系统，以 MCP Server 形式对外暴露 3 个业务流程级工具（摄取 / 关联发现 / 检索问答），核心安全机制是 frontmatter `status` 字段（`staged`/`promoted`）构成的**信任闸门**。

---

## 技术栈

| 领域 | 选型 |
|---|---|
| 图编排 | LangGraph ≥ 0.2.50 + LangChain ≥ 0.3.0 |
| LLM | Ollama 本地（默认）/ OpenAI API（占位） |
| 向量库 | Chroma ≥ 0.5.0 + langchain-chroma |
| 文本切分 | MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter |
| MCP Server | mcp 1.x（FastMCP） |
| 视频转文本 | yt-dlp + faster-whisper（三级 fallback） |
| 配置 | pydantic-settings + python-dotenv |
| CLI 调试 | typer + rich |
| Python | ≥ 3.11 |

---

## 目录结构

```
personal-kb-multiagent/
├── pyproject.toml                  # 依赖、入口点、构建配置
├── langgraph.json                  # LangGraph 图注册表（langgraph dev 用）
├── .env / .env.example             # 环境变量（LLM key、Vault 路径等）
│
├── config/                         # ── 配置层 ──
│   ├── settings.py                 #   全局配置：LLM 路由 / Vault / RAG / 视频 / Obsidian CLI
│   └── prompts.py                  #   三个 Agent 的 system/user prompt 模板
│
├── core/                           # ── 核心业务层（与触发方式解耦）──
│   ├── graph.py                    #   图注册表：导出 3 个子图
│   ├── state.py                    #   KBState TypedDict（每字段唯一写者）
│   │
│   ├── nodes/                      #   图节点实现
│   │   ├── ingestion.py            #     摄取：外部内容 → staged 草稿
│   │   ├── correlation.py          #     关联发现：promoted 笔记语义关联
│   │   └── retrieval_qa.py         #     检索问答：promoted 笔记 RAG 回答
│   │
│   ├── subgraphs/                  #   子图（每个对应一个 MCP 工具）
│   │   ├── ingestion_graph.py      #     START → ingestion_node → END
│   │   ├── correlation_graph.py    #     START → correlation_node → END
│   │   └── retrieval_graph.py      #     START → retrieval_qa_node → END
│   │
│   └── tools/                      #   内部工具集（MCP 不直接暴露）
│       ├── llm.py                  #     LLM 工厂：按角色返回 Ollama/API 实例 + embeddings
│       ├── retriever.py            #     RAG 检索器：全量/增量索引 + metadata 过滤
│       ├── vault_io.py             #     Vault 读写 + status 管理（信任闸门核心）
│       ├── vault_resolver.py       #     Vault 路径动态解析（CLI → obsidian.json → fallback）
│       ├── obsidian_skill.py       #     笔记格式化（LLM 优先，fallback 基础包装）
│       ├── obsidian_cli.py         #     Obsidian CLI 三级适配（obs → yakitrak → 文件系统）
│       └── video_to_text.py        #     视频转文本（CC字幕 → Whisper → 失败）
│
├── mcp_server/                     # ── MCP 适配层（薄适配器，无业务逻辑）──
│   └── server.py                   #   FastMCP：3 个工具入口
│
├── scripts/                        # ── 调试 ──
│   └── debug_run.py                #   typer CLI：ingest/correlate/query/index/status
│
├── tests/
│   └── test_smoke.py               #   冒烟测试
│
└── learning/01_retrieval_chain/     # ── 学习模块（简化版检索链）──
```

---

## 核心架构决策

### 1. 信任闸门（最重要）

`status` 字段是**唯一安全边界**：

- `staged`：AI 生成的草稿，**不可被检索/关联**
- `promoted`：人工审核后的可信笔记，**唯一可被检索/关联的状态**
- **任何代码路径和 MCP 工具都不能改 status**，只能人工在 Obsidian 中修改

保障机制：
- `vault_io.create_staged_note()` 强制写 staged
- `obsidian_skill._force_status_staged()` 兜底
- `obsidian_cli.property_set()` 拒绝设置 status
- `retriever.retrieve()` metadata 硬过滤 `status=promoted`
- MCP Server 不暴露 promote 工具

### 2. 状态归属（KBState）

每个字段只由一个 Agent 写入，避免冲突：

| 字段 | 写入者 |
|---|---|
| `source_type`, `raw_content`, `processed_note`, `note_path` | Ingestion Agent |
| `related_notes` | Correlation Agent |
| `retrieved_chunks`, `answer` | Retrieval/QA Agent |
| `messages` | 各节点追加（add_messages reducer） |

### 3. 分层解耦

```
config/          ← 所有模块引用
  ↑
core/tools/      ← 内部工具
  ↑
core/nodes/      ← 图节点
  ↑
core/subgraphs/  ← 子图
  ↑
core/graph.py    ← 导出
  ├──→ mcp_server/  （薄适配）
  └──→ scripts/     （调试入口）
```

核心原则：`core/` 与触发方式完全解耦。MCP Server 只做参数解析 → 调子图 → 格式化返回。

### 4. RAG 索引策略

- **全量索引** `index_vault()`：幂等重建，delete + re-add
- **增量索引** `ensure_index_fresh()`：基于 mtime manifest，query/correlate 入口自动调用
- **检索隔离**：metadata filter `{status: "promoted"}`，staged 笔记物理隔离

### 5. 优雅降级

每个外部依赖都有降级路径：
- LLM 不可用 → 相似度直出 / 基础 frontmatter 包装
- Obsidian CLI 不可用 → 文件系统 fallback
- 视频转写不可用 → stub 占位文本
- Vault 路径解析失败 → .env fallback

---

## MCP 工具清单

| 工具 | 参数 | 功能 | 对应子图 |
|---|---|---|---|
| `ingest_content` | `source`, `source_type?` | 摄取内容为 staged 笔记 | ingestion_graph |
| `trigger_correlation` | `note_path` | 对 promoted 笔记做语义关联发现（只读） | correlation_graph |
| `query_kb` | `question` | 基于 promoted 笔记 RAG 回答 + 引用来源 | retrieval_graph |

---

## 调试命令

```bash
# 安装（开发模式）
pip install -e ".[dev]"

# 调试入口
python scripts/debug_run.py ingest <source>      # 摄取
python scripts/debug_run.py correlate <path>      # 关联发现
python scripts/debug_run.py query <question>      # 检索问答
python scripts/debug_run.py index                 # 全量重建索引
python scripts/debug_run.py status                # 查看配置与 Vault 状态

# LangGraph dev（本地 REST 服务）
langgraph dev

# MCP Server
python -m mcp_server.server

# 测试
pytest
```

---

## 关键文件速查

| 需要了解… | 看这个文件 |
|---|---|
| 全局配置项 | `config/settings.py` |
| Agent prompt 设计 | `config/prompts.py` |
| 状态结构与设计原则 | `core/state.py` |
| 摄取逻辑 | `core/nodes/ingestion.py` |
| 关联发现逻辑 | `core/nodes/correlation.py` |
| 检索问答逻辑 | `core/nodes/retrieval_qa.py` |
| RAG 索引与检索 | `core/tools/retriever.py` |
| Vault 读写与闸门 | `core/tools/vault_io.py` |
| MCP 工具定义 | `mcp_server/server.py` |
| 调试入口 | `scripts/debug_run.py` |

---

## 面向 LLM 的操作指南

### 修改检索行为
改 `core/tools/retriever.py`（索引策略、检索逻辑）和 `config/settings.py`（`rag_top_k` 等参数）。

### 修改 Agent 行为
改 `config/prompts.py`（prompt 模板）和 `core/nodes/*.py`（节点逻辑）。

### 添加新 MCP 工具
1. 在 `core/nodes/` 添加节点实现
2. 在 `core/subgraphs/` 添加子图
3. 在 `core/graph.py` 导出
4. 在 `mcp_server/server.py` 注册工具

### 修改信任闸门
**不建议**。闸门是核心安全边界，涉及 `vault_io.py`、`obsidian_skill.py`、`obsidian_cli.py`、`retriever.py`、`mcp_server/server.py` 多处联动。

### 添加新配置项
在 `config/settings.py` 的 `Settings` 类中添加字段，在 `.env` 中设置对应环境变量。
