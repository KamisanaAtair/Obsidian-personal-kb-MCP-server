---
name: personal-kb-mcp-setup
description: "personal-kb-multiagent（Obsidian-personal-kb-MCP-server）MCP 服务首次执行前的强制前置安装流程。This skill should be used whenever the user asks to start, connect, configure, test, or first-use the personal-kb / obsidian-personal-kb-host MCP server, or before any action that would launch its server process, including adding it to MCP config or invoking its tools for the first time. It checks and installs all Python and system dependencies, creates .env and secrets.env, and guides the user to fill in the DashScope ASR API key (qwen-audio-3.0-asr-flash). All steps are idempotent: completed checks are skipped on re-run."
agent_created: true
---

# personal-kb MCP 服务首次运行前置安装

本 skill 是 `personal-kb-multiagent` MCP server（stdio 传输，入口 `python -m mcp_server.server`）**首次执行前的强制前置步骤**。任何会启动、连接或首次使用该 MCP server 的请求，都必须先走完本流程的检查，全部通过后才放行执行。即使未出现明显触发词，只要操作对象是该 MCP server 的首次执行，也必须先执行本 skill。

**项目根定位**：本 skill 位于 `<repo-root>/personal-kb-mcp-setup/`（仓库根目录），项目根即 SKILL.md 上一级目录。若当前工作区不是该仓库，先向用户确认仓库绝对路径，再继续。

## 0. 快速通道（每次先做，幂等）

逐项检查以下 6 个完成标记，**全部通过则直接放行 MCP server 执行**，并告知用户：环境此前已就绪，本次及以后执行不会再出现安装与配置步骤。

| # | 完成标记 | 检查方式（在项目根执行） |
|---|---|---|
| 1 | Python ≥ 3.11 存在 | `python --version`（Windows 可用 `py -3 --version`；macOS/Linux 用 `python3 --version`） |
| 2 | 虚拟环境 + Python 包齐全 | `.venv` 目录存在，且 venv 内 python 执行 §2 的导入自检通过 |
| 3 | `.env` 存在 | 项目根存在 `.env` 文件 |
| 4 | embedding 模型已缓存 | `models/bge-m3/` 下存在模型文件（如 `model.safetensors` / `pytorch_model.bin` / `config.json`） |
| 5 | `secrets.env` 存在且密钥非空 | §4 的密钥加载自检输出 `OK` |
| 6 | ffmpeg 可用 | `ffmpeg -version` 成功（CC 字幕路径可无 ffmpeg，但音频转写必须） |

任一项不通过 → 进入对应章节补装/补配，完成后回到本节复核。

## 1. 全量依赖清单

以下为该项目**全部依赖**，逐项检查，缺失即安装：

**A. 运行时（系统级）**

| 依赖 | 版本要求 | 用途 | 检查 | 安装（按检测到的 OS 选择） |
|---|---|---|---|---|
| Python | ≥ 3.11 | 运行服务 | `python --version` | Windows：`winget install Python.Python.3.11` 或官网安装包；macOS：`brew install python@3.11`；Linux(Debian/Ubuntu)：`sudo apt install python3.11 python3.11-venv` |
| ffmpeg / ffprobe | 任意新版 | 提取/分段音频（ASR 前置） | `ffmpeg -version` | Windows：`winget install Gyan.FFmpeg`；macOS：`brew install ffmpeg`；Linux(Debian/Ubuntu)：`sudo apt install ffmpeg`；Fedora：`sudo dnf install ffmpeg`；Arch：`sudo pacman -S ffmpeg` |
| git | 任意 | 克隆/更新仓库 | `git --version` | 各发行版包管理器或 https://git-scm.com |

**B. Python 包（pyproject.toml 声明，共 20 个，全部经 `pip install -e .` 一次装齐）**

| 包 | 用途 |
|---|---|
| langgraph ≥0.2.50 | Agent 图编排 |
| langchain ≥0.3.0 / langchain-core ≥0.3.0 | LangChain 基础 |
| chromadb ≥0.5.0 | 本地向量库 |
| langchain-chroma ≥0.1.4 | Chroma 适配 |
| langchain-text-splitters ≥0.2.0 | Markdown/递归切分 |
| rank-bm25 ≥0.2.2 | BM25 稀疏检索 |
| jieba ≥0.42.1 | 中文分词（BM25） |
| langchain-huggingface ≥0.1.0 | HuggingFaceEmbeddings 适配 |
| sentence-transformers ≥2.7.0 | 本地 bge-m3 推理 |
| modelscope ≥1.18.0 | 模型下载（魔搭，国内友好） |
| mcp ≥1.0.0,<2.0.0 | MCP server 框架（FastMCP） |
| yt-dlp ≥2024.8.6 | 字幕下载/音频提取 |
| faster-whisper ≥1.0.3 | 本地 Whisper（已停用，仍为声明依赖） |
| pydantic ≥2.7.0 / pydantic-settings ≥2.3.0 | 配置加载（含 secrets.env） |
| python-dotenv ≥1.0.0 | .env 加载 |
| pyyaml ≥6.0 | YAML 解析 |
| rich ≥13.7.0 / typer ≥0.12.0 | CLI 与输出 |

检查（§0 第 2 项的导入自检，在项目根执行；`<py>` 为 venv 解释器）：

```bash
# Windows: <py> = .venv\Scripts\python.exe   macOS/Linux: <py> = .venv/bin/python
<py> -c "import langgraph, langchain, langchain_core, chromadb, langchain_chroma, langchain_text_splitters, rank_bm25, jieba, langchain_huggingface, sentence_transformers, modelscope, mcp, yt_dlp, faster_whisper, pydantic, pydantic_settings, dotenv, yaml, rich, typer; print('OK')"
```

安装（venv 不存在或导入失败时；幂等，可重复执行）：

```bash
python -m venv .venv          # Windows 下 python 换成 py -3
<py> -m pip install -e .      # 装齐上表全部 20 个包
```

可选（跑测试才需要）：`<py> -m pip install -e '.[dev]'`

**C. 本地 embedding 模型（bge-m3，约 2.2 GB）**

- 检查：`models/bge-m3/` 非空（见 §0 第 4 项）
- 下载：`<py> scripts/download_embed_model.py`（默认从魔搭 ModelScope 下载）

**D. 配置文件 `.env`**

- 检查：项目根存在 `.env`
- 生成：复制 `.env.example` 为 `.env`，并按用户实际情况设置：
  - `VAULT_ROOT`：用户 Obsidian Vault 绝对路径（`VAULT_AUTODISCOVER=false` 时生效）
  - `VIDEO_TO_TEXT_MCP_ENABLED=true`（默认 false 是 STUB 模式；要启用真实语音转写必须设 true）

## 2. 系统识别（生成 secret 文件前必做）

检测用户操作系统，后续路径写法与"打开文件"指引按 OS 输出：

- **Windows**：`$OSTYPE` 含 `msys`/`cygwin`，或 `ver` 命令存在 → 路径形如 `C:\...\secrets.env`
- **macOS**：`uname -s` 输出 `Darwin` → 路径形如 `/Users/<user>/.../secrets.env`
- **Linux**：`uname -s` 输出 `Linux` → 路径形如 `/home/<user>/.../secrets.env`

## 3. 生成 secret 文件 `secrets.env`

该文件存放**语音识别模型**（阿里百炼 DashScope `qwen-audio-3.0-asr-flash`，用于视频转写，见 `core/tools/video_to_text.py`）的 API Key。`config/settings.py` 通过 `env_file=(".env", "secrets.env")` 自动加载，项目已 gitignore，不会入库。

若项目根不存在 `secrets.env`，则创建，内容固定为：

```dotenv
# 阿里百炼（DashScope）语音识别 API Key
# 用途：qwen-audio-3.0-asr-flash 视频转写（core/tools/video_to_text.py）
# 获取：登录阿里云百炼控制台 https://bailian.console.aliyun.com → API-KEY 管理 → 创建
# ⚠️ 本文件已 gitignore，请勿提交到仓库或外传
DASHSCOPE_API_KEY=
```

注意：`DASHSCOPE_API_KEY` 留空，**不要**替用户猜测或编造任何密钥值。

## 4. 指引用户填写 API Key（密钥为空时）

若 `secrets.env` 中 `DASHSCOPE_API_KEY` 为空值（快速通道第 5 项检查命令，在项目根执行）：

```bash
<py> -c "from config.settings import get_settings; k=get_settings().dashscope_api_key; print('OK' if k else 'EMPTY')"
```

输出 `EMPTY` 时，向用户输出以下内容后**停止本次流程**（不继续启动 MCP server）：

1. **打印 secrets.env 的绝对路径**（按 §2 识别的 OS 给出对应写法）。
2. **指引用户在本地打开该文件**，按 OS 给出命令：
   - Windows：`notepad "C:\...\Obsidian-personal-kb-MCP-server\secrets.env"`（或资源管理器中定位后用记事本打开）
   - macOS：`open /Users/<user>/.../secrets.env`
   - Linux：`xdg-open /home/<user>/.../secrets.env`（无图形环境时建议 `nano`/`vim` 或任意编辑器）
3. **指引用户获取并填写密钥**：登录 https://bailian.console.aliyun.com → API-KEY 管理 → 创建 API Key → 粘贴到 `DASHSCOPE_API_KEY=` 等号之后 → 保存文件。
4. **请用户再次执行**（重新触发本 skill / 重试原请求），届时会重新校验密钥。
5. **明确告知**：以上依赖安装与密钥配置步骤只需这一次；以后执行本 skill 会命中快速通道（§0）直接通过，不会再出现这些步骤。

## 5. 完成放行

当 §0 快速通道 6 项全部通过：

1. 告知用户环境就绪，列出本次实际补装/补配的项（无则说明"此前已全部就绪"）。
2. 放行 MCP server 执行。启动方式（Host 直连配置参考 `examples/workbuddy.mcp.json`）：
   - Windows：`.venv\Scripts\python.exe -m mcp_server.server`（cwd = 项目根）
   - macOS/Linux：`.venv/bin/python -m mcp_server.server`（cwd = 项目根）
3. 再次确认：以后执行不会再出现安装与密钥配置步骤。

## 边界

- 不修改 `pyproject.toml`、不改服务代码；只做安装、生成配置与指引用户。
- 不读取、不回显用户填入后的完整密钥值（校验只输出 OK / EMPTY）。
- `secrets.env` 是唯一存放该密钥的位置；不要把密钥写进 `.env`、MCP 配置或任何会入库的文件。
