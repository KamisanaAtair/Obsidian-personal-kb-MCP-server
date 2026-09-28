---
name: personal-kb-mcp-setup
description: Guide a user to install the local Personal KB trial package and connect its HTTP MCP service to WorkBuddy.
---

# Personal KB 本机安装引导

用户首次安装时，使用对应平台的 Personal KB 安装包。不要通过 WorkBuddy 的 Bash 或安全沙箱下载依赖、模型、运行安装脚本或启动 stdio 子进程。

1. 引导用户完整解压已提供的安装包，Windows 双击 install.cmd，macOS 14+ Apple 芯片双击 install.command。没有安装包时说明需要实际安装包，不把 GitHub 自动源码 ZIP 冒充可运行安装器，也不编造 Release 下载地址。
2. 本机网页打开后，用户点击“安装并接入 WorkBuddy”，由安装器合并配置；不要在聊天里生成真实认证令牌。
3. 用户在 WorkBuddy 原生界面完成信任。未加载时刷新连接器或重启 WorkBuddy；不改信任记录。
4. 连接成功后使用 get_status 确认实际状态，并继续用户原来的业务请求。

安装时不选择笔记库，不强制模型、视频依赖或 API Key。业务 Prompt 明确指定绝对库路径和库内分类目录，每个任务独立。缺少路径时只询问缺失路径，不要求重新安装。

保存新笔记必须保持 staged。导入原有笔记需明确范围及是否纳入无 status 的旧笔记，不能因用户保存一个文件就扫描整个库。异步任务返回编号后可查询进度，未完成不宣称成功。模型下载可以在本机后台继续，基础文字功能可以先使用。
