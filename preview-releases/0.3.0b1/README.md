# Personal KB 0.3.0b1 试用包

这是独立预览分支中的试用文件，供确认后再合并。没有创建正式 Release。

| 平台 | 安装包 | 校验值 |
|---|---|---|
| Windows x64 | [下载 ZIP](PersonalKB-0.3.0b1-windows-x64.zip?raw=true) | [SHA256](PersonalKB-0.3.0b1-windows-x64.zip.sha256) |
| macOS 14+ Apple 芯片 | [下载 ZIP](PersonalKB-0.3.0b1-macos-arm64.zip?raw=true) | [SHA256](PersonalKB-0.3.0b1-macos-arm64.zip.sha256) |

完整解压后双击 `install.cmd` / `install.command`。在本机网页点击接入 WorkBuddy，再回 WorkBuddy 完成原生信任。安装时不选笔记库、不要求 API Key；使用时在 Prompt 中指定库及分类目录。

[完整试用说明](../../README-FIRST.md)。首次需要联网；本版未签名，不添加开机自启。语义模型约 2.3 GB，按需在后台准备。

已完成 Mac 解压安装、HTTP MCP 调用、文字写入和视频组件验证；回归测试覆盖 93 项及 7 个子测试。Windows 实机、真实 WorkBuddy 信任/热加载、完整 bge-m3 加载检索、真实云 ASR 与大型笔记库性能尚未验证。

两包与上一轮本地交付逐字节一致。此分支的 README 下载入口和历史文档链接经过补充，包内文档仍为打包时的文本；运行代码、锁文件和清单一致。独立 `installer/vendor/`、模型、本地环境、内部报告和验证数据不进入分支。重新构建时按根 README 准备固定版本 uv。
