# Personal KB — 本机安装试用版

把 Obsidian 笔记接入 WorkBuddy。**0.3.0b1** 新增独立本机安装器和 HTTP MCP：安装、下载、索引在用户启动的本机进程执行；整理笔记和答案生成由 WorkBuddy 的模型完成。

## 首次使用

从此预览分支下载对应安装包，完整解压后，双击 `install.cmd` / `install.command`：

- [Windows x64 安装包](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-windows-x64.zip?raw=true) · [SHA256](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-windows-x64.zip.sha256)
- [macOS 14+ Apple 芯片安装包](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-macos-arm64.zip?raw=true) · [SHA256](preview-releases/0.3.0b1/PersonalKB-0.3.0b1-macos-arm64.zip.sha256)

浏览器打开后点击 **安装并接入 WorkBuddy**，再在 WorkBuddy 完成原生信任。安装时不选择笔记库，不要求 API Key。使用时在 Prompt 中说明库的绝对路径及分类目录；每个任务可以选择不同的位置。

**[从用户视角开始试用](README-FIRST.md)** · [安装与恢复](docs/SETUP_FROM_ZIP.md) · [WorkBuddy 接入](docs/workbuddy.md)

试用包存放于本分支的 [preview-releases/0.3.0b1](preview-releases/0.3.0b1/)，未创建 GitHub Release。GitHub 的“Download ZIP”下载的是整个源码分支，根目录未包含 uv 二进制；请使用上面的独立安装包。支持 Windows x64，以及 macOS 14+ Apple 芯片。Intel Mac 暂不支持；Windows 实机、真实 WorkBuddy 信任/重载、完整 bge-m3 下载加载和真实云端 ASR 仍待验证。

两份安装包是上一轮已交付的冻结版本，SHA256 保持不变。本分支额外补充下载入口及历史文档链接；包内说明保留打包时的文本。运行代码、依赖锁及版本清单与分支源码一致，Windows 启动器仅有已声明的 CRLF 换行转换。

## 笔记与检索

- 保存：用户指定现有库和库内目录；生成笔记强制 `status: staged`，人工审核后才可改为 `promoted`。
- 旧笔记：用户明确要求导入时，可将没有 `status` 的既有 Markdown 纳入索引；不改原文件，返回结果区分用户导入与已审核资料。
- 多库：分别保存索引范围和向量数据库；再次指定同库索引范围会替换原范围。
- 同步：约每 30 秒增量检查已授权范围；查询与历史任务交付前检查源文件，删除、修改、降级或超出当前范围的旧片段不返回。
- 等待：模型、索引和视频在后台执行，MCP 返回任务编号。基础文字能力先可用，语义模型约 2.3 GB，可稍后下载。

[HTTP 工具约定](docs/HOST_USAGE.md) 说明九个工具及异步结果。原有四工具 stdio 实现保留，开发者可看 [旧版 stdio 使用说明](docs/LEGACY_STDIO.md)；其依赖安装改为 `pip install -e '.[legacy]'`。

## 开发与打包

```bash
uv venv --python 3.11
uv pip install -e '.[legacy,dev,semantic,video]'
python -m pytest tests tests_local -q
python scripts/build_installer.py
```

打包前需按 `installer/release.json` 下载并校验对应官方 uv 0.12.12 归档，再把可执行文件放入 `installer/vendor/<platform>/`。安装器使用带 SHA256 的依赖锁；语义模型使用固定 revision 和文件校验清单。`dist/` 是构建输出，不提交 Git。

纯基础服务可用 `pip install -e .` 后运行 `personal-kb --data-dir /absolute/path/to/test-data --no-browser`。这条开发命令不自动写 WorkBuddy 配置。

## 上游与许可证

基于 [KamisanaAtair / Obsidian-personal-kb-MCP-server](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server)，本次实现基线为默认分支 `feat/asr-dashscope-api-key` 的 `cabbe3e1369d7e500199d65245c4529d46cd3592`。保留上游署名与 [LICENSE](LICENSE)（PolyForm Noncommercial License 1.0.0，Copyright © 2026 XvAo）。uv 的许可证随包保留。
