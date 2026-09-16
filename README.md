# Personal KB — host-delegated

把 Obsidian 笔记库接入 MCP Host 的个人知识库服务，版本 **0.2.0**。本版将笔记整理、关联理由和答案生成交给 Host 的对话模型；服务端保留原文获取、本地检索、来源校验和草稿落盘。

“转嫁成本”指服务端不再另行调用生成式 LLM；生成仍消耗 Host 原有额度和上下文，本地 bge-m3、视频 ASR、模型下载和磁盘也仍有成本。本服务不调用 MCP sampling。

## 四个工具

| 工具 | 服务端返回 | Host 下一步 |
|---|---|---|
| `ingest_content_prepare(user_input)` | 原文、`prepare_id`、`prompt_for_host` | 用自身模型生成完整 Markdown |
| `ingest_content_finalize(prepare_id, note_content)` | `note_path` 或 `error` | 告知用户草稿位置，等待人工审核 |
| `trigger_correlation(note_path)` | 候选片段和 `prompt_for_host` | 判断关联理由，直接展示 |
| `query_kb(question)` | 检索片段、`prompt_for_host`、`no_hit_message` | 生成带引用的答案，或展示无命中文案 |

草稿一律写入 `Inbox/`，强制 `status: staged`。用户在 Obsidian 审核并手动改为 `promoted` 后才参与检索；MCP 不提供提升状态的工具。

## 本地启动

克隆 **`codex/host-delegated`** 分支，或解压本版源码包并进入源码目录。需要 **Python 3.11 或更高版本**：

```bash
git clone --branch codex/host-delegated https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server.git
cd Obsidian-personal-kb-MCP-server
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

编辑 `.env`，把 `VAULT_ROOT` 设为实际 Vault 的**绝对路径**，保留 `VAULT_AUTODISCOVER=false`。Windows PowerShell 激活命令为 `.venv/Scripts/Activate.ps1`。

```bash
# 首次使用检索前下载本地 embedding 模型
python scripts/download_embed_model.py

# 查看配置；此命令不加载 embedding 模型
python scripts/debug_run.py status

# stdio MCP 服务，由 Host 启动或用于协议调试
python -m mcp_server.server
```

默认 `VIDEO_TO_TEXT_MCP_ENABLED=false`，视频返回带 STUB 标记的示例转写。真实视频转写须启用此开关并安装 ffmpeg；纯文本摄取不需要启用它。

Host 必须在**同一个服务进程**内完成 prepare → 生成 → finalize；`prepare_id` 默认 60 分钟有效，重启即失效。具体连接参数、交互示例及调试命令见 [Host 使用说明](docs/HOST_USAGE.md)。

WorkBuddy 用户可按 [接入指南](docs/workbuddy.md) 合并 [通用 MCP 配置示例](examples/workbuddy.mcp.json)，其中包含服务 description 和四工具工作约定。示例中的绝对路径须先替换。

## 验证与设计

```bash
pip install pytest pytest-asyncio
python -m pytest -q
```

- [实现结果与验证范围](docs/IMPLEMENTATION_REPORT.md)
- [架构与项目目标](PROJECT_README.md)、[开发上下文](PROJECT_CONTEXT.md)、[目录说明](struct.md)
- [设计决策与计划偏差](docs/DECISIONS.md)

已通过 28 项回归测试、真实 bge-m3 检索和本地合成视频的 Whisper 转写验证。WorkBuddy 已读取本机配置，但原生首次信任及 Host 完整生成循环尚未验证；详细环境和边界见实现报告。

## 上游与许可证

基于 [KamisanaAtair / Obsidian-personal-kb-MCP-server](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server)，改造基线为 `9ebb73669912eb99f2edee27d2aebeebfaf88f6a`。保留上游署名与 [LICENSE](LICENSE)（文件载明 PolyForm Noncommercial License 1.0.0，Copyright © 2026 XvAo）。本次改造称为 **host-delegated**；项目既有“v2”专指未来的图谱感知检索。
