# Personal KB — 自选模型的本机知识库

把 Obsidian 笔记接入 WorkBuddy，也可以直接在本地页面整理内容。**0.4.0b2** 修复 Windows 源码克隆后缺少启动组件的问题，并保留独立模型配置、黑紫 / 白紫界面和本地任务页：你可以继续使用宿主模型，或让知识库直接调用自己的 Qwen、Kimi、GLM、DeepSeek、本地 Ollama 或自定义兼容服务。

当前为候选试用版；已实现功能不等于全部通过实机验收。进度、测试证据和未完成项见 [本轮开发与测试日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-03-model-settings-development.md)。

## 首次使用

下载适合你电脑的 **0.4.0b2 候选安装包**：

- [Windows x64](preview-releases/0.4.0b2/PersonalKB-0.4.0b2-windows-x64.zip?raw=true) · [SHA256](preview-releases/0.4.0b2/PersonalKB-0.4.0b2-windows-x64.zip.sha256)
- [macOS 14+ Apple 芯片](preview-releases/0.4.0b2/PersonalKB-0.4.0b2-macos-arm64.zip?raw=true) · [SHA256](preview-releases/0.4.0b2/PersonalKB-0.4.0b2-macos-arm64.zip.sha256)

1. **完整解压 ZIP**。Windows 选择“全部解压”；Mac 在 Finder 双击 ZIP，然后进入解压后的文件夹。
2. **双击启动**：Windows 打开 `install.cmd`，Mac 打开 `install.command`。启动器准备私有 Python 和基础依赖，并打开本机网页，无需预装 Python 或 Git。
3. **选择生成方式**：默认使用宿主模型，无需额外 Key；如需自选模型，点击右上角“设置”，添加连接、测试，再保存并应用独立模型配置。
4. **开始使用**：本地页面的“本地任务”可以直接执行独立生成；要在 WorkBuddy 中使用，先点击工作台的“接入 WorkBuddy”，再到 WorkBuddy 完成原生信任。每次任务明确填写或说明笔记库绝对路径及分类目录。

安装时不选择笔记库，也不会自动索引笔记。语义检索和视频组件按需要准备；文字整理无需先下载约 2.3 GB 的检索模型。安装器不自动安装 Skill，WorkBuddy 通过 MCP 工具完成业务。

**[从用户视角开始试用](README-FIRST.md)** · [安装与恢复](docs/SETUP_FROM_ZIP.md) · [WorkBuddy 接入](docs/workbuddy.md) · [十个 HTTP MCP 工具](docs/HOST_USAGE.md)

安装包放在仓库中，不代表已创建 GitHub Release。从 **0.4.0b2** 起，本分支的 Git 克隆和“Code → Download ZIP”源码 ZIP 均包含 Windows 所需的 `uv.exe`；完整取得目录后可直接运行根目录 `install.cmd`。Mac 用户仍使用上面的平台安装 ZIP，源码目录不附带 Mac 二进制。[0.3.0b1 历史包](preview-releases/0.3.0b1/) 保留原文件和 SHA256，不包含本次模型设置功能。

## 模型由你选择

| 模式 | 谁负责生成 | 使用方式 |
|---|---|---|
| 使用宿主模型 | WorkBuddy 等 MCP 客户端 | 服务准备资料，宿主生成正文；无需为本项目配置生成模型 Key |
| 使用独立模型 | 本机服务调用已配置的模型 | 服务生成、校验并保存笔记，或返回带引用的答案；本地页面也能完成任务 |

独立配置控制知识库内部的生成模型，**不会替换 WorkBuddy 自身的对话模型**。生成方式、默认连接及笔记整理 / 知识问答 / 关联分析的任务覆盖都在“模型服务”中设置。

| 专属入口 | 默认连接 | 设置中的区别 |
|---|---|---|
| 通义千问 Qwen | 阿里云百炼官方兼容接口 | 可选择地域；Key 需与地域对应 |
| Kimi | Moonshot 官方兼容接口 | 使用开放平台 Key，不能用 Kimi Code 订阅凭据替代 |
| 智谱 GLM | 智谱官方兼容接口 | 通用 API 与 Coding Plan 端点需按实际账户区分 |
| DeepSeek | DeepSeek 官方兼容接口 | 模型 ID 和权限以账户可用模型为准 |
| 本地 Ollama | 本机 Ollama 原生接口 | 先启动 Ollama 并准备模型；思考能力执行前动态核验 |
| 自定义兼容服务 | 用户填写的 Chat Completions 地址 | 远程地址使用 HTTPS；本机回环地址允许 HTTP |

可先保存地址与 Key，再获取模型列表并填写模型 ID。保存连接、测试通过、当前启用分别显示；测试会发送简短请求，可能产生 API 费用。仅对受支持的模型开放思考参数；未知型号可使用服务商默认参数。

四家云端预设直接请求对应官方地址，共用连接池与流式传输。“OpenAI 兼容”描述请求格式，不意味着经过 OpenAI 服务器，也不自动限制传输速率。原生接口与兼容接口谁更快需要同条件实测，本版不作速度保证；任务详情显示服务端记录的首事件、首正文、总耗时和用量。

生成模型 Key 使用系统凭据库 `keyring` 保存，配置文件只保存凭据引用，页面不会回填 Key。凭据库不可用时明确失败，不降级为明文保存。**视频转写的旧 DashScope Key 仍保存在本机 `data/credentials.json`，尚未迁移到系统凭据库**。任务原文或检索片段会发送至所选生成服务；本地索引不因此上传整个库。

## 笔记、任务与恢复

- 新笔记只保存到明确指定的现有库和库内目录，强制 `status: staged`；由你在 Obsidian 审核后改为 `promoted`。
- 索引需单独授权。本地任务页要求勾选授权并指定包含 / 排除目录；没有 `status` 的旧 Markdown 只有明确选择后才纳入，原文件不修改。
- 每个库分别保存范围与向量数据库；同库重新索引会替换范围。查询目录只能缩小已授权范围。
- 开启自动同步后约每 30 秒检查变化。问答和关联在生成前后、最终交付和历史结果读取时检查来源；来源变化会使旧结果失效，页面清除已展示正文。
- 本地页面使用带认证的 SSE 展示增量内容，生成中内容标明待校验；最终结果以任务接口校验结果为准。宿主是否逐字展示由其客户端决定。
- 任务入队时固定模型配置快照。切换设置只影响新任务；失败不自动换厂商、退回宿主或重试模型调用。
- 手动重试优先复用已持久化的生成检查点，再执行幂等保存；同任务相同内容不会重复创建文件，也不会覆盖用户已修改的笔记。若生成结果尚未写入检查点，手动重试仍可能再次调用模型并计费。

退出或关机后可双击安装入口，或安装目录内的 `Open Personal KB.cmd` / `.command` 重开服务；“后台任务”提供继续 / 重试。本试用版不添加开机自启，未做代码签名，首次安装需要联网。提供 Windows x64、macOS 14+ Apple 芯片包；不支持 Intel Mac。

## 验证范围与试用边界

| 范围 | 当前证据 | 待验收 |
|---|---|---|
| 历史 0.3 基础能力 | 已有 93 项测试及 7 个子测试的基线；Mac 基础安装、检索模型本地加载、视频组件准备有历史证据 | 不据此宣称 0.4 新安装包或模型设置已验收 |
| 0.4 自动化 | 0.4.0b1 基线已有 176 项测试和 7 个子测试通过，覆盖模型协议、安全、故障恢复及业务集成 | 0.4.0b2 的新验证结果见下方 Windows 修复日志 |
| 真实独立模型 | Ollama Qwen3 4B 与 bge-m3 的真实整理、索引、问答和关联通过 16 项语义及保存检查 | 真实页面与 WorkBuddy 操作；更多模型的答案质量与性能 |
| 四家云端服务 | 按协议进行自动化测试；当前没有对应账户 Key | 真实账户认证、模型权限、计费和端到端行为 |
| 页面及 WorkBuddy | 已实现本地管理页、接入配置与 HTTP MCP | Computer Use 页面黑盒、WorkBuddy 原生信任和真实业务；当前 Mac 锁定，尚未完成 |
| Windows 安装启动 | 0.4.0b2 新增干净克隆、源码 ZIP、平台 ZIP 的 Windows 自动化门禁；执行结果见修复日志 | Windows 桌面双击、浏览器视觉、WorkBuddy 原生操作；真实云端 ASR、大型库性能 |

“配置已保存”“收到客户端握手”“业务完成”是三个独立结果。测试客户端握手不能证明 WorkBuddy 已完成原生信任；模型准备成功不能证明用户库已经建立索引。测试范围更新后以 [开发日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-03-model-settings-development.md) 的实际证据为准。

本次 Windows 修复的提交、安装包校验和实际 CI 结果见 [Windows 启动修复日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-04-windows-installer-fix.md)。

## 开发与打包

```bash
uv venv --python 3.11
uv pip install -e '.[legacy,dev,semantic,video]'
uv run --no-sync python -m pytest tests tests_local -q
uv run --no-sync python scripts/build_installer.py
```

纯基础服务可用 `pip install -e .` 后运行 `personal-kb --data-dir /absolute/path/to/test-data --no-browser`，不会自动写 WorkBuddy 配置。生成服务位于 `local_app/models/`，`ModelFactory` 选择厂商适配器，公共服务管理配置、凭据引用、连接池与响应解析；见 [当前开发上下文](PROJECT_CONTEXT.md)。

Windows uv 0.12.12 已按官方归档校验并精确纳入 Git；Mac 打包前仍需按 `installer/release.json` 下载并校验官方归档，将可执行文件放入 `installer/vendor/macos-arm64/`。打包会检查所选平台二进制的大小和 SHA256、必要文件及版本一致性；缺失或不匹配时立即失败。仅构建 Windows 可运行 `python scripts/build_installer.py --platform windows-x64`。安装器使用带 SHA256 的依赖锁，语义模型使用固定 revision 与文件清单。`dist/` 是构建输出；预览交付包按版本另存，不覆盖 0.3 历史包。旧四工具 stdio 实现保留，见 [旧版说明](docs/LEGACY_STDIO.md)，不等同于本版 HTTP MCP。

## 上游与许可证

基于 [KamisanaAtair / Obsidian-personal-kb-MCP-server](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server)。保留上游署名与 [LICENSE](LICENSE)（PolyForm Noncommercial License 1.0.0，Copyright © 2026 XvAo）。uv 的许可证随包保留。
