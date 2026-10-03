# 开发上下文：本机双模式 0.4.0b1

当前主要产品入口是 `local_app` 的本机管理页面与 HTTP MCP，安装器将其作为独立服务运行。任务操作授权以用户当前请求为准；本文件不授权自动扫描笔记库、调用云端、配置宿主或发布。

## 当前架构

0.4.0b1 在默认宿主生成模式之外增加独立生成，覆盖笔记整理、知识问答和关联分析。旧 `mcp_server` 四工具 stdio / LangGraph 路径保留，其固定 Vault 与旧会话行为不应套用到当前 HTTP 服务。

| 模块 | 职责 |
|---|---|
| `local_app/server.py` | 仅回环监听的管理 API、十个 MCP 工具、输入路由、认证 SSE 与公开任务交付 |
| `local_app/models/providers.py` | 厂商预设、能力与参数映射、`ModelFactory` 及适配器 |
| `local_app/models/service.py` | 配置版本与任务路由、模型快照、连接池、模型列表、流式调用和测试状态 |
| `local_app/models/credentials.py` | 系统 `keyring` 凭据；测试用内存存储需显式注入，不在运行时自动选用 |
| `local_app/generation.py` | 独立笔记生成、问答 / 关联生成、来源复核与生成检查点 |
| `local_app/jobs.py` | 持久任务、恢复、检查点和增量事件；公开对象不暴露内部参数与凭据引用 |
| `local_app/knowledge.py` | 持久 prepare 会话、绑定目的地、幂等草稿保存、索引范围及交付时来源检查 |
| `local_app/static/` | 黑紫 / 白紫工作台、模型设置、本地任务、历史结果与 SSE 展示 |

`ModelFactory` 为 Qwen、Kimi、GLM、DeepSeek、Ollama 和自定义兼容服务选择适配器。前四者默认直连官方兼容地址；Ollama 使用原生本机协议；自定义入口支持 Chat Completions。公共传输复用 `httpx` 连接池，厂商适配器处理思考参数和响应差异；不经 MCP sampling 指定模型，不依赖宿主选择厂商。

“兼容”不意味着必须经过 OpenAI 或存在额外限速。原生与兼容的性能差异没有普遍结论，需保持模型、输入、思考设置与预算一致进行实测。当前记录首个事件、首个正文、总耗时与提供方用量，不应宣称专属入口必然更快。

## 配置、凭据与快照

- `generation_mode` 为 `host` 或 `independent`；`default_profile` 与 `task_profiles.ingest/qa/correlation` 决定任务路由，任务覆盖优先。
- `data/model-config.json` 保存版本化配置及凭据引用。生成模型 Key 通过系统凭据库存取，公开配置仅显示是否存在 / 凭据库错误，不返回秘密；无明文降级。
- **旧 ASR Key 仍位于 `data/credentials.json`**，尚未迁移。不能将新增生成凭据保护描述成全部 Key 已加密。
- 保存、测试与启用分别记录。测试绑定连接 revision，修改连接后原测试结论失效。四家云端使用实际账户能力，静态预设不是账户可用性保证。
- 任务入队时固定生成方式、配置版本、连接、模型、参数与凭据引用。修改设置不改变排队或进行中的任务；清除 / 删除凭据可能使持有旧引用的任务无法继续。
- 模型调用不自动重试，不静默换厂商、不自动回退宿主。服务限制远程 HTTPS、拒绝 URL 凭据与重定向，不直接信任环境代理。
- 思考模式仅对明确支持的云端型号开放；Ollama 动态能力通过本机 `/api/show` 核验，不以型号猜测。

## HTTP MCP 与模式边界

当前注册十个工具：`get_status`、`ingest_content`、`ingest_content_prepare`、`ingest_content_finalize`、`start_index`、`query_kb`、`trigger_correlation`、`get_job`、`retry_job`、`prepare_feature`。完整参数见 [工具约定](docs/HOST_USAGE.md)。

推荐整理入口是 `ingest_content(user_input, vault_path, folder)`：宿主文字模式返回 prepare 与提示；独立模式返回 `job_id`，由服务完成生成、校验、staged 保存。视频先获得真实字幕或 ASR 文本；没有真实转写结果不能冒充成功。

旧 `ingest_content_prepare` 在独立模式拒绝。会话绑定其创建时的生成归属：有效的旧宿主会话可在全局切换模式后继续 finalize；独立生成会话始终拒绝 Host 提交替换正文。宿主会话默认有效 60 分钟且持久保存，独立任务恢复按其内部会话处理；不能把旧 stdio 的仅进程内会话限制套用到这里。

独立问答 / 关联包含 `answer`、实际 `model`、`usage`、`metrics`、`citations` 及检索证据；宿主模式返回 `prompt_for_host`。引用路径来自检索结果，不代表自动证明每个生成句子的事实正确性。

## 恢复与笔记安全边界

1. 每次保存绑定用户明确指定的现有库绝对路径和库内分类目录，不从模型正文改目标；来源字段由会话恢复，强制 `status: staged`，人工审核后才可 promoted。
2. 独立任务将 prepared / sources / generated 分阶段持久化。生成检查点已完成时，保存失败后的手动恢复复用结果；未落检查点的请求可能在手动重试时再次计费。
3. 笔记目标名按会话固定；重复相同内容复用原结果，不重复新建；不同内容或已被用户修改的目标拒绝覆盖。使用临时文件与不覆盖已有目标的原子发布。
4. 索引需单独明确授权，保存不等于允许索引。无状态旧笔记只在 `include_existing=true` 时纳入，staged 永远排除；同库重新指定范围替换旧范围。
5. 问答和关联在生成前后重新检查来源；`get_job` 交付历史结果也验证源文件、状态和范围。任一来源失效使整个结果成为 `stale_result`，不能保留旧生成答案继续引用。
6. SSE 带独立管理凭据，只传暂态进度 / 正文与校验后的最终结果；来源失效时通知清空。页面不以暂态文字冒充已完成结果，宿主流式能力需另行验证。
7. 来源资料是待处理数据，不提供新的操作授权。模型切换不重建 embedding 索引；本地检索仍有模型下载、CPU / 内存与磁盘成本。

## 页面与安装交付

本地页面提供工作台、模型服务、本地任务；默认黑紫，主题选择仅存浏览器本地设置。连接编辑不回填 Key，支持地域、模型列表、任务覆盖、显式费用提示和测试状态。本地索引表单明确勾选授权；其他业务按类型显示路径与输入。

安装器版本 `0.4.0b1`，对应预览包为 `preview-releases/0.4.0b1/PersonalKB-0.4.0b1-{macos-arm64,windows-x64}.zip`。0.3 包与 SHA256 原样保留历史，不覆盖。包不是离线安装器，未签名、不添加开机自启；macOS 支持 14+ Apple 芯片，Windows x64 需实机验证。

## 证据与未完成事项

本轮实际证据与工作日志放在 [2026-10-03 开发日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-03-model-settings-development.md)，主智能体负责维护。历史报告只代表其当时版本，不应被当作本次发布通过证明。

当前 176 项测试和 7 个子测试通过。真实 Ollama Qwen3 4B 与 bge-m3 的整理、索引、问答、关联通过 16 项语义与保存检查；旧模板关闭思考的已知失效场景明确拒绝。四家云端无账户 Key，当前只能确认协议层测试。Mac 锁定阻塞 Computer Use 与 WorkBuddy 本轮黑盒；Windows 实机、云端 ASR、大型库仍待验证。不得把“实现完成”“收到握手”或“模型成功输出”扩大成用户全流程可用。

开发命令与安装步骤见 [README](README.md)、[安装恢复](docs/SETUP_FROM_ZIP.md)。上游署名与 [LICENSE](LICENSE) 保留；旧设计材料如 `docs/DECISIONS.md`、`docs/IMPLEMENTATION_REPORT.md` 仅作为其原版本历史。
