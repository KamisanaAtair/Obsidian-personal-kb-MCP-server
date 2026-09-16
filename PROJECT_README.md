# 项目目标与架构

## 目标

让支持 MCP 的 AI 客户端在日常对话中使用本地 Obsidian 知识库：把外部文本或视频整理为待审笔记，对已审核笔记发现关联，并基于已审核资料回答问题。

host-delegated 0.2.0 保留 LangGraph、bge-m3 本地 embedding、Chroma + BM25 混合检索和既有视频转写模块，将所有生成式判断转移到 Host。它不需要服务端生成模型或生成 API key，也不通过 MCP sampling 向客户端索取模型调用。

## 工作流

```text
用户输入 → Host 调用 prepare → 服务端读取/转写 + 创建内存会话
         ← 原文 + prepare_id + prompt_for_host
Host 生成 Markdown → 调用 finalize → 校验 YAML、补全来源、强制 staged
                   ← Inbox 中的草稿路径
用户人工审核 → 手动设为 promoted
Host 调用 query / correlation → 服务端刷新索引、检索 promoted 片段
                             ← 检索数据 + prompt_for_host
Host 生成答案 / 关联理由 → 向用户展示
```

prepare/finalize 的拆分把服务端写笔记与 Host 生成正文连接起来。关联和问答的生成结果直接展示给用户，无需回传服务端；它们不修改笔记，但可能更新本地检索索引。

## 职责分工

| 层 | 职责 |
|---|---|
| `mcp_server/` | 四个 stdio MCP 工具；参数映射、调用子图、格式化返回 |
| `core/subgraphs/`、`core/graph.py` | prepare、finalize、correlation、retrieval 四个独立 LangGraph 入口 |
| `core/nodes/` | 原文准备、草稿校验落盘、候选检索、问答片段准备 |
| `core/tools/` | 进程内会话、Vault IO、索引、embedding、视频转写、确定性路径识别 |
| `config/` | 配置，以及格式化后交给 Host 的六个既有 prompt 模板 |
| Host | 笔记正文、关联理由、带引用的答案 |
| 用户 | 审核草稿、决定是否提升状态或添加双链 |

## 信任闸门与来源

- finalize 从服务端内存会话恢复 `source_type`、`source_ref`，覆盖 Host 的同名声明，补齐元数据后强制草稿状态。
- 只有 `promoted` 笔记进入索引和召回；对未审核目标调用关联工具，会在刷新索引和候选检索前返回空结果。
- `create_staged_note` 保留写入兜底，MCP 不提供 `promote` 或任意修改状态的工具。
- 来源与状态校验防止元数据伪造，不能证明正文没有被恶意指令操纵。正文仍需人工审核；`staged` 隔离也不代表 Host 处理原文时自动具备 prompt injection 防护。

## 索引与会话

query / correlation 按 mtime 增量维护索引；`python scripts/debug_run.py index` 提供全量重建。检索保留向量、BM25 和 RRF 融合，本期不改为图谱检索。

摄取会话只在单进程内存中保存来源和创建时间，默认 TTL 为 60 分钟，每次读取会话时惰性清理过期记录。重启失效，TTL 内重复 finalize 会再次创建草稿，不保证幂等。

## 使用与验收

安装见 [README](README.md)，工具契约及 Host 操作见 [HOST_USAGE](docs/HOST_USAGE.md)，差异说明见 [DECISIONS](docs/DECISIONS.md)，实际检查结果见 [IMPLEMENTATION_REPORT](docs/IMPLEMENTATION_REPORT.md)。

仍需承担 Host 生成额度、本地推理和模型存储成本；并未承诺零费用、所有 Host 行为一致或真实外部链路均已联调。“v2”保留为未来图谱感知检索的名称。
