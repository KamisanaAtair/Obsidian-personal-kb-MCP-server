# 项目结构与功能说明

> 基于 LangGraph 的个人知识库多智能体系统，以 MCP Server 形式对外暴露三个业务流程级工具。
> 核心架构决策：用 frontmatter 的 `status` 字段（`staged` / `promoted`）作为**唯一信任闸门**。

---

## 1. 项目目录

```
personal-kb-multiagent/
│
├── pyproject.toml                  # 项目元数据、依赖声明、CLI 入口、构建配置
├── langgraph.json                  # LangGraph 图注册表（供 langgraph dev 使用）
├── .gitignore                      # Git 忽略规则
├── .env                            # 环境变量配置（不提交，含 LLM key 占位符）
│
├── config/                         # ── 配置层 ──────────────────────────
│   ├── __init__.py                 #   包初始化，导出 Settings / get_settings
│   ├── settings.py                 #   全局配置：LLM 路由 / Vault / RAG / 视频转写 / Obsidian CLI
│   └── prompts.py                  #   三个 Agent 的 prompt 模板（Ingestion / Correlation / QA）
│
├── core/                           # ── 核心业务逻辑层（与触发方式解耦）──
│   ├── __init__.py                 #   包初始化，说明导入路径设计
│   ├── graph.py                    #   图注册表：导出三个子图供 langgraph dev / MCP 引用
│   ├── state.py                    #   KBState 状态 Schema（每字段唯一写者）
│   │
│   ├── nodes/                      #   ── 图节点实现 ──
│   │   ├── __init__.py             #     导出三个节点函数
│   │   ├── ingestion.py            #     Ingestion Agent：外部内容 → staged 草稿笔记
│   │   ├── correlation.py          #     Correlation Agent：对 promoted 笔记做语义关联发现
│   │   └── retrieval_qa.py         #     Retrieval/QA Agent：仅基于 promoted 笔记回答 + 引用
│   │
│   ├── subgraphs/                  #   ── 子图定义（每个对应一个 MCP 工具入口）──
│   │   ├── __init__.py             #     导出三个 build_*_graph 函数
│   │   ├── ingestion_graph.py      #     Ingestion 子图：START → ingestion_node → END
│   │   ├── correlation_graph.py    #     Correlation 子图：START → correlation_node → END
│   │   └── retrieval_graph.py      #     Retrieval 子图：START → retrieval_qa_node → END
│   │
│   └── tools/                      #   ── 内部工具集（MCP 不直接暴露）──
│       ├── __init__.py             #     工具边界说明
│       ├── llm.py                  #     LLM 工厂：按 Agent 角色返回 Ollama / API 模型实例
│       ├── retriever.py            #     RAG 检索器：Chroma 向量库 + metadata 物理隔离 staged
│       ├── vault_io.py             #     Vault 读写 + status 管理（信任闸门核心）
│       ├── vault_resolver.py       #     Vault 路径动态解析（obsidian-cli / obsidian.json）
│       ├── obsidian_skill.py       #     笔记格式化（LLM 优先，占位符时基础包装 fallback）
│       ├── obsidian_cli.py         #     Obsidian CLI 适配层（官方 obs / yakitrak / 文件系统）
│       └── video_to_text.py        #     视频转文本（yt-dlp CC 字幕 + Whisper 三级 fallback）
│
├── mcp_server/                     # ── MCP Server 适配层（薄适配器）──
│   ├── __init__.py                 #   工具粒度边界说明
│   └── server.py                   #   FastMCP Server：暴露 3 个业务流程级工具
│
├── scripts/                        # ── 调试脚本 ──
│   ├── __init__.py
│   └── debug_run.py                #   第一层调试入口：绕开 MCP/Host 直接调用 core 子图
│
└── tests/                          # ── 测试 ──
    ├── __init__.py
    └── test_smoke.py               #   冒烟测试：框架结构 / 信任闸门 / 索引幂等性 / 路径解析
```

---

## 2. 文件功能简述

### 2.1 配置层（config/）

| 文件 | 功能 |
|---|---|
| `settings.py` | 全局配置中心。LLM 路由（Ollama 本地 / API key 模型）、Vault 路径（动态解析 + fallback）、RAG 参数、视频转写开关、Obsidian CLI 开关。使用 pydantic-settings 从 `.env` 加载 |
| `prompts.py` | 三个 Agent 各自的 system / user prompt 模板。Ingestion 结构化笔记、Correlation 输出建议关联 JSON、QA 强制引用来源回答 |

### 2.2 核心层（core/）

| 文件 | 功能 |
|---|---|
| `graph.py` | 图注册表。导入并导出三个子图实例，供 `langgraph.json` 和 MCP Server 引用 |
| `state.py` | `KBState` TypedDict 定义。每字段唯一写者，`messages` 用 `add_messages` reducer。已移除 `intent` 字段（路由由 MCP Host 选工具完成） |

#### 节点实现（core/nodes/）

| 文件 | 功能 | 写入的 state 字段 |
|---|---|---|
| `ingestion.py` | 摄取节点。自动判别来源类型（视频/文本），视频走转写，调 `format_note` 格式化，落地为 `status=staged` 笔记到 `Inbox/` | `source_type`, `raw_content`, `processed_note`, `note_path` |
| `correlation.py` | 关联发现节点。仅对 `promoted` 笔记运行，语义检索候选旧笔记，LLM 判断关联性输出建议列表（只读），LLM 不可用时退化为相似度直出 | `related_notes` |
| `retrieval_qa.py` | 检索问答节点。增量刷新索引后检索 `promoted` 笔记片段，LLM 基于片段回答并强制引用来源，LLM 不可用时直出片段 | `retrieved_chunks`, `answer` |

#### 子图定义（core/subgraphs/）

| 文件 | 结构 | 对应 MCP 工具 |
|---|---|---|
| `ingestion_graph.py` | `START → ingestion_node → END` | `ingest_content` |
| `correlation_graph.py` | `START → correlation_node → END` | `trigger_correlation` |
| `retrieval_graph.py` | `START → retrieval_qa_node → END` | `query_kb` |

#### 内部工具（core/tools/）

| 文件 | 功能 |
|---|---|
| `llm.py` | LLM 工厂。按角色（ingest/correlation/qa）返回对应 LLM 实例，支持 Ollama 本地和 API key 两种 provider。同时提供 `get_embeddings` |
| `retriever.py` | RAG 检索器。两级索引策略：`index_vault()` 全量幂等重建，`ensure_index_fresh()` 基于 mtime manifest 增量更新。检索时 metadata filter `status=promoted` 物理隔离 staged |
| `vault_io.py` | Vault 读写核心。`create_staged_note` 强制写 staged（信任闸门），`read_note` 读取笔记元信息，`list_promoted_notes` / `list_staged_notes` 按 status 筛选。**不提供改 status 的对外入口** |
| `vault_resolver.py` | Vault 路径动态解析。顺序：`obsidian-cli print-default` → `obsidian.json`（open:true）→ None（fallback .env）。不硬编码路径 |
| `obsidian_skill.py` | 笔记格式化。LLM 优先做内容结构化，占位符时 fallback 基础 frontmatter 包装。`_force_status_staged` 信任闸门兜底 |
| `obsidian_cli.py` | Obsidian CLI 三级适配。探测顺序：官方 `obs` → yakitrak `obsidian-cli` → 文件系统 fallback。`property_set` 显式拒绝设置 status 字段 |
| `video_to_text.py` | 视频转文本。三级 fallback：CC 字幕（yt-dlp）→ Whisper 转写（faster-whisper / openai-whisper）→ 失败。`ENABLED=false` 时走 stub 占位 |

### 2.3 MCP Server 层（mcp_server/）

| 文件 | 功能 |
|---|---|
| `server.py` | FastMCP Server，暴露 3 个工具：`ingest_content`、`trigger_correlation`、`query_kb`。不含业务逻辑，只做参数解析 → 调子图 → 格式化返回。**不暴露任何能改 status 的工具** |

### 2.4 调试与测试

| 文件 | 功能 |
|---|---|
| `scripts/debug_run.py` | 第一层调试入口（typer CLI）。`ingest` / `correlate` / `query` / `index` / `status` 五个子命令，绕开 MCP/Host 直接驱动 core 子图 |
| `tests/test_smoke.py` | 冒烟测试。覆盖：KBState 字段完整性、子图可编译、信任闸门强制 staged、MCP 工具集安全边界、索引幂等性、增量刷新、Vault 路径动态解析 |

---

## 3. 项目整体流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        MCP Host（Codex / Claude Code / WorkBuddy …）     │
│                          用户发起请求，选择对应 MCP 工具                    │
└────────────┬──────────────────┬──────────────────┬──────────────────────┘
             │                  │                  │
     ┌───────▼───────┐ ┌───────▼────────┐ ┌───────▼───────┐
     │ ingest_content │ │trigger_correlation│ │  query_kb   │
     │  （MCP 工具）   │ │  （MCP 工具）    │ │ （MCP 工具）  │
     └───────┬───────┘ └───────┬────────┘ └───────┬───────┘
             │                  │                  │
             ▼                  ▼                  ▼
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│  Ingestion 子图  │ │ Correlation 子图  │ │ Retrieval 子图   │
│  (core/subgraphs)│ │ (core/subgraphs) │ │ (core/subgraphs) │
└────────┬────────┘ └────────┬─────────┘ └────────┬────────┘
         │                   │                    │
         ▼                   ▼                    ▼
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│ ingestion_node   │ │ correlation_node │ │ retrieval_qa_node│
│ (core/nodes/)    │ │ (core/nodes/)    │ │ (core/nodes/)    │
└────────┬────────┘ └────────┬─────────┘ └────────┬────────┘
         │                   │                    │
         ▼                   ▼                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    core/tools/（内部工具集）                           │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │  llm.py  │ │retriever │ │ vault_io │ │obsidian_ │ │ video_to │  │
│  │ LLM 工厂 │ │ RAG 检索 │ │ Vault读写│ │ skill.py │ │ _text.py │  │
│  └──────────┘ └──────────┘ └──────────┘ │obsidian_ │ └──────────┘  │
│                                          │ cli.py   │               │
│                                          │vault_    │               │
│                                          │resolver  │               │
│                                          └──────────┘               │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  config/settings.py（全局配置）  config/prompts.py（prompt）  │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
         │                   │                    │
         ▼                   ▼                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Obsidian Vault（文件系统）                     │
│                                                                      │
│   ┌────────────────────┐        ┌──────────────────────────────┐     │
│   │  Inbox/             │        │  其他目录                      │     │
│   │  ├─ note_1.md       │        │  ├─ RAG基础.md                │     │
│   │  │  status: staged  │        │  │  status: promoted          │     │
│   │  └─ note_2.md       │        │  └─ ...                       │     │
│   │     status: staged  │        │                               │     │
│   └────────────────────┘        └──────────────────────────────┘     │
│                                                                      │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │  .chroma_db/（Chroma 向量库 + index_manifest.json）           │   │
│   └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

信任闸门（核心安全边界）：
═══════════════════════════
  staged  ──[不可被检索]──►  Retrieval / Correlation 物理隔离
  promoted ──[可被检索]──►  仅 promoted 笔记进入向量库召回
  改 status ──[只能人工]──►  任何代码路径 / MCP 工具均不提供改 status 入口
```

---

## 4. 各功能模块流程图

### 4.1 Ingestion 模块（摄取）

```
用户 / MCP Host
      │
      │  ingest_content(source, source_type?)
      ▼
┌─────────────────────────────────────────────────────────┐
│  Ingestion 子图                                         │
│                                                         │
│  START ──► ingestion_node ──► END                       │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  ingestion_node                                  │   │
│  │                                                  │   │
│  │  1. 判别来源类型                                  │   │
│  │     ┌─────────┐    ┌─────────┐    ┌──────────┐  │   │
│  │     │video_url│    │raw_text │    │note_path │  │   │
│  │     └────┬────┘    └────┬────┘    └────┬─────┘  │   │
│  │          │              │              │         │   │
│  │          ▼              │              ▼         │   │
│  │  ┌──────────────┐      │        ┌──────────┐    │   │
│  │  │video_to_text │      │        │vault_io  │    │   │
│  │  │ CC字幕/Whisper│     │        │read_note │    │   │
│  │  └──────┬───────┘      │        └────┬─────┘    │   │
│  │         │              │             │          │   │
│  │         ▼              ▼             ▼          │   │
│  │  2. format_note(raw_content)                   │   │
│  │     ┌─────────────────────────────────────┐    │   │
│  │     │ obsidian_skill.py                   │    │   │
│  │     │ LLM 可用？──是──► LLM 结构化        │    │   │
│  │     │    │否                               │    │   │
│  │     │    └──► 基础 frontmatter 包装        │    │   │
│  │     │         │                           │    │   │
│  │     │    _force_status_staged() ◄── 信任闸门│    │   │
│  │     └─────────────────┬───────────────────┘    │   │
│  │                       │                        │   │
│  │                       ▼                        │   │
│  │  3. create_staged_note(processed)              │   │
│  │     ┌─────────────────────────────────────┐    │   │
│  │     │ vault_io.py                         │    │   │
│  │     │ 强制 status=staged ◄── 信任闸门      │    │   │
│  │     │ Obsidian CLI 可用？──是──► CLI 创建  │    │   │
│  │     │    │否                               │    │   │
│  │     │    └──► 文件系统写入 Inbox/           │    │   │
│  │     └─────────────────────────────────────┘    │   │
│  │                       │                        │   │
│  │                       ▼                        │   │
│  │  写入 state: {source_type, raw_content,        │   │
│  │               processed_note, note_path}       │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
      │
      ▼
  返回：staged 笔记路径 + 状态说明
  下一步：人工在 Obsidian 中审核，改 status → promoted
```

### 4.2 Correlation 模块（关联发现）

```
用户 / MCP Host
      │
      │  trigger_correlation(note_path)
      ▼
┌─────────────────────────────────────────────────────────┐
│  Correlation 子图                                       │
│                                                         │
│  START ──► correlation_node ──► END                     │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  correlation_node                                │   │
│  │                                                  │   │
│  │  1. 读取目标笔记 (vault_io.read_note)             │   │
│  │     │                                            │   │
│  │     ├─ 不存在 ──► 返回空关联 + 错误消息            │   │
│  │     │                                            │   │
│  │  2. 信任闸门检查                                   │   │
│  │     status != promoted? ──是──► 跳过，返回空       │   │
│  │     │否                                           │   │
│  │     ▼                                            │   │
│  │  3. 增量刷新索引 (retriever.ensure_index_fresh)    │   │
│  │     基于 mtime manifest，仅更新变更笔记             │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  4. 语义检索候选旧笔记                              │   │
│  │     retriever.retrieve(query, top_k)              │   │
│  │     metadata filter: status=promoted ◄── 物理隔离  │   │
│  │     剔除自身                                       │   │
│  │     │                                            │   │
│  │     ├─ 无候选 ──► 返回空关联                       │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  5. LLM 判断关联性                                │   │
│  │     LLM 可用？──是──► prompt + candidates JSON     │   │
│  │     │否                                           │   │
│  │     └──► 退化为相似度直出（带占位理由）              │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  写入 state: {related_notes: [{path, reason,     │   │
│  │                                  score}]}        │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
      │
      ▼
  返回：建议关联列表（只读，不自动改文件）
  提示：如需建立双链，请在 Obsidian 中手动添加 [[双向链接]]
```

### 4.3 Retrieval/QA 模块（检索问答）

```
用户 / MCP Host
      │
      │  query_kb(question)
      ▼
┌─────────────────────────────────────────────────────────┐
│  Retrieval 子图                                         │
│                                                         │
│  START ──► retrieval_qa_node ──► END                    │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  retrieval_qa_node                               │   │
│  │                                                  │   │
│  │  1. 增量刷新索引 (retriever.ensure_index_fresh)    │   │
│  │     基于 mtime manifest，保证刚 promote 的笔记     │   │
│  │     无需手动跑 index 即可被检索到                   │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  2. 检索 promoted 笔记片段                         │   │
│  │     retriever.retrieve(question, top_k)           │   │
│  │     metadata filter: status=promoted ◄── 物理隔离  │   │
│  │     │                                            │   │
│  │     ├─ 无命中 ──► "信息不足：知识库中暂无…"         │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  3. 信任闸门兜底                                   │   │
│  │     万一混入 staged 片段 ──► 强制丢弃（不应发生）    │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  4. 拼 context block（带编号，便于引用）             │   │
│  │     [1] 笔记: path (相似度 0.85) content...       │   │
│  │     [2] 笔记: path (相似度 0.72) content...       │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  5. LLM 回答（基于片段，强制引用）                   │   │
│  │     LLM 可用？──是──► prompt + context_block       │   │
│  │     │否                                           │   │
│  │     └──► 直出片段（降级模式）                       │   │
│  │     │                                            │   │
│  │     ▼                                            │   │
│  │  写入 state: {retrieved_chunks, answer}           │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
      │
      ▼
  返回：答案 + 引用来源清单
```

### 4.4 RAG 检索器模块（retriever.py）

```
┌─────────────────────────────────────────────────────────────────┐
│                    RAG 检索器（retriever.py）                     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  全量索引：index_vault()                                  │  │
│  │                                                           │  │
│  │  触发时机：manifest 缺失 / debug_run.py index 手动触发     │  │
│  │                                                           │  │
│  │  Vault ──► list_promoted_notes() ──► 逐篇切分            │  │
│  │           (仅 status=promoted)       MarkdownHeaderText   │  │
│  │                                      + RecursiveCharacter │  │
│  │                                       │                   │  │
│  │                                       ▼                   │  │
│  │                          delete_collection() ◄── 幂等保证  │  │
│  │                          重新构造 Chroma 实例              │  │
│  │                          add_texts(metadata: promoted)     │  │
│  │                                       │                   │  │
│  │                                       ▼                   │  │
│  │                          写入 index_manifest.json          │  │
│  │                          {path: {mtime, chunk_ids}}        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  增量索引：ensure_index_fresh()                            │  │
│  │                                                           │  │
│  │  触发时机：query_kb / trigger_correlation 入口自动调用      │  │
│  │                                                           │  │
│  │  加载 manifest ◄── index_manifest.json                    │  │
│  │       │                                                   │  │
│  │       ├─ 不存在/损坏 ──► 全量重建 (index_vault)            │  │
│  │       │                                                   │  │
│  │       ▼                                                   │  │
│  │  比对 Vault 当前 mtime vs manifest 记录                    │  │
│  │       │                                                   │  │
│  │       ├─ 新增笔记 ──► _index_one_note() → add_texts       │  │
│  │       ├─ 修改笔记 ──► delete(ids) → _index_one_note()     │  │
│  │       ├─ 删除笔记 ──► delete(ids)                         │  │
│  │       └─ 无变化   ──► 跳过                                │  │
│  │       │                                                   │  │
│  │       ▼                                                   │  │
│  │  更新 manifest                                            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  检索：retrieve()                                         │  │
│  │                                                           │  │
│  │  query ──► Chroma.similarity_search_with_score            │  │
│  │            filter: {status: "promoted"}  ◄── 信任闸门      │  │
│  │            top_k: config.rag_top_k                        │  │
│  │                   │                                       │  │
│  │                   ▼                                       │  │
│  │            [{content, path, score, header_path}]           │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.5 视频转文本模块（video_to_text.py）

```
视频链接（Bilibili / YouTube / …）
      │
      ▼
  ENABLED=true?
      │
      ├─ 否 ──► _stub_transcript() ──► 返回占位文本
      │
      ▼ 是
  _transcribe_real()
      │
      ├─ 1. _check_yt_dlp() ── yt-dlp 不在 PATH? ──► 抛异常
      │
      ├─ 2. _try_cc_subtitles()
      │     yt-dlp --write-subs --sub-langs zh-Hans,zh-CN,zh,...
      │     │
      │     ├─ 命中 CC 字幕 ──► _srt_to_text() ──► 返回文本
      │     │
      │     ▼ 无 CC 字幕
      ├─ 3. _try_whisper_transcription()
      │     │
      │     ├─ ffmpeg 不在 PATH? ──► 返回 None
      │     │
      │     ▼
      │     yt-dlp -x --audio-format wav（提取音频）
      │     │
      │     ▼
      │     Whisper 转写（线程池，避免阻塞事件循环）
      │     ┌──────────────────────────────┐
      │     │ whisper_backend?             │
      │     │  ├─ faster-whisper（默认轻量）│
      │     │  └─ openai-whisper（精度高）  │
      │     └──────────────┬───────────────┘
      │                    │
      │     ──► SRT → _srt_to_text() ──► 返回文本
      │
      ▼ 全部失败
  抛 RuntimeError
```

### 4.6 Vault 路径解析模块（vault_resolver.py）

```
Settings.vault_path（属性访问）
      │
      ▼
  vault_autodiscover=true?
      │
      ├─ 否 ──► 直接用 vault_root（.env 配置）
      │
      ▼ 是
  resolve_vault_path()
      │
      ├─ 1. _resolve_via_cli()
      │     obsidian-cli print-default --path-only
      │     │
      │     ├─ 成功 ──► 返回 Path
      │     │
      │     ▼ 失败 / CLI 不存在
      ├─ 2. _resolve_via_obsidian_json()
      │     读 obsidian.json（跨平台定位）
      │     取 "open": true 的 vault
      │     │
      │     ├─ 成功 ──► 返回 Path
      │     │
      │     ▼ 无 open 标记
      │     取首个存在的 vault 路径
      │     │
      │     ├─ 成功 ──► 返回 Path
      │     │
      │     ▼ 不存在
      ├─ 3. 返回 None ──► fallback 到 vault_root
```

### 4.7 信任闸门机制（贯穿全链路）

```
                    信任闸门安全边界总览
═══════════════════════════════════════════════════════

  笔记生命周期：
  ┌──────────┐    ┌──────────┐    ┌──────────────┐
  │  手动编辑  │    │  文本导入  │    │  AI 生成/视频  │
  │ (Obsidian)│    │          │    │              │
  └─────┬────┘    └─────┬────┘    └──────┬───────┘
        │               │                │
        ▼               ▼                ▼
   status=         status=          status=
   promoted        staged           staged
   (天然可信)      (待审核)         (待审核)
        │               │                │
        │          ┌────┴────┐           │
        │          │ 人工审核  │           │
        │          │ (Obsidian)│          │
        │          │ 改 status │           │
        │          │ → promoted│          │
        │          └────┬────┘           │
        │               │                │
        ▼               ▼                ▼
  ┌─────────────────────────────────────────┐
  │     向量库索引（仅 promoted 入库）        │
  │     metadata: {status: promoted}         │
  └─────────────────┬───────────────────────┘
                    │
                    ▼
  ┌─────────────────────────────────────────┐
  │     检索（metadata filter 物理隔离）      │
  │     filter: {status: "promoted"}         │
  │     staged 笔记即使被误索引也不会被召回    │
  └─────────────────────────────────────────┘

  代码层保障：
  ┌────────────────────────────────────────────────────┐
  │  vault_io.create_staged_note()   → 强制写 staged    │
  │  obsidian_skill._force_status_staged() → 强制改回   │
  │  obsidian_cli.property_set()     → 拒绝设置 status  │
  │  mcp_server                     → 不暴露 promote 工具│
  │  retriever.retrieve()           → metadata 硬过滤   │
  └────────────────────────────────────────────────────┘
```

### 4.8 调试入口模块（debug_run.py）

```
python scripts/debug_run.py <command>
      │
      ├─ ingest <source> ──► ingestion_graph.ainvoke()
      │                       直接驱动 Ingestion 子图
      │
      ├─ correlate <path> ──► correlation_graph.ainvoke()
      │                       直接驱动 Correlation 子图
      │
      ├─ query <question> ──► retrieval_graph.ainvoke()
      │                       直接驱动 Retrieval 子图
      │
      ├─ index ──► retriever.index_vault()
      │            全量重建向量索引
      │
      └─ status ──► get_settings() + list_promoted/staged_notes()
                    查看配置与 Vault 状态

设计目的：绕开 MCP/Host，直接验证 core 业务逻辑
```

---

## 5. 模块间依赖关系

```
config/
  ↑ 被所有模块引用
  │
core/tools/
  ↑ 被 core/nodes/ 引用
  │
core/nodes/
  ↑ 被 core/subgraphs/ 引用
  │
core/subgraphs/
  ↑ 被 core/graph.py 导出
  │
  ├──► mcp_server/server.py（MCP 适配层，薄调用）
  └──► scripts/debug_run.py（调试入口，直接驱动）
```

**关键设计原则**：
- `core/` 与触发方式（MCP / CLI / 测试）完全解耦
- MCP Server 层不含业务逻辑，只做参数解析 → 调子图 → 格式化返回
- 内部工具（`core/tools/`）不对外暴露，MCP 层不直接调用
- 信任闸门贯穿全链路，任何代码路径都不能改 status
