# Personal KB 0.4.0b1 候选试用包

本版增加独立模型配置、六类服务入口、黑紫/白紫页面与本地生成任务。默认保留宿主生成模式；独立配置不会更换 WorkBuddy 自身的对话模型。

| 平台 | 安装包 | 校验值 |
|---|---|---|
| Windows x64 | [下载 ZIP](PersonalKB-0.4.0b1-windows-x64.zip?raw=true) | [SHA256](PersonalKB-0.4.0b1-windows-x64.zip.sha256) |
| macOS 14+ Apple 芯片 | [下载 ZIP](PersonalKB-0.4.0b1-macos-arm64.zip?raw=true) | [SHA256](PersonalKB-0.4.0b1-macos-arm64.zip.sha256) |

完整解压后打开 `install.cmd` 或 `install.command`。升级前先在旧页面“维护与退出”中停止旧服务。旧版目录与共享数据保留；重新准备检索/视频组件时可复用本机缓存。

当前 176 项自动化测试及 7 个子测试通过。真实 Ollama Qwen3 4B 与 bge-m3 的整理、索引、问答、关联通过 16 项语义及保存检查。已知旧 Qwen3 模板的“关闭思考”会明确拒绝，需选默认或开启，不会自动更换设置或截断正文。

**候选包尚未完成整体验收。** Computer Use 页面操作和 WorkBuddy 原生信任/业务仍缺实机证据；Windows、四家云端账户、真实云 ASR 和大型库性能也未验证。配置保存、HTTP 握手和真实客户端业务是不同结果。

详见[本轮工作日志](../../project-memory/reports/2026-10-03-model-settings-development.md)和[使用指南](../../README-FIRST.md)。安装需要联网，未签名、不开机自启；本目录不是 GitHub Release，历史 0.3.0b1 包保持原样。
