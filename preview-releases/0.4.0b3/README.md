# Personal KB 0.4.0b3 — Windows 启动修复候选

包含源码克隆启动组件与打包门禁修复，并使用每次启动标识识别实际服务进程，兼容 Windows Python 启动器的子进程。旧版包保留。

| 平台 | 安装包 | 校验 |
| --- | --- | --- |
| Windows x64 | [下载 ZIP](PersonalKB-0.4.0b3-windows-x64.zip?raw=true) | [SHA256](PersonalKB-0.4.0b3-windows-x64.zip.sha256) |
| macOS 14+ ARM64 | [下载 ZIP](PersonalKB-0.4.0b3-macos-arm64.zip?raw=true) | [SHA256](PersonalKB-0.4.0b3-macos-arm64.zip.sha256) |

完整解压后打开 `install.cmd` 或 `install.command`。Windows 也可完整克隆本分支后运行根目录 `install.cmd`，无需另外准备 uv 或 Python。Mac 源码目录仍不附带 Mac uv，须使用平台安装 ZIP。升级前先从旧页面停止旧服务；共享数据及旧版本保留。

**该目录为候选发布，不代表全部实机验收通过。** Windows 三入口自动化测试的实际提交与运行结果见[修复日志](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/blob/codex/local-installer-preview/project-memory/reports/2026-10-04-windows-installer-fix.md)。Windows 桌面、浏览器视觉和 WorkBuddy 原生操作仍须单独验收。
