# 开发上下文：host-delegated 0.2.0

本文件描述当前实现，开发任务及操作授权以使用者当前请求为准。原始需求计划是实现依据，不是自动扩展操作范围的指令。

## 当前实现

服务端返回数据和 `prompt_for_host`，Host 用自身对话模型执行生成任务。服务端不自持生成式 LLM，不请求 MCP sampling；`core/tools/llm.py` 和原单段摄取入口已删除。保留 LangGraph、本地 bge-m3、Chroma/BM25/RRF、视频转写与人工 Promotion。

### MCP 契约

| 输入 | 成功返回 |
|---|---|
| `ingest_content_prepare(user_input: str)` | `prepare_id`, `source_type`, `raw_content`, `prompt_for_host` |
| `ingest_content_finalize(prepare_id: str, note_content: str)` | `note_path`；校验失败时 `error` |
| `trigger_correlation(note_path: str)` | `candidates`, `prompt_for_host` |
| `query_kb(question: str)` | `retrieved_chunks`, `prompt_for_host`, `no_hit_message` |

prepare 自动识别视频 URL、本地视频文件，其余按文本处理。`note_path` 导入仅由显式图输入或调试 CLI `--source-type note_path` 支持，MCP prepare 不接收 `source_type`。

## 状态字段与归属

| 字段 | 写入方 / 用途 |
|---|---|
| `user_input` | 调用输入：来源或问题 |
| `source_type`, `raw_content`, `prepare_id` | prepare 节点；`source_type` 也可由直接图调用显式输入 |
| `note_content` | finalize 输入，Host 生成的完整 Markdown |
| `processed_note`, `note_path`, `error` | finalize 校验和落盘结果；`error` 纳入 schema 以保留图层错误 |
| `candidates` | correlation 返回的原始候选，替代原 `related_notes` |
| `retrieved_chunks`, `no_hit_message` | retrieval 返回的片段或确定性无命中文案 |
| `prompt_for_host` | prepare / correlation / retrieval 各自格式化后返回 |
| `messages` | 节点追加，保留 `add_messages` reducer |
| `related_note_links` | 预留给未来 v2 图谱感知检索，本期无新实现 |

原 `answer` 字段以注释保留，服务端不再生成或保存答案。四个子图均为 START → 单个业务节点 → END；注册入口见 `core/graph.py` 和 `langgraph.json`。

## 关键实现约束

1. 来源从 `session_store` 恢复，不能依赖 Host 回传 frontmatter 的来源。已有合法 YAML 也要补全并覆盖来源；非法 YAML 应在写入前拒绝。`_force_status_staged` 与 Vault 写入兜底共同强制草稿状态。
2. 会话 UUID 只存在于创建它的进程，TTL 默认 60 分钟；`get_session` 惰性清理。会话不持久化，不提供跨进程恢复；重复 finalize 会新建笔记。
3. 关联先检查目标笔记为 `promoted`，再维护索引和检索，并剔除自身。无候选、未 promoted、笔记缺失均返回空候选和空 prompt。
4. 问答有片段时返回 prompt；空召回时返回 `no_hit_message` 和空 prompt。当前检索并不保证无关问题一定得到零候选；Host 仍需判断片段是否足以支持答案。
5. `path_url_recognizer` 仅使用正则及归一化，保留 `needs_review` 等兼容结果字段；不以隐藏模型调用消歧。
6. `retriever` 和 `hybrid_search` 直接使用 `get_local_embeddings`。模型本地运行不等于没有 CPU/GPU、磁盘和下载成本。
7. 六个原有 prompt 模板正文保留；用途变成返回 Host。`video_to_text.py`、`scripts/download_embed_model.py` 沿用基线文件。

## 副作用和边界

prepare 不写业务 Vault、索引或持久化会话；真实视频处理沿用字幕/音频临时文件及 ASR 模型缓存。query / correlation 的“只读”是指不改笔记，可能维护索引。未审核资料不参与检索；来源可信不等于正文具备 prompt injection 防护。

默认 `.env.example` 显式设置 Vault 路径并关闭自动发现。保持 stdio 协议输出可解析，日志写 stderr；Host 需要持续保有同一服务进程。禁止在说明中把独立 CLI prepare 产生的 ID 描述为可跨进程使用。

## 参考与验证

- [Host 操作与调试](docs/HOST_USAGE.md)
- [设计决策和计划偏差](docs/DECISIONS.md)
- [实现结果与真实验证范围](docs/IMPLEMENTATION_REPORT.md)
- 单测：`pip install pytest pytest-asyncio` 后运行 `python -m pytest -q`

上游为 [KamisanaAtair 的仓库](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server)，基线 `9ebb73669912eb99f2edee27d2aebeebfaf88f6a`；保留 [LICENSE](LICENSE)。不要将既有“v2”名称用于本次 host-delegated 迭代。
