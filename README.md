# Personal KB Multi-Agent

基于 LangGraph 的个人知识库多智能体系统，以 MCP Server 形式对外暴露三个业务流程级工具，核心安全机制是 frontmatter `status` 字段（`staged`/`promoted`）构成的**信任闸门**。

---

## 功能概览

| MCP 工具 | 功能 |
|---|---|
| `ingest_content` | 摄取外部内容（文本/视频链接）→ 生成 `staged` 草稿笔记 |
| `trigger_correlation` | 对 `promoted` 笔记做语义关联发现（只读） |
| `query_kb` | 基于 `promoted` 笔记的 RAG 检索问答 + 引用来源 |

---

## 核心设计：信任闸门

```
staged   ──[不可被检索]──►  Retrieval / Correlation 物理隔离
promoted ──[可被检索]──►   仅 promoted 笔记进入向量库召回
改 status ──[只能人工]──►  任何代码路径 / MCP 工具均不提供改 status 入口
```

- AI 生成的笔记强制标记为 `staged`，不可被检索
- 人工在 Obsidian 中审核后改为 `promoted`，方可进入知识库
- 代码层多处兜底，确保闸门不被绕过

---

## 技术栈

| 领域 | 选型 |
|---|---|
| 图编排 | LangGraph ≥ 0.2.50 + LangChain ≥ 0.3.0 |
| LLM | Ollama 本地（默认）/ OpenAI API |
| 向量库 | Chroma ≥ 0.5.0（metadata 过滤隔离 staged） |
| Embedding | BAAI/bge-m3（本地 sentence-transformers） |
| 混合检索 | Chroma 向量检索 + BM25 稀疏检索（RRF 融合） |
| MCP Server | mcp 1.x（FastMCP） |
| 视频转文本 | yt-dlp + faster-whisper（CC 字幕 → Whisper fallback） |
| 配置 | pydantic-settings + python-dotenv |
| Python | ≥ 3.11 |

---

## 快速开始

### 1. 安装

```bash
git clone https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server.git
cd Obsidian-personal-kb-MCP-server
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少配置 VAULT_ROOT 指向你的 Obsidian Vault 目录
```

### 3. 下载 Embedding 模型（首次使用）

```bash
python scripts/download_embed_model.py
```

### 4. 启动 MCP Server

```bash
python -m mcp_server.server
```

### 5. 调试（可选）

```bash
# 查看配置与 Vault 状态
python scripts/debug_run.py status

# 摄取内容
python scripts/debug_run.py ingest "https://www.bilibili.com/video/BVxxxxxx"

# 关联发现
python scripts/debug_run.py correlate "path/to/note.md"

# 检索问答
python scripts/debug_run.py query "什么是 RAG？"

# 全量重建索引
python scripts/debug_run.py index
```

---

## 项目结构

```
├── config/              # 配置层：全局设置 + prompt 模板
├── core/
│   ├── nodes/           # 图节点实现（ingestion / correlation / retrieval_qa）
│   ├── subgraphs/       # 子图定义（每个对应一个 MCP 工具）
│   ├── tools/           # 内部工具集（LLM工厂 / RAG检索器 / Vault读写 等）
│   ├── graph.py         # 图注册表
│   └── state.py         # KBState 状态定义
├── mcp_server/          # MCP Server 适配层（薄适配器，无业务逻辑）
├── scripts/             # 调试脚本
├── .env.example         # 环境变量示例
├── pyproject.toml       # 依赖与构建配置
└── langgraph.json       # LangGraph 图注册表
```

---

## 架构分层

```
config/           ← 所有模块引用
  ↑
core/tools/       ← 内部工具（LLM / 检索器 / Vault IO）
  ↑
core/nodes/       ← 图节点（业务逻辑）
  ↑
core/subgraphs/   ← 子图（流程编排）
  ↑
core/graph.py     ← 导出
  ├──→ mcp_server/   （MCP 适配，薄调用）
  └──→ scripts/      （调试入口）
```

**核心原则**：`core/` 与触发方式完全解耦，MCP Server 只做参数解析 → 调子图 → 格式化返回。

---

## 笔记生命周期

```
外部内容 ──► Ingestion Agent ──► staged 草稿（Inbox/）
                                      │
                                 人工审核（Obsidian）
                                      │
                                      ▼
                                 promoted 笔记
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                   Correlation Agent        Retrieval/QA Agent
                   （语义关联发现）          （RAG 检索问答）
```

---

## 优雅降级

每个外部依赖都有降级路径：

- **LLM 不可用** → 相似度直出 / 基础 frontmatter 包装
- **Obsidian CLI 不可用** → 文件系统 fallback
- **视频转写不可用** → stub 占位文本
- **Vault 路径解析失败** → `.env` fallback

---

## 许可证

[CC BY-NC-SA 4.0](LICENSE) — 免费使用、要求署名、禁止商用、相同方式共享。
