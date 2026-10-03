# Personal KB 0.3.0b1 试用包

这是仓库内保留的 0.3.0b1 冻结试用包，没有创建正式 GitHub Release。

| 平台 | 安装包 | 校验值 |
|---|---|---|
| Windows x64 | [下载 ZIP](PersonalKB-0.3.0b1-windows-x64.zip?raw=true) | [SHA256](PersonalKB-0.3.0b1-windows-x64.zip.sha256) |
| macOS 14+ Apple 芯片 | [下载 ZIP](PersonalKB-0.3.0b1-macos-arm64.zip?raw=true) | [SHA256](PersonalKB-0.3.0b1-macos-arm64.zip.sha256) |

完整解压后双击 `install.cmd` / `install.command`。在本机网页点击接入 WorkBuddy，再回 WorkBuddy 完成原生信任。安装时不选笔记库、不要求 API Key；使用时在 Prompt 中指定库及分类目录。

[完整试用说明](../../README-FIRST.md)。首次需要联网；本版未签名，不添加开机自启。语义模型约 2.3 GB，按需在后台准备。

2026-09-28 的隔离验证覆盖 Mac 解压安装、HTTP MCP 调用、文字写入和视频组件。2026-10-03 重新通过 93 项回归测试及 7 个子测试；当天的真实 Mac 首次安装观察确认基础服务就绪、配置保存、完整 bge-m3 下载与本地加载验证、视频组件准备成功，并记录到客户端握手。

客户端身份未被独立确认，握手不能证明笔记业务完成。Windows 实机、WorkBuddy 原生信任 / 热加载 / 原会话续跑、真实笔记库保存与检索、真实云 ASR 和大型库性能仍待验证。

两包与最初交付逐字节一致，SHA256 不变。包内文档仍为打包时文本，请以仓库的 [完整试用说明](../../README-FIRST.md) 为准；运行代码、锁文件和清单一致，Windows 启动器仅作 CRLF 换行转换。独立 `installer/vendor/`、模型、本地环境、内部报告和验证数据不进入分支。重新构建时按 [根 README](../../README.md#开发与打包) 准备固定版本 uv。
