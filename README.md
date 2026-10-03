# Personal KB — 本机安装试用版

把 Obsidian 笔记接入 WorkBuddy。**0.3.0b1** 新增独立本机安装器和 HTTP MCP：安装、下载、索引在用户启动的本机进程执行；整理笔记和答案生成由 WorkBuddy 的模型完成。

## 首次使用

下载适合你电脑的独立安装包：

- [Windows x64 安装包](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-windows-x64.zip?raw=true) · [SHA256](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-windows-x64.zip.sha256)
- [macOS 14+ Apple 芯片安装包](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-macos-arm64.zip?raw=true) · [SHA256](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-macos-arm64.zip.sha256)

1. **先完整解压 ZIP**。Windows 在资源管理器选择“全部解压”；Mac 在 Finder 双击 ZIP，进入解压后的文件夹。
2. **双击启动**：Windows 打开 `install.cmd`，Mac 打开 `install.command`。终端自动准备私有 Python 和基础依赖，然后打开本机浏览器界面；无需预装 Python、Git 或手动输入命令。
3. **点击“安装并接入 WorkBuddy”**：程序备份并合并 MCP 连接配置，保留其他连接器。回到 WorkBuddy 完成原生“信任”；未出现连接器时刷新或重启 WorkBuddy。
4. **发送第一条业务消息**：在 Prompt 中说明已有笔记库的绝对路径和分类目录，再提供待整理内容。WorkBuddy 生成笔记，调用本机 MCP 保存草稿。

安装时不选择笔记库、不要求 API Key；每个任务可以使用不同的库和目录。基础文字能力先可用，语义检索、视频组件按需在后台准备，无需向 WorkBuddy 发送两轮安装指令，也不需要它在沙箱里执行安装脚本。安装器不会自动安装 Skill；接入后的日常操作通过 MCP 工具完成。

**[从用户视角开始试用](README-FIRST.md)** · [安装与恢复](docs/SETUP_FROM_ZIP.md) · [WorkBuddy 接入](docs/workbuddy.md)

安装包保存在仓库的 [preview-releases/0.3.0b1](preview-releases/0.3.0b1/)，尚未创建 GitHub Release。**请使用上面的独立安装包**；GitHub 的“Code → Download ZIP”下载的是源码，根目录不包含启动所需的 uv 二进制。

支持 Windows x64 和 macOS 14+ Apple 芯片，暂不支持 Intel Mac。试用包未签名、首次需要联网，不设置开机自启。退出服务或重启电脑后，双击安装入口或安装目录内的 `Open Personal KB.cmd` / `.command` 重新打开；可选功能中断后可在网页“后台任务”中继续 / 重试。

## 笔记与检索

- 保存：用户指定现有库和库内目录；生成笔记强制 `status: staged`，人工审核后才可改为 `promoted`。
- 旧笔记：用户明确要求导入时，可将没有 `status` 的既有 Markdown 纳入索引；不改原文件，返回结果区分用户导入与已审核资料。
- 多库：分别保存索引范围和向量数据库；再次指定同库索引范围会替换原范围。
- 同步：约每 30 秒增量检查已授权范围；查询与历史任务交付前检查源文件，删除、修改、降级或超出当前范围的旧片段不返回。
- 等待：模型、索引和视频在后台执行，MCP 返回任务编号。基础文字能力先可用，语义模型约 2.3 GB，可稍后下载。

[HTTP 工具约定](docs/HOST_USAGE.md) 说明九个工具及异步结果。原有四工具 stdio 实现保留，开发者可看 [旧版 stdio 使用说明](docs/LEGACY_STDIO.md)；其依赖安装改为 `pip install -e '.[legacy]'`。

## 验证范围与试用边界

| 范围 | 已有证据 | 仍需验证 |
|---|---|---|
| Mac 首次安装（2026-10-03） | Apple 芯片 Mac 上基础服务就绪、连接配置保存；bge-m3 下载及本地加载验证完成，视频组件准备成功 | Windows 实机安装、其他系统环境 |
| 客户端接入（2026-10-03） | 观察到客户端初始化握手 | 客户端身份未被独立确认；WorkBuddy 原生信任界面、热加载与原会话续跑仍需实测 |
| 功能回归（2026-10-03） | 93 项测试及 7 个子测试重新通过；2026-09-28 已在隔离环境验证 HTTP MCP、文字写入及视频组件 | 真实笔记库保存与检索闭环、真实云端 ASR、大型库性能 |

“配置已保存”“收到客户端握手”“笔记业务完成”是三个独立结果。模型准备成功也不代表已为你的库建立索引；导入原笔记前仍需明确库及收录范围。下载时间取决于网络和缓存，后台任务也可能排队。

两份 ZIP 保留 0.3.0b1 最初交付时的文件和 SHA256，没有重新打包。仓库说明已更新，包内文档可能较旧，请以本 README 和 [首次使用说明](README-FIRST.md) 为准。运行代码、依赖锁及版本清单一致；Windows 启动器在打包时转换为 CRLF 换行。

## 开发与打包

```bash
uv venv --python 3.11
uv pip install -e '.[legacy,dev,semantic,video]'
uv run --no-sync python -m pytest tests tests_local -q
uv run --no-sync python scripts/build_installer.py
```

打包前需按 `installer/release.json` 下载并校验对应官方 uv 0.12.12 归档，再把可执行文件放入 `installer/vendor/<platform>/`。安装器使用带 SHA256 的依赖锁；语义模型使用固定 revision 和文件校验清单。`dist/` 是构建输出，不提交 Git。

纯基础服务可用 `pip install -e .` 后运行 `personal-kb --data-dir /absolute/path/to/test-data --no-browser`。这条开发命令不自动写 WorkBuddy 配置。

## 上游与许可证

基于 [KamisanaAtair / Obsidian-personal-kb-MCP-server](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server)，本次实现基线为默认分支 `feat/asr-dashscope-api-key` 的 `cabbe3e1369d7e500199d65245c4529d46cd3592`。保留上游署名与 [LICENSE](LICENSE)（PolyForm Noncommercial License 1.0.0，Copyright © 2026 XvAo）。uv 的许可证随包保留。
