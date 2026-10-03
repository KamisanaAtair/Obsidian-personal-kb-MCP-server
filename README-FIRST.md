# Personal KB 0.4.0b1 试用指南

这一版可以继续使用 WorkBuddy 的模型，也能在本地页面选择自己的生成模型。界面默认黑紫，可用右上角按钮切换白紫。当前验收进展与限制见 [开发日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-03-model-settings-development.md)。

## 安装并打开

1. 从 [README 下载入口](README.md#首次使用) 取得 0.4.0b1 平台包。Windows 需要 x64，Mac 需要 Apple 芯片及 macOS 14 或以上；不支持 Intel Mac。
2. 完整解压 ZIP，双击 `install.cmd`（Windows）或 `install.command`（Mac）。首次会联网准备私有 Python 和依赖，无需预装 Python、Git 或手动输入命令。
3. 自动打开“Personal KB · 你的本机知识库”。工作台显示连接与组件状态；安装阶段不会选择或扫描笔记库。

旧 0.3 安装包仍保留，但没有新的模型设置页面。重新打开时可检查页脚版本；若仍显示旧版，请先停止旧服务，再使用 0.4.0b1 入口启动。

## 选择自己的模型

1. 点击右上角 **“设置”**，在“添加模型连接”选择 Qwen、Kimi、GLM、DeepSeek、本地 Ollama 或自定义服务。
2. 填写连接名称、API 地址和自己的 Key。云端预设默认直连官方地址；Qwen 可选择服务地域。Ollama 需要先在本机运行并准备模型。
3. 可以直接填写模型 ID，也可先保存连接，再点击 **“获取列表”**。从列表选择模型后要再次保存。
4. 点击 **“测试已保存连接”**。测试会发送一条简短请求，可能产生少量 API 费用；测试通过不会自动启用这个连接。
5. 在“生成方式”选择 **“使用独立模型”**，指定默认连接并点击 **“保存并应用”**。也可以分别指定笔记整理、知识问答和关联分析使用的连接。

页面分别显示已保存、测试结果、是否启用。更换配置只影响新任务，运行中的任务固定使用原配置；失败会明确提示，不自动切换厂商或退回宿主。选择“使用宿主模型”则继续由 WorkBuddy 生成，无需额外生成 Key。

生成模型 Key 保存在系统凭据库，页面不回填；编辑时留空会保留原 Key。系统凭据库不可用时不会转存明文。不同服务商、地域或域名需要匹配的 Key，不要将 Key 发到聊天中。独立生成会把任务原文或检索片段发送到所选服务。

## 先整理一条笔记

在 **“本地任务”** 选择“整理一段内容为笔记”，填写：

- 笔记库绝对路径，例如 `/Users/你的用户名/Documents/工作库` 或 `D:\Obsidian\工作库`；该库需已存在。
- 保存目录，例如 `技术研究/RAG`，可留空；不存在的库内目录会被创建。
- 想整理的原文，例如“增量索引只处理新增、修改和删除的文件，减少重复计算”。

启用独立模型后点击“开始整理”，结果区域显示进度、正文、实际模型和保存路径。生成中的内容仍待最终校验。完成后在 Obsidian 打开返回的文件：新笔记强制标为 `staged`，人工审核后才可改为 `promoted`。文字整理无需先准备检索或视频组件。

宿主模式下，本地页面只准备资料和生成提示，不会自行保存最终生成笔记；请到 WorkBuddy 继续。

## 在 WorkBuddy 中使用

1. 在工作台点击 **“接入 WorkBuddy”**。程序备份并合并自身连接条目，保留其他 MCP。
2. 回到 WorkBuddy 的连接器管理，找到 `obsidian-personal-kb-host`，完成原生信任。未出现时刷新连接器或重启 WorkBuddy。
3. 发送一条明确指定路径的业务消息：

```text
把下面内容整理成一篇 Obsidian 笔记。
笔记库绝对路径：D:\Obsidian\工作库
分类目录：技术研究\RAG
内容：增量索引只处理新增、修改和删除的文件，减少重复计算。
使用 ingest_content 完成任务，等待实际结果后告诉我保存路径。
```

`ingest_content` 自动遵循当前生成方式。独立模式返回任务编号，WorkBuddy 查询 `get_job` 后展示已生成草稿；宿主模式返回提示，由 WorkBuddy 生成并调用 `ingest_content_finalize`。独立配置不会改变 WorkBuddy 自身的对话模型。配置保存、握手和笔记保存要分别确认。

## 导入笔记、提问和关联

先在工作台准备语义检索组件；下载的模型约 2.3 GB，另需运行依赖。准备好不会自动建立任何笔记库索引。

在“本地任务”选择 **“建立或更新检索索引”**，填写库路径、包含 / 排除目录，并明确勾选授权。是否纳入无 `status` 的旧 Markdown、是否以后自动同步均由你选择。也可以向 WorkBuddy 明确提出相同范围要求。

同库重新指定范围会替换旧范围；原文件不修改。`staged`、无效元数据、隐藏文件和链接目录不收录。无状态旧笔记只有明确纳入后才检索，结果会区分它们与已审核资料。

随后可在本地页或 WorkBuddy 中提问、分析已 `promoted` 笔记的关联。独立模式直接返回答案、引用和实际模型信息；宿主模式返回供宿主生成的资料。查询目录只能缩小当前授权范围。原笔记删除、修改、降级或范围变化后，旧结果会失效，需重新发起任务。

## 重开、恢复与视频

- 重开：双击安装入口，或安装目录内的 `Open Personal KB.cmd` / `.command`。此版不添加开机启动项。
- 下载或任务中断：从工作台“后台任务”查看并继续 / 重试。模型不会自动重试；手动重试可能增加费用。已保存的生成检查点会优先复用，笔记保存按任务去重。
- 视频：按需准备组件，有字幕时优先使用字幕。云端音频识别另需 DashScope Key，音频会发送至该服务。**视频 Key 当前仍保存在本机 `data/credentials.json`，不使用新增的系统凭据库。**
- 数据目录：Windows `%LOCALAPPDATA%\PersonalKB`；Mac `~/Library/Application Support/PersonalKB`。任务、配置、模型和索引在 `data` 子目录；生成模型秘密由系统凭据库保存。
- 停止服务：展开页面“维护与退出”，点击停止。

本版为未签名、需联网的候选试用包。当前真实 Ollama 模型调用已有证据；完整业务、Computer Use / WorkBuddy 黑盒、Windows 实机及四家云端真实账户仍有待验项，不能以协议测试或历史握手代替。请查看 [README 验证范围](README.md#验证范围与试用边界) 和 [持续更新的工作日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-03-model-settings-development.md)。
