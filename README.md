# Personal KB — 自选模型的本机知识库

把 Obsidian 笔记接入 WorkBuddy，也可以直接在本地页面整理内容。当前 **0.5.0b3 预览源码**支持图文视频笔记：截图结合对应时间点前后的讲解进行视觉分析，再整理成带库内图片附件的待审核笔记。文字、视觉和语音可以分别选择模型，同一连接复用一个 Key。

**最新功能请使用 [`codex/local-installer-preview` 分支](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/tree/codex/local-installer-preview)。** 仓库默认的 `feat/asr-dashscope-api-key` 分支及下方历史安装包可能仍是旧版，不会因打开仓库首页自动获得 0.5 功能。本轮提供更新后的源码，不上传新的 0.5 平台安装 ZIP，也未创建 GitHub Release。

## 首次使用

### Windows x64：下载当前分支的完整源码

1. 下载 **[0.5 预览分支源码 ZIP](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/archive/refs/heads/codex/local-installer-preview.zip)**，选择 Windows 的“全部解压”；也可以完整克隆下方指定分支。不要只下载或复制 `install.cmd`。
2. 进入解压后的项目根目录，确认 `install.cmd`、`installer/bootstrap.py` 和 `installer/vendor/windows-x64/uv.exe` 都在，再双击 **`install.cmd`**。首次联网准备私有 Python 和基础依赖，无需预装 Python；下载 ZIP 的方式也无需 Git。
3. 浏览器自动打开本机页面。核对页脚版本为 **0.5.0b3**，点击导航 **“我的模型”** 管理自己的连接，再到 **“模型用途”** 分配任务；默认也可以继续使用宿主模型。
4. 在 **“本地任务”** 直接使用独立模型。要通过 WorkBuddy 自然语言调用，点击工作台 **“接入 WorkBuddy”**，再到 WorkBuddy 完成原生信任。每次任务明确填写笔记库绝对路径及分类目录。

已有 Git 的用户可执行：

```bash
git clone --branch codex/local-installer-preview --single-branch https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server.git
```

本分支包含 Windows 所需的 `uv.exe`。若仍显示 `Missing required file`，按窗口列出的完整路径检查解压目录；按键只会关闭失败窗口，不会继续安装。详见[安装与恢复](docs/SETUP_FROM_ZIP.md)。

### macOS：当前源码使用开发运行方式

当前远端源码**不附带 Mac uv 二进制**，不能将源码 ZIP 当作完整 Mac 安装包双击 `install.command`。Apple 芯片、macOS 14+ 用户可按下方[开发与打包](#开发与打包)运行当前源码；这需要预先安装 `uv`，并会联网安装 Python 和依赖。新的 0.5 Mac 平台包目前仅为本地构建候选，没有远端下载入口。

### 历史安装包

以下 **0.4.0b3** 平台包保留供历史版本试用，**不包含 0.5 的图文视频、统一视觉 / ASR 路由及 secret 导入功能**：

- [Windows x64 旧包](preview-releases/0.4.0b3/PersonalKB-0.4.0b3-windows-x64.zip?raw=true) · [SHA256](preview-releases/0.4.0b3/PersonalKB-0.4.0b3-windows-x64.zip.sha256)
- [macOS 14+ Apple 芯片旧包](preview-releases/0.4.0b3/PersonalKB-0.4.0b3-macos-arm64.zip?raw=true) · [SHA256](preview-releases/0.4.0b3/PersonalKB-0.4.0b3-macos-arm64.zip.sha256)

旧平台包完整解压后可分别运行 `install.cmd` / `install.command`，其包内说明和行为属于旧版本。没有 Intel Mac 平台包。

安装时不选择笔记库，也不会自动索引笔记。语义检索和视频组件按需要准备；文字整理无需先下载约 2.3 GB 的检索模型。安装器不自动安装 Skill，WorkBuddy 通过 MCP 工具完成业务。

**[从用户视角开始试用](README-FIRST.md)** · [图文视频笔记与统一 AI 设置](docs/video-notes.md) · [安装与恢复](docs/SETUP_FROM_ZIP.md) · [WorkBuddy 接入](docs/workbuddy.md) · [十个 HTTP MCP 工具](docs/HOST_USAGE.md)

## 模型由你选择

| 模式 | 谁负责生成正文 | 使用方式 |
|---|---|---|
| 使用宿主模型 | WorkBuddy 等 MCP 客户端 | 服务准备资料，宿主生成正文；普通文字整理无需额外生成 Key |
| 使用独立模型 | 本机服务调用已配置的模型 | 服务生成、校验并保存笔记，或返回带引用的答案；本地页面也能完成任务 |

独立配置控制知识库内部的生成模型，**不会替换 WorkBuddy 自身的对话模型**。即使正文使用宿主模型，图文视频仍需配置视觉连接；没有可用字幕时还需配置语音识别连接。

| 专属入口 | 默认连接 | 设置中的区别 |
|---|---|---|
| 千问 AI 平台 | 新平台按量 API / Token Plan | 显式选择计费入口，Key 与地址必须配套；旧百炼连接不自动迁移 |
| Kimi | Moonshot 官方兼容接口 | 使用开放平台 Key，不能用 Kimi Code 订阅凭据替代 |
| 智谱 GLM | 智谱官方兼容接口 | 通用 API 与 Coding Plan 端点需按实际账户区分 |
| DeepSeek | DeepSeek 官方兼容接口 | 模型 ID 和权限以账户可用模型为准 |
| 本地 Ollama | 本机 Ollama 原生接口 | 先启动 Ollama 并准备模型；思考能力执行前动态核验 |
| 自定义兼容服务 | 用户填写的 Chat Completions 地址 | 远程地址使用 HTTPS；本机回环地址允许 HTTP |

在 **我的模型 → 添加模型连接** 中添加连接，勾选服务商实际支持的文字、视觉或语音能力，并分别填写型号；勾选能力不会让服务商自动获得该能力。同一连接共用地址与 Key，型号可以不同；纯视觉或纯语音连接可不填文字型号，本机免 Key 服务允许留空。

文字生成设置默认连接，也可分别覆盖笔记整理、知识问答、关联分析；**视觉和语音必须各自选择连接并保存应用，不会跟随默认文字模型**。语音协议支持 DashScope 或 OpenAI 兼容音频接口，应与服务商实际接口一致；Ollama 入口不提供原生 ASR。

保存、测试通过和启用是独立状态。选中“测试能力”后点击“测试已保存能力”：文字测试发送简短请求，视觉测试发送合成图片，语音测试发送静音 WAV，均可能产生 API 费用。测试通过只说明该能力接口响应正常，不证明真实图片理解或转写质量。

模型列表是辅助功能，有些服务不提供列表或单独限制列表权限。获取失败时仍可按服务商文档手动填写模型 ID，保存后测试对应能力；列表可用也不代表每个型号都有调用权限。服务地址应填 **Base URL**，不要填控制台网页或完整的 `/chat/completions` 请求地址。

四家云端预设直接请求对应官方地址，共用连接池与流式传输。“OpenAI 兼容”描述请求格式，不意味着经过 OpenAI 服务器，也不自动限制传输速率。原生接口与兼容接口谁更快需要同条件实测，本版不作速度保证；任务详情显示服务端记录的首事件、首正文、总耗时和用量。

### 千问新平台与旧百炼

0.5.0b3 的千问预设已改为新平台，添加连接时显式选择计费入口：

| 入口 | OpenAI 兼容 Base URL | 凭据 |
|---|---|---|
| 按量 API | `https://maas.qianwenaiapi.com/compatible-mode/v1` | 千问通用 Key，通常为 `sk-ws-`，早期也有 `sk-` |
| Token Plan（个人 / 团队） | `https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1` | 对应订阅的专属 Key，通常为 `sk-sp-` |

两者必须配套，不根据前缀自动选择地址，也不会在失败时切到另一种计费方式。模型填写控制台实际支持的 ID，预填建议不保证账户权限。[新平台 API Key 说明](https://platform.qianwenai.com/docs/api-reference/preparation/api-key) · [个人 / 团队接入地址](https://platform.qianwenai.com/docs/developer-guides/clients-and-developer-tools/chatbox)

**更正旧版指导**：新平台 Token Plan 按兼容 API 协议接入自定义工具，不能套用旧百炼 Coding Plan 的用途说明。[新平台 Token Plan 文档](https://platform.qianwenai.com/docs/token-plan/overview)

旧百炼 `dashscope…aliyuncs.com` 或业务空间地址仍按原配置读取；升级不会改域名或把旧 Key 发送到新平台。迁移时在“我的模型”编辑连接，选择新入口并重新填写匹配的 Key。旧百炼的地域 / 业务空间地址仍以[其官方文档](https://help.aliyun.com/zh/model-studio/base-url)为准。其余预设也已逐项核对：Kimi、GLM、DeepSeek、Ollama 的官方地址仍适用，保持不变。

本版原生 ASR 支持千问通用端点的 `qwen3-asr-flash` 协议；Token Plan 的新 `qwen-audio-3.0-asr-flash` 协议尚未适配，请为语音单独配置本版已支持的服务。这是本项目的适配边界，不表示平台没有语音能力。[当前 ASR 协议](https://platform.qianwenai.com/docs/api-reference/speech-recognition/qwen-asr/api-reference)

### 连接保存在哪里，怎样管理

- **我的模型**集中显示全部已保存连接，包括型号、测试状态和用途。保存后自动回到列表并突出刚保存的连接；保存不会自动测试或启用。
- **添加 / 编辑连接**只填写该连接的地址、Key 和各能力型号。编辑后保存更新同一条连接，不会创建副本。
- 在“我的模型”点击 **配置模型用途**，选择文字生成方式、默认文字连接和任务覆盖；视觉、语音分别选择。点击“保存并应用”后，新任务才使用该配置。
- **使用帮助**提供 Q&A。输入框附近的“填写说明”可直接打开对应问题，返回后继续填写；未保存的草稿仅在当前页面会话中保留，刷新时请留意提示。

这些入口切换独立视图，支持浏览器前进、后退和刷新定位；认证信息与页面位置分开处理。页面不会把 Key 或表单草稿写进链接。

### 模型连接失败时

- 认证或权限失败：核对计费方案、Base URL、地域 / 业务空间、模型 ID 与授权，不能仅凭 Key 前缀判断可用性。
- HTTP `502`、`503`、`504`：分别表示网关响应异常、服务暂不可用或网关超时；实际原因还可能涉及服务端、上游路由或网络代理。状态码不能单独证明 Key 错误，也不能证明兼容协议限制了性能。
- 连接或读取超时：先核对地址及本机网络 / 代理。增大客户端超时不会修复已经由上游返回的 `504`。

从 0.5.0b2 起会在相应错误中保留 HTTP 状态码用于区分问题。反馈时提供出错步骤、脱敏后的地址域名与路径、模型 ID、错误码及文字即可；不要提供 Key、认证请求头或整个数据目录。程序不会自动反复重试模型请求，修改连接后请保存并发起新测试。

### Key 与本机 secret 模板

0.5 本机服务的文字、视觉与 ASR Key 统一存入系统凭据库 `keyring`，配置文件只保存凭据引用，页面不会回填 Key。凭据库不可用时明确失败，不降级为明文保存。

启动会创建空 `secrets.env.example`。可以在设置页直接填写 Key，也可把空模板复制为同目录 `secrets.env`、在本机填写后，选中已保存连接并点击“导入本机填写的 Key”。旧 `data/credentials.json` 中的 DashScope Key 需在 Qwen 连接中显式选择迁移；程序不会启动即迁移。成功写入并回读校验后才清除来源文件的密钥字段，保留其他内容；失败保留原值。导入后仍需分别测试和启用能力。

实际调用时，Key 会发送给所选服务用于认证；任务文字、选中的截图或音频片段会发送至对应服务。本地索引不因此上传整个库。旧 stdio 配置方式仍独立保留，不等同于本机页面的凭据管理。

## 视频怎样变成图文笔记

1. 在工作台准备视频组件，在“模型用途”选好视觉连接；需要无字幕转写时再选 ASR 连接。视频限 **512 MiB、2 小时**，优先采用已有字幕，缺少可用字幕时才调用 ASR。
2. 在“本地任务”选择“整理一段内容为笔记”，填写视频链接或本地视频绝对路径、库路径和保存目录，再选择 **“图文结合”**。默认“纯文字”只整理字幕或转写，不分析截图。
3. 自动有限采样最多 **8 张图**，也可手动输入最多 8 个互不重复的视频内秒数，如 `90, 125.5, 240`。自动采样不保证覆盖全部关键画面；思维导图或逐步展示的 PPT 适合手动补选。
4. 每张图与时间点前后约 **30 秒**讲解交给视觉模型，分清图中事实、讲者说明和不确定内容；再用完整时间轴和逐图证据组织笔记，把图片放在对应解释旁。思维导图重点处理中心主题、层级和分支，箭头不默认等同因果，模糊文字不猜测。
5. 服务端校验图片引用并保存为库内 `Assets/PersonalKB/...` 附件，正文使用 Obsidian 相对引用。新笔记强制 `status: staged`，由你审核后改为 `promoted`。宿主模式的“资料已准备”仅是中间状态，完成正文保存后才有可打开的笔记和附件。

字幕时间与分块 ASR 时间会区分标注；ASR 分块时间只是近似定位。失败重试优先复用已完成的转写、截图和视觉分析检查点；附件或笔记若被用户修改，不会直接覆盖。未完成的模型调用在重试时仍可能产生费用。

在 WorkBuddy 中可以这样说：

```text
把这个视频整理成图文笔记：〈视频链接〉。
笔记库：D:\Obsidian\工作库；保存目录：技术研究/视频。
重点查看第 90、125.5、240 秒的画面，结合前后讲解说明思维导图的层级与分支关系。
标明时间精度和无法确认的内容，先保存为待审核草稿，完成后告诉我笔记路径。
```

对应 MCP 参数是 `video_mode="illustrated"`、`frame_times=[90,125.5,240]`，不指定时为纯文字。Key 和能力路由先在本机页面配置，无需在对话中提供秘密。完整用法见[图文视频指南](docs/video-notes.md)。

## 笔记、任务与恢复

- 新笔记只保存到明确指定的现有库和库内目录，先保持 `staged`。
- 索引需单独授权。本地任务页要求勾选授权并指定包含 / 排除目录；没有 `status` 的旧 Markdown 只有明确选择后才纳入，原文件不修改。
- 每个库分别保存范围与向量数据库；同库重新索引会替换范围。查询目录只能缩小已授权范围。
- 开启自动同步后约每 30 秒检查变化。问答和关联在生成前后、最终交付和历史结果读取时检查来源；来源变化会使旧结果失效，页面清除已展示正文。
- 本地页面使用带认证的 SSE 展示增量内容，生成中内容标明待校验；最终结果以任务接口校验结果为准。宿主是否逐字展示由其客户端决定。
- 任务入队时固定模型配置快照。切换设置只影响新任务；失败不自动换厂商、退回宿主或重试模型调用。
- 手动重试优先复用已持久化的检查点；相同任务不会重复创建相同笔记，也不会覆盖用户已修改的内容。配置调整后想使用新模型，应发起新任务。

安装器用户可双击原入口，或安装目录内的 `Open Personal KB.cmd` / `.command` 重开；开发运行用户重新执行启动命令。后台任务提供继续 / 重试。本版不添加开机自启，安装入口未签名，首次安装需要联网。

## 验证范围与试用边界

| 范围 | 已有证据 | 尚未验证 |
|---|---|---|
| 0.5.0b3 新千问与模型管理 | 完整回归 364 项测试及 18 个子测试、13 项前端测试通过；隔离浏览器验证套餐选择、保存/编辑、用途、帮助往返、前后退/刷新及窄屏深浅主题；合成 Key 验证手填和 secret 导入 | 未调用真实收费模型；用户账户权限与实际网关根因仍待现场确认 |
| 历史 0.5.0b2 诊断 | 受控响应覆盖 HTTP 状态、错误脱敏、无自动重试和模型列表失败后的手填测试；其旧平台套餐指导已由上文更正 | 旧测试不能证明新平台账户可用性 |
| 0.5 图文与统一设置 | 0.5.0b1 整合基线为 312 项测试和 18 个子测试通过；合成媒体经真实 FFmpeg 处理，覆盖时间对齐、真实 PNG 请求格式、附件保存、失败恢复、秘密导入边界和正文引用校验；当时独立结果复核通过 | 测试替身不能证明真实云端模型的理解或转写质量；不代表 Coding Plan 已实测可用 |
| 0.5 页面与服务 | 隔离环境中已用真实浏览器验证桌面 / 手机宽度、深浅主题、能力设置与任务状态；本地候选包完成内容校验和解压服务启动、HTTP MCP 验证 | Windows 桌面双击与视觉、WorkBuddy 原生信任和真实业务；当前提交的自动安装状态见下方 CI |
| 云端与视频平台 | 云端接口具有协议测试，视频下载具有代码与边界测试 | 真实收费视觉 / ASR 调用、线上视频下载、账户权限、费用和性能 |
| 历史版本 | 0.4.0b3 Windows CI 曾验证完整克隆、源码 ZIP、平台 ZIP 的安装与重开；历史 Ollama Qwen3 4B 曾完成真实整理、索引、问答和关联验证 | 历史结果不等于 0.5 完整实机验收 |

当前提交的 Windows 三入口自动安装结果请查看 [Windows installer CI](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/actions/workflows/windows-installer.yml?query=branch%3Acodex%2Flocal-installer-preview)。版本目录尚无平台包时，CI 从受验提交构建临时候选再执行完整安装检查；已有发布目录损坏则直接失败。运行中或失败不能视为通过，CI 也不代表桌面操作或 WorkBuddy 原生验收。

“配置已保存”“收到客户端握手”“业务完成”是三个独立结果。测试客户端握手不能证明 WorkBuddy 已完成原生信任；模型准备成功也不代表用户库已建立索引。

## 开发与打包

在完整的当前分支源码目录执行以下命令。需先安装 `uv`；Mac 支持目标是 Apple 芯片、macOS 14+。示例使用独立开发数据目录，启动不会自动写入 WorkBuddy 配置：

```bash
uv venv --python 3.11.15
uv pip install -e .
uv run --no-sync python -m local_app.server --data-dir "$HOME/Library/Application Support/PersonalKB-Development/data"
```

服务会打开带本机会话的管理页。视频与检索可在页面按需准备，运行时需能在 `PATH` 找到 `uv`；基础文字整理不要求先安装它们。开发运行不会创建安装器的持久启动快捷方式。

需要完整测试依赖时，在同一源码目录执行：

```bash
uv pip install -e '.[legacy,dev,semantic,video]'
uv run --no-sync python -m pytest tests tests_local -q
uv run --no-sync python scripts/build_installer.py --platform windows-x64
```

Windows uv 0.12.12 已按官方归档校验并纳入 Git；构建 Mac 包前需按 `installer/release.json` 获取并校验对应官方归档，将可执行文件放入 `installer/vendor/macos-arm64/`，再运行 `python scripts/build_installer.py --platform macos-arm64`。构建器检查二进制大小、SHA256、必要文件及版本一致性，缺失或不匹配即失败。未具备该组件时不能把源码 ZIP 重命名成 Mac 安装包。

`dist/` 是本地构建输出；本轮不上传新平台包。安装器使用带 SHA256 的依赖锁，语义模型使用固定 revision 与文件清单。生成服务位于 `local_app/models/`，`ModelFactory` 选择厂商适配器，公共服务管理配置、凭据引用、连接池与响应解析。旧四工具 stdio 实现保留，见[旧版说明](docs/LEGACY_STDIO.md)，不等同于本版 HTTP MCP。

## 上游与许可证

基于 [KamisanaAtair / Obsidian-personal-kb-MCP-server](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server)。保留上游署名与 [LICENSE](LICENSE)（PolyForm Noncommercial License 1.0.0，Copyright © 2026 XvAo）。uv 的许可证随包保留。
