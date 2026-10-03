# WorkBuddy 本机 HTTP 接入（0.4.0b1）

[用户步骤](../README-FIRST.md) · [十个工具约定](HOST_USAGE.md) · [开发与测试日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-03-model-settings-development.md)

双击启动器启动本机服务，WorkBuddy 通过 `http://127.0.0.1:32123/mcp` 连接。安装、索引和独立模型调用在该本机进程执行，WorkBuddy 的 Bash 沙箱不承担安装和长期任务。

## 接入步骤

1. 完整解压 0.4.0b1 平台包并双击安装入口，核对本地页脚版本。
2. 工作台点击 **“接入 WorkBuddy”**。程序向 `~/.workbuddy/mcp.json` 合并 `obsidian-personal-kb-host` 条目，使用 `type: streamableHttp` 和随机 Bearer 凭据。
3. 在 WorkBuddy 连接器管理完成原生信任。若未识别，刷新连接器或重启客户端。
4. 发起明确指定笔记库路径的整理请求，让客户端调用 `ingest_content`；等待任务真正完成后，核对返回文件。

写配置会保留其他条目与顶层字段，重复点击不重复新增；已有文件修改前保留私密备份。非本安装器管理的同名条目不会被覆盖。不要手工清空整个配置文件，也不要公开含 Bearer 的配置。

## 模型设置与宿主的分工

本地页面右上角“设置”可选择 Qwen、Kimi、GLM、DeepSeek、Ollama 和自定义服务。独立模式只决定知识库工具内部使用哪个生成模型，不能替换 WorkBuddy 自身的对话模型。

- **独立模式**：`ingest_content` 生成并保存待审核草稿；问答、关联返回已经生成的答案、引用、实际模型和用量。WorkBuddy 查询 `get_job`，展示结果，不重复生成或调用 finalize 替换正文。
- **宿主模式**：`ingest_content` 准备资料，WorkBuddy 按 `prompt_for_host` 生成并调用 `ingest_content_finalize`；问答与关联也由宿主完成生成。
- **旧入口**：`ingest_content_prepare` 在独立模式拒绝。模式切换不作废有效的旧宿主会话，但独立会话始终禁止宿主替换正文。

不需要把生成模型 Key 发给 WorkBuddy。Key 在本地页面提交到系统凭据库；任务输入只包含业务参数。模型失败不自动回退到 WorkBuddy，也不更换服务商。修改设置只影响新任务。

本地页面能通过带认证的 SSE 显示增量内容和最终校验结果；WorkBuddy 是否逐字呈现工具输出取决于客户端，不能以本地流式显示推定宿主支持。

## 连接状态与验证范围

服务仅监听 `127.0.0.1`，管理页面与 MCP 使用不同凭据，并检查 Host / Origin。页面分别显示配置已保存和客户端已握手；前者不代表已信任。客户端名称来自对方声明，测试客户端也能产生握手记录。

原生信任必须在 WorkBuddy 完成。目标版本的外部配置热加载、信任界面、原会话续跑和真实业务需独立实测。当前 Mac 锁定，Computer Use 与 WorkBuddy 的本轮黑盒验收尚未完成；已有历史握手及协议测试不能替代它们。最新结果见开发日志。

参考：[WorkBuddy 连接器文档](https://open.workbuddy.cn/docs/connector)。`examples/workbuddy.mcp.json` 是旧 stdio 示例，不要与本版安装器维护的 HTTP 配置混用。
