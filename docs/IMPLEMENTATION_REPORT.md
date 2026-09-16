# host-delegated 实现结果

## 交付概况

已基于 [KamisanaAtair/Obsidian-personal-kb-MCP-server](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server) 的 `main` 提交 `9ebb73669912eb99f2edee27d2aebeebfaf88f6a` 实现 host-delegated 版本，项目版本为 `0.2.0`，发布分支为 `codex/host-delegated`。

**生成式模型调用已从服务器移除。** 服务器负责来源处理、本地检索、会话校验与草稿落盘；笔记正文、关联理由及引用式答案由 MCP Host 使用自身模型生成。服务器不调用 Host 私有 API，也不依赖 MCP sampling。

公开源码包含实现、通用配置示例、使用说明、测试与原始 LICENSE；不包含虚拟环境、模型权重、索引、密钥、个人笔记或本机 WorkBuddy 配置与日志。本文记录实际验证摘要，本机原始日志不随公开源码发布。

## 功能完成情况

| 功能 | 实现结果 | 关键位置 |
|---|---|---|
| 摄取准备 | 提取/读取原始内容，保留用户说明，返回 UUID 会话和 Host prompt；不创建笔记 | `core/nodes/ingestion.py` |
| 摄取落盘 | 校验有效会话和 Markdown；以会话来源覆盖 Host 来源，强制 staged 后写 Inbox | 同上、`core/tools/obsidian_skill.py` |
| 会话管理 | 进程内字典，UTC 创建时间，默认 60 分钟 TTL，查询时惰性清理 | `core/tools/session_store.py` |
| 关联发现 | 非 promoted 在索引/检索前返回；有效笔记返回候选与 Host prompt，去掉自身 | `core/nodes/correlation.py` |
| 知识库问答 | 返回 promoted 片段、来源与 Host prompt；无召回返回确定性文案 | `core/nodes/retrieval_qa.py` |
| MCP 和图 | 恰好四个工具、四个独立子图，KBState 包含错误字段 | `mcp_server/server.py`、`core/graph.py` |
| 本地检索 | 检索器及混合检索直接使用原有 bge-m3 本地工厂 | `core/tools/retriever.py`、`hybrid_search.py` |
| 调试入口 | 同进程 prepare → 提供 Host Markdown → finalize；显示候选/检索数据和 prompt | `scripts/debug_run.py` |

`core/tools/llm.py` 和旧 `ingestion_graph.py` 已删除。Ollama/OpenAI 服务端配置及 `langchain-ollama`、`langchain-openai` 直接依赖已移除。六个业务 prompt 字符串与基线完全一致。

## 按现场代码补齐的内容

1. **计划遗漏的生成调用**：`path_url_recognizer.py` 存在路径识别 LLM fallback，已移除，保留正则、归一化和歧义提示。
2. **计划遗漏的 Embedding 导入**：检索器和混合检索都从旧 `llm.py` 导入工厂，已迁移至 `get_local_embeddings`，避免删文件后报错。
3. **错误通过图传递**：附件 State 示例遗漏 `error`，已补入，否则会话错误可能被 LangGraph 过滤。
4. **来源一致性**：上游 helper 仅补 status，无法保证已有 frontmatter 中的来源真实。本版无论 Host 是否填写来源，均采用服务端会话值；用 YAML 序列化处理冒号、换行，并拒绝非法 YAML 或非键值对象。
5. **可携带的测试**：上游说明测试位于另一台机器的外部仓库，本版把针对本次改造的测试直接纳入源码包。
6. **源码发布清单**：补充 `MANIFEST.in`，确保构建源码分发时包含配置、文档和测试辅助数据。

## 实际验证

验证日期：2026-09-16。验证环境：macOS ARM64，Python `3.12.14`；MCP `1.30.0`、LangGraph `1.2.11`、langchain-core `1.6.3`、Chroma `1.5.9`、langchain-chroma `1.1.0`、Pydantic `2.13.5`、pytest `9.1.1`。这些版本及下方包数量是本机环境快照，不是强制版本锁。

| 检查 | 结果 |
|---|---|
| 依赖安装 | 项目运行和开发依赖安装于独立环境；补齐 yt-dlp 默认组件、EJS、Deno，并复用本机 ffmpeg / ffprobe |
| `.venv/bin/python -m pytest -q` | 发布准备阶段复跑：**28 passed in 10.26s** |
| 真实 LangGraph `.ainvoke` | prepare/finalize 正常路径、错误传播与来源信息通过 |
| 真实 MCP stdio 客户端/服务器 | 初始化、四工具 schema、无效会话、prepare/finalize、草稿关联闸门通过 |
| FastMCP 注册工具调用 | `query_kb` JSON 结果和无命中分支通过 |
| 真实 Chroma + 测试 Embedding | 所测查询返回 promoted 笔记，未召回 staged 夹具；笔记降回 staged 后旧索引块被移除。这不证明 BM25 能过滤外部手工写入集合的任意 staged 块 |
| 真实 bge-m3 推理 | 三段中文文本生成 `3 × 1024` 维向量；相关句余弦相似度 `0.8623`，无关句 `0.3208` |
| 真实 bge-m3 + MCP + Chroma/BM25 | stdio 客户端发现并调用四工具；检索、关联返回 promoted 夹具，排除 staged；prepare 不写 Vault，finalize 强制 staged 并恢复会话来源 |
| 真实本地视频转写 | 临时英文合成语音经 ffmpeg 制成 MP4，通过 `ingest_content_prepare` 调用 faster-whisper medium / CPU / int8；得到有效转写，prepare 未写 Vault |
| WorkBuddy 配置 | 5.3.14 已读取合并后的新服务配置；原生日志显示等待首次信任，**尚不能视为已连接** |
| CLI 子进程 | `--help`、`status`、同进程 `ingest --note-file` 通过，支持从项目外目录运行 |
| 模板及模块保留 | 六个 prompt 值一致；视频模块、本地 Embedding 文件及下载脚本 SHA-256 与基线一致 |
| 静态检查 | 改动 Python 文件通过 Ruff `E4,E7,E9,F`；全库通过致命错误规则 `E9,F63,F7,F82`；compileall、diff whitespace 检查通过 |
| `uv build` | 源码分发包及通用 Python wheel 构建成功 |
| 分发包检查 | 首轮源码分发包含配置、文档、测试辅助文件；wheel 安装到临时目录后成功导入并列出四工具 |
| `uv pip check --python .venv/bin/python` | 本机安装验证时，159 个已安装发行包依赖一致；Deno 版本、EJS 导入与 ffprobe 读取临时 MP4 均通过 |

Ruff 的全库扩展规则检查未全部通过：包含上游保留模块的旧类型注解、未用导入及风格问题。本版没有为清理这些问题修改要求保留的模块；上述“静态检查通过”仅指表内明确的规则与范围。首次导入 jieba 曾出现其正则转义 SyntaxWarning，测试通过，最终整套输出为 28 passed。

测试全部使用临时 Vault，明确关闭真实 Vault 自动发现。回归测试使用确定性测试 Embedding；另行使用真实 bge-m3 验证了小样本向量、Chroma/BM25 检索与 MCP 调用。两者覆盖不同，不构成大规模检索质量评测。测试未调用生成式模型。

真实 bge-m3 权重来自官方 `BAAI/bge-m3` 提交 `5617a9f61b028005a4858fdac845db406aefb181`。Whisper 实测输入为本地合成英文音频，输出为 `This is a local knowledge-based test, we review notes.`；该测试不代表中文语音或外部视频网站已验证。

## 计划偏差及使用边界

- **视频 prepare 的写入边界**：视频模块按要求保留原样。prepare 不写笔记库、索引或磁盘会话；真实视频管线仍可能生成临时字幕/音频/SRT，并下载或使用 ASR 模型缓存。因此没有满足字面上的“任何文件都不写”；文本、视频 stub 和本地真实视频测试均验证了 prepare 不写 Vault。
- **成本含义**：Host 的生成仍消耗其正常上下文、额度或计费；本地 Embedding、Chroma、视频转写的算力、存储及下载成本仍存在。没有测量真实节省金额或运行加速比例。
- **会话边界**：单用户、单进程；重启失效；到期须重新 prepare；同一有效 ID 重复 finalize 会产生新草稿，未提供幂等/消费协议。
- **读取边界**：MCP prepare 的参数按计划只有 `user_input`，不会自动把 Markdown 路径作为笔记导入；显式 `note_path` 仍可由调试入口或内部图输入使用。
- **“只读”的含义**：关联和问答不改笔记，但会按原逻辑维护检索索引。向量检索可能返回与问题弱相关的最近邻；无命中文案用于空召回，Host 必须依照证据充分性决定能否作答。
- **既有 BM25 索引边界**：本服务的正常索引流程只写入 promoted 笔记；BM25 沿用上游实现，从该专用 Chroma 集合读取文档，没有再次按 status 过滤。发布审计确认：若外部程序或手工向集合写入 staged 文档，匹配词查询可能将其召回。应使用本服务专用的索引目录和集合，不与其他写入者共享；原有回归夹具没有覆盖这种匹配词污染场景。本次发布保留该既有运行行为。
- **信任边界**：会话来源校验处理来源伪造，强制 staged 处理状态伪造；这些机制不等于清除正文中的 prompt injection。Host 应把原始笔记视为资料，并保留人工审核流程。

尚未验证：WorkBuddy 完成原生首次信任后的实际连接及完整 Host 生成循环、YouTube/Bilibili 等外部站点下载和字幕获取、中文 ASR 质量、Obsidian CLI 写入分支、长视频及大规模 Vault 性能。已创建独立 Vault 并合并本机 WorkBuddy 配置，但测试未使用用户真实笔记。WorkBuddy 的当前状态为“配置已读取，等待信任”，不等同于全链路接入成功。

详见 [使用与调用示例](HOST_USAGE.md)、[WorkBuddy 通用接入指南](workbuddy.md)、[决策记录](DECISIONS.md)。原始许可证与版权信息保存在根目录 [LICENSE](../LICENSE)，以该文件为准。
