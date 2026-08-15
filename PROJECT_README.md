# personal-kb-multiagent

个人知识库多智能体系统：把本地 Obsidian 笔记库、视频转文档 MCP、Obsidian 整理 skill 整合为可检索问答的个人知识库，以 **MCP Server** 形式对外暴露，供日常使用的支持 MCP 的 AI 客户端（Claude Code / Codex / WorkBuddy 等）在对话中顺手调用。

> 需求文档：`personal-kb-multiagent-requirements.md`（v0.2-draft）

## 核心架构

```
MCP Host（Claude Code / Codex / WorkBuddy）
        │  自然语言意图 → 选工具
        ▼
┌─────────────────────────────────────────────┐
│  MCP Server（薄适配层，无业务逻辑）          │
│  ingest_content / trigger_correlation /     │
│  query_kb                                    │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│  core/（业务逻辑层，与触发方式解耦）          │
│  ┌─ Ingestion Agent   → staged 草稿笔记      │
│  └─ Correlation Agent → 建议关联（只读）      │
│  └─ Retrieval/QA Agent→ 仅检索 promoted 笔记  │
└─────────────────────────────────────────────┘
        │ 人工 Promotion（图外，唯一信任闸门）
        ▼
   Obsidian Vault（单一库 + status 字段）
```

**信任闸门**：未经人工确认的 `staged` 笔记**物理上不可被检索**——不靠调节 AI 阈值，靠架构保证。Promotion（改 status）只能人工在 Obsidian 中完成，任何 MCP 工具都不具备此权限。

## 三个 Agent / 三个 MCP 工具

| Agent | MCP 工具 | 输入 | 输出 | 可写笔记 |
|---|---|---|---|---|
| Ingestion | `ingest_content(source)` | 视频链接/文本 | `staged` 草稿 | 仅创建 |
| Correlation | `trigger_correlation(note_id)` | 已 promoted 笔记 | 建议关联列表 | 否（只读） |
| Retrieval/QA | `query_kb(question)` | 提问 | 答案 + 引用来源 | 否 |

工具粒度原则：只暴露对应一次完整业务流程的工具，不暴露内部原子操作（改 status、直接写文件），避免 Host 绕过编排顺序与信任闸门。

## 目录结构

```
.
├── config/          # 配置层（settings 集中管理 + prompt 模板）
│   ├── settings.py
│   └── prompts.py
├── core/            # 业务逻辑层（与触发方式解耦）
│   ├── state.py      # KBState schema
│   ├── graph.py      # 子图注册表（langgraph dev 入口）
│   ├── nodes/        # 三个 agent 节点
│   ├── subgraphs/   # 三个独立子图（对应三个 MCP 工具入口）
│   └── tools/        # 内部工具（不对外暴露）
│       ├── llm.py            # LLM 工厂（Ollama / API 占位符）
│       ├── video_to_text.py  # 视频转文档 MCP 占位符 ⚠️ 待接入
│       ├── obsidian_skill.py  # Obsidian skill 占位符 ⚠️ 待接入
│       ├── vault_io.py        # 笔记读写 + status 管理（仅内部）
│       └── retriever.py       # RAG 检索（仅 promoted）+ mtime 增量索引（ensure_index_fresh）
├── mcp_server/      # MCP 适配层（薄，无业务逻辑）
│   └── server.py
├── scripts/         # 调试入口（第一层，绕开 Host/MCP）
│   └── debug_run.py
└── tests/           # 冒烟测试
```

## 当前进度

- [x] 项目骨架与依赖配置
- [x] 配置层（LLM/API key 用占位符）+ KBState
- [x] 核心工具层
  - [x] LLM 工厂（Ollama / API 占位符）
  - [x] **视频转文本**：yt-dlp CC 字幕 + Whisper 三级 fallback（参考 bilibili-render-pdf skill 方法论独立实现，不依赖 Host skill）
  - [x] **笔记格式化**：LLM 优先，占位符时基础 frontmatter 包装 fallback
  - [x] **Obsidian CLI 适配层**：官方 `obs` / yakitrak `obsidian-cli` / 文件系统 三级 fallback（不依赖 Host skill）
  - [x] vault_io：笔记读写 + status 管理（信任闸门：create_staged_note 强制 staged）
  - [x] retriever：RAG 检索（metadata 物理隔离 staged）+ 两级索引刷新（全量幂等重建 / mtime 增量）
- [x] 三个 Agent 子图与节点
- [x] MCP Server 适配层（3 个工具）
- [x] 调试入口与冒烟测试（12 项全通过）
- [ ] **填入真实 LLM key / Ollama 模型名** → `.env`
- [ ] 安装系统依赖（可选）：ffmpeg（Whisper 转写需要）、Obsidian CLI（自动更新双链用）

### 能力开关（.env）

| 能力 | 开关 | 关闭时行为 |
|---|---|---|
| Vault 路径发现 | `VAULT_AUTODISCOVER` | fallback `.env` 的 `VAULT_ROOT` |
| 视频转写 | `VIDEO_TO_TEXT_MCP_ENABLED` | 走 stub 占位文本 |
| Obsidian CLI 落地 | `OBSIDIAN_SKILL_ENABLED` | fallback 文件系统直接写入 |
| LLM 格式化 | `LLM_PROVIDER` + 模型名非占位符 | fallback 基础 frontmatter 包装 |

三个能力**独立判断**可用性并优雅降级，互不影响。完全占位模式下链路仍可跑通验证。

### 多 Host 通用性

本系统**不依赖任何 Host 的 skill**。视频转写和 Obsidian 操作均在 `core/tools/` 独立实现，
参考开源 skill 的方法论但不调用 skill 本身。因此可在 Codex / Claude Code / WorkBuddy 等
任意支持 MCP 的 Host 中使用，行为一致。

## 调试策略（三层）

| 层级 | 方式 | 目标 | 消耗 Host token |
|---|---|---|---|
| ① 日常主战场 | 直接调用 `core/`（`langgraph dev` 或 pytest） | 核心业务逻辑 | 否 |
| ② 验证适配层 | MCP Inspector 手动扮演 Host | MCP schema/参数/返回 | 否 |
| ③ 阶段性验收 | 接入真实 Host（Codex 等） | 端到端体验 | 是（少用） |

## 快速开始

```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 配置（先复制占位符配置）
cp .env.example .env
#    Vault 路径自动从 obsidian.json 解析（装了 Obsidian 即可，无需手填）；
#    LLM key 与外部 MCP 暂留占位符。无 Obsidian 桌面端时在 .env 显式设 VAULT_ROOT

# 3. 第一层调试（绕开 MCP/Host，直接验证核心逻辑）
python scripts/debug_run.py

# 4. LangGraph Studio 可视化调试（逐节点查看 state）
langgraph dev

# 5. MCP Server（供 Host 调用 / MCP Inspector 调试）
python -m mcp_server.server
```

## 关键设计决策

- **单一 Vault + status 字段**：不做人机分库，靠 frontmatter `status: staged|promoted` 区分信任度
- **status 用 frontmatter 字段而非 tag**：状态是互斥单值，字段能保证约束
- **图外人工环节（方式B）**：不使用 LangGraph `interrupt`，更贴合 git 分支开发节奏
- **去除图内 Supervisor 路由**：Host 选哪个 MCP 工具即完成路由，图内二次判断是重复劳动
- **MCP 只暴露业务流程级工具**：不暴露内部原子操作，防止绕过信任闸门
- **被动式触发**：本期不监听 Vault 变化，由 Host 调用驱动
- **向量索引两级刷新**：`query_kb` / `trigger_correlation` 子图入口自动调 `ensure_index_fresh` 按 mtime 增量索引（manifest 记录每篇笔记的 chunk_ids），人工 promote 后无需手动跑 index 即可被检索；`python scripts/debug_run.py index` 提供强制全量重建（幂等：先 delete_collection 再重建，不累积重复 chunk）
- **Vault 路径动态解析**：不硬编码 vault 路径（遵循 obsidian skill 规范 "prefer print-default / obsidian.json"）。`settings.vault_path` 优先调 `resolve_vault_path()`（`obsidian-cli print-default --path-only` → `obsidian.json` 的 `open:true` vault），失败 fallback `.env` 的 `VAULT_ROOT`。装了 Obsidian 桌面端即可自动发现，换机器/vault 名无需改配置；测试用 `vault_autodiscover=false` 保证隔离
- **yakitrak CLI 依赖按命令区分**：`create`/`move`/`open` 走 `obsidian://` URI，仍需 Obsidian 桌面端安装（与官方 `obs` 同依赖）；仅 `print-default`/`search`/`list` 不依赖 Obsidian 运行。无 Obsidian 桌面端时真正能兜底的只有文件系统直接写入
