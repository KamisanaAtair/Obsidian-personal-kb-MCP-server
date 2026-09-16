# host-delegated 决策记录

基于上游 `9ebb73669912eb99f2edee27d2aebeebfaf88f6a` 的代码审计和开发计划实施。本文记录实现选择，不替代 [实际验证报告](IMPLEMENTATION_REPORT.md)。

## 核心决策

| 决策 | 备选方案 | 采用理由 / 限制 |
|---|---|---|
| 本次称为 host-delegated | 使用“v2”命名 | 既有 v2 指未来图谱感知检索，避免混淆；包版本为 0.2.0 |
| 服务端返回数据 + `prompt_for_host` | 服务端继续自持生成式 LLM，或调用 MCP sampling | 笔记整理、关联理由、答案合成统一由 Host 自身模型完成；仍消耗 Host 额度和上下文 |
| 摄取拆为 prepare / finalize | 单次调用直接落盘 | 生成正文交给 Host，校验与写入留在服务端；两段之间以服务端会话配对 |
| finalize 强制 staged，不拒绝 Host 声明的 promoted | schema 禁止传状态 | 保留写入兜底，无论输入声明何状态，最终只能是草稿 |
| 会话提供权威来源 | 信任 Host 回传的来源字段 | 配对后用服务端保存的 `source_type`、`source_ref` 补齐并覆盖，降低来源伪造风险 |
| 单进程内存会话 + 60 分钟 TTL | Redis / 持久化数据库 / 跨进程恢复 | 符合本地单用户工具规模；按读取惰性清理，重启失效，60 分钟是可调默认值 |
| finalize 后保留会话到 TTL | 使用后立刻消费 ID | 按计划保留简单 get_session 契约；重复 finalize 会新建草稿，不保证幂等 |
| `related_notes` 更名为 `candidates` | 保留原名 | 返回的是检索候选，不再是生成后的关联建议 |
| `answer` 保留为注释 | 完全删除字段 | 服务端不再保存答案，注释用于比较架构演进 |
| 关联 / 问答不回调校验生成结果 | Host 回传 JSON / 答案再解析 | 结果由 Host 展示，无下游服务端生成状态依赖；工具不改笔记，但可维护索引 |
| 保留四个 LangGraph 子图 | 移除图编排 | 缩小与上游的架构差异，保持 MCP 与核心逻辑解耦 |
| 保留本地 bge-m3 与既有视频转写 | 同时外移 embedding / ASR | 本期只外移生成式判断；模型推理、下载、磁盘成本仍存在 |
| 保留六个 prompt 正文 | 重写全部生成模板 | 沿用原任务语义，仅更改用途说明并将填参结果返回 Host |

## 代码审计发现的必要调整

### 1. 删除模型工厂前清理隐藏调用与 embedding 依赖

原 `path_url_recognizer.py` 除正则外还有隐藏的生成模型消歧调用。若只改三个业务节点，仍会残留服务端生成路径。本版删除该路径，保留正则、归一化及 `needs_review` 标记；歧义输入需要调用方复核。

原 `retriever.py` 和 `hybrid_search.py` 经旧 `llm.py` 获取 embedding。删除工厂前将两处改为直接使用 `get_local_embeddings`，保持本地 bge-m3 的用途和模型实现。`embeddings.py`、`scripts/download_embed_model.py` 保留基线文件；其中可能仍有上游时期的架构比较注释，当前架构以本版文档为准。

### 2. KBState 补充 error

计划给出的完整 State 示例没有 `error`，但 finalize 需要把校验错误穿过 LangGraph 返回 MCP。将 `error` 加入 schema，避免图层过滤未声明字段后丢失错误信息。

### 3. 修正已有 frontmatter 的来源补全缺陷

计划建议 helper 原样复用，仅在缺少有效 frontmatter 时补全。审计发现已有 frontmatter 可能仅含状态，仍缺来源；也可能含 Host 伪造的来源。仅判定“有合法 frontmatter”不能满足计划要求的服务端权威来源。

本版对所有正文执行 YAML mapping 校验与元数据补全，始终以会话覆盖来源，保留其余元数据及正文，再复用强制 staged 和 Vault 写入兜底。非法、非对象或未闭合的 YAML 在写入前拒绝；使用 YAML 序列化保存来源字符串，避免换行等字符破坏元数据结构。这是实现来源要求所需的修正，人工 Promotion 规则不变。

### 4. prepare “无写入”的验收口径

计划一方面要求 `video_to_text.py` 完全不动，另一方面要求视频 prepare 不产生“任何文件写入”。上游真实视频链路会下载临时字幕、音频并可能缓存 ASR 模型，两条要求按字面不能同时满足。

本版保留 `video_to_text.py` 的基线字节，采用明确边界：prepare **不写业务 Vault、不写索引、不持久化会话**；既有视频临时文件及模型缓存行为保留。模拟视频通过不代表真实视频链路无文件副作用。

### 5. 调试入口保留同进程配对

原单段 `ingest` 改为同进程 prepare → 显示 prompt → 读取 Host 正文文件 → finalize。`--note-file` 支持非交互模拟，缺省则等待输入文件路径。单独 `prepare` 仅供预览，退出后的 ID 不可跨进程使用。

MCP 签名按计划不提供 `source_type`。因此普通 Markdown 文件路径不自动作为文件导入；需要读取文件时由获授权的 Host 读作文本，或使用直接图输入 / CLI 的 `--source-type note_path`。

## 必须保留的解释边界

- “转嫁成本”仅指服务端生成调用外移。没有承诺免费，也没有保证具体 Host 的模型额度、上下文容量或调度行为。
- 无命中文案在召回为空时返回。现有 top-k 检索可能对无关问题仍返回候选，Host 需判断证据是否充分；本期未新增问答相关性判定器。
- 来源与状态校验防止元数据伪造，不能证明正文没有 prompt injection。staged 隔离与人工审核保留，Host 处理原始内容时也须把资料和用户指令区分开。
- “只读”关联 / 问答表示不修改业务笔记；增量索引维护仍有本地写入。
- 源码与自动测试结果不等于真实 Host、真实视频或完整 bge-m3 模型链路已完成联调。实际证据以实现报告为准。
- 上游 README 的许可证表述与实际 LICENSE 不一致；本版保留实际 [LICENSE](../LICENSE) 及其 `Copyright © 2026 XvAo`，按文件载明的 PolyForm Noncommercial License 1.0.0 标识，不沿用上游 README 的错误名称。
