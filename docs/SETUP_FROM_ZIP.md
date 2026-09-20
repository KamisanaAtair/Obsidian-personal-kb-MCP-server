# 从 ZIP 开始：把本服务配置到你的 WorkBuddy（零基础指南）

本指南假设你**什么都没装过、什么都不懂**：没碰过命令行、不知道 MCP 是什么、没装过 Python。只要你有一台 Windows / macOS / Linux 电脑和已登录的 WorkBuddy，跟着做就行。

每一步结尾都有"检查点"，确认通过再进行下一步。全文只需要你亲手做 4 件事：**解压、复制一个文件夹、对 WorkBuddy 说一句话、填一串密钥**。其余安装工作由仓库自带的 `personal-kb-mcp-setup` skill 自动完成。

## 这个东西是干什么的

本仓库是一个"私人知识库"服务。配置完成后，你可以在 WorkBuddy 对话里：

- 把文章、视频链接、文本丢给它，它整理成笔记存进你的 Obsidian 库；
- 之后用自然语言问它"我之前存的那篇讲 XX 的笔记说了什么"，它会检索并回答。

WorkBuddy 是"大脑"（对话），本服务是"手脚"（取原文、建索引、写笔记）。两者通过 MCP 协议连接——你不需要理解这句话，照做即可。

## 开始前确认

1. 电脑能上网。
2. WorkBuddy 已安装并登录。
3. （推荐）装了 Obsidian。没装也能用，见文末常见问题第 3 条。

## 第 1 步：下载 ZIP

1. 打开仓库页面：https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server
2. 如果你要用的是某个分支（如果你什么都不知道，下载——> ASR 分支 `feat/asr-dashscope-api-key`喵），先点页面左上角的分支下拉框切换到该分支；用默认分支则跳过。
3. 点绿色的 **Code** 按钮 → 点 **Download ZIP**。
4. 得到一个 `Obsidian-personal-kb-MCP-server...zip` 文件（一般在"下载"文件夹里）。

检查点：下载文件夹里能看到这个 zip 文件。

## 第 2 步：解压到固定位置

解压出来的文件夹名会带一长串分支名，先重命名成短的。

**Windows**

1. 在 D 盘（或 C 盘）新建文件夹 `personal-kb`（路径里**不要有中文和空格**）。
2. 右键下载的 zip → 全部解压 → 解压到 `D:\personal-kb`。
3. 解压出的长名文件夹（如 `Obsidian-personal-kb-MCP-server-feat-asr-dashscope-api-key`）重命名为 `kb`。此后你的仓库路径就是 `D:\personal-kb\kb`。

**macOS**

1. 双击 zip 解压（在"下载"里）。
2. 把解压出的长名文件夹移到个人目录并重命名：之后路径为 `~/personal-kb/kb`（`~` 就是你的家目录）。

**Linux**

```bash
mkdir -p ~/personal-kb && cd ~/personal-kb
unzip ~/Downloads/Obsidian-personal-kb-MCP-server-*.zip
mv Obsidian-personal-kb-MCP-server-* kb
```

检查点：进入这个文件夹，能看到 `README.md`、`pyproject.toml`、`personal-kb-mcp-setup` 文件夹等内容。记住这个路径，下文称为**仓库路径**。

## 第 3 步：把安装 skill 复制进 WorkBuddy

仓库自带一个 `personal-kb-mcp-setup` 文件夹——这是"安装向导"，教 WorkBuddy 自动帮你装好一切依赖、生成配置。要先把它放进 WorkBuddy 的技能目录。

**Windows（纯鼠标操作）**

1. 按 `Win + R`，输入 `%USERPROFILE%\.workbuddy` 回车，打开 WorkBuddy 的数据文件夹。（这是个隐藏文件夹，用这种方式打开最省事。）
2. 如果里面没有 `skills` 文件夹，右键新建一个，命名为 `skills`。
3. 打开 `skills` 文件夹，把仓库里的 `personal-kb-mcp-setup` **整个文件夹**复制进来。
4. 最终应存在这个文件：`C:\Users\你的用户名\.workbuddy\skills\personal-kb-mcp-setup\SKILL.md`

**macOS**

1. Finder 按 `Cmd + Shift + G`，输入 `~/.workbuddy`，回车。
2. 没有 `skills` 文件夹就新建一个，把 `personal-kb-mcp-setup` 整个文件夹复制进去。

或用终端：

```bash
mkdir -p ~/.workbuddy/skills
cp -R ~/personal-kb/kb/personal-kb-mcp-setup ~/.workbuddy/skills/
```

**Linux**

```bash
mkdir -p ~/.workbuddy/skills
cp -R ~/personal-kb/kb/personal-kb-mcp-setup ~/.workbuddy/skills/
```

检查点：`~/.workbuddy/skills/personal-kb-mcp-setup/SKILL.md` 存在。完成后重启 WorkBuddy（或至少新开一个对话）。

## 第 4 步：让 WorkBuddy 自动安装（你只说一句话）

打开 WorkBuddy 对话，把下面这句话复制进去（把路径换成你的仓库路径）：

> 帮我配置并启动 personal-kb MCP server，仓库在 D:\personal-kb\kb

WorkBuddy 会触发 `personal-kb-mcp-setup` skill，自动执行：

- 检查/安装 Python 3.11+、ffmpeg（缺什么装什么，会问你要权限）；
- 在仓库里创建虚拟环境并安装全部 Python 依赖；
- 下载本地检索模型 bge-m3（约 2.2 GB，取决于网速，可能要等一会儿）；
- 生成配置文件 `.env` 和密钥文件 `secrets.env`。

你只需要在 WorkBuddy 需要确认时点允许，等待完成。

检查点：WorkBuddy 给出了一个 `secrets.env` 文件的**完整路径**，并叫你往里面填一串密钥。进行下一步。

## 第 5 步：申请并填写 API Key

这个密钥用于**语音识别**（你丢视频链接给它时，把视频的声音转成文字）。它由阿里云"百炼"平台签发，新用户有免费额度（详见仓库根目录 [ASR 免费政策与定价速查](../ASR_PRICING_AND_FREE_TIER.md)）。

1. 浏览器打开 https://bailian.console.aliyun.com ，注册/登录阿里云账号（可能要求实名认证）。
2. 进入控制台 → 左侧 **API-KEY 管理** → **创建新的 API Key** → 复制生成的那串密钥（形如 `sk-` 开头的一长串字符）。
3. 按 WorkBuddy 给你的方式打开 `secrets.env`（Windows 用记事本、macOS 用 `open`、Linux 用 `xdg-open`，WorkBuddy 会直接告诉你命令）。
4. 找到最后一行 `DASHSCOPE_API_KEY=`，把密钥**直接粘贴在等号后面**（不要加引号、不要有空格），变成 `DASHSCOPE_API_KEY=sk-xxxxxxxx`。
5. 保存文件并关闭。

检查点：打开文件能看到 `DASHSCOPE_API_KEY=` 后面跟了一串 `sk-` 开头的字符。

## 第 6 步：再说一次，这次会直接通过

回到 WorkBuddy，再说一遍：

> 帮我配置并启动 personal-kb MCP server，仓库在 D:\personal-kb\kb

这次 skill 的快速通道检查会全部通过，并告诉你环境就绪。**以后再执行不会再出现安装和填密钥的步骤**，这两件事这辈子（在这台电脑上）只用做一次。

接着让 WorkBuddy 把服务挂载为 MCP 连接器：它会参照 [examples/workbuddy.mcp.json](../examples/workbuddy.mcp.json) 生成适配你电脑路径的配置，写进 WorkBuddy 的 MCP 配置。之后在 WorkBuddy 的连接器/服务器管理里对这个新服务器点**信任**（首次连接必有一次，是正常的安全流程）。

检查点：连接器列表里该服务器显示**已连接**，能看到 `ingest_content_prepare` 等四个工具。

## 第 7 步：验证能用了

对 WorkBuddy 说：

> 使用 personal-kb，把"每周先收集记录，再整理复盘结论"保存为 Obsidian 草稿。先调用 ingest_content_prepare，再按 prompt_for_host 生成完整 Markdown，最后在同一服务实例中调用 ingest_content_finalize；保持 staged，并展示实际 note_path。

如果 WorkBuddy 展示了写入的笔记路径，全部配置完成。

## 常见问题

1. **模型下载（2.2 GB）太慢或中断**：让 WorkBuddy 重新执行下载命令即可，已下载的部分会续用；国内网络默认走魔搭 ModelScope，一般不慢。
2. **装了 ffmpeg 但 WorkBuddy 说找不到**：安装后 PATH 没刷新，重启 WorkBuddy（必要时重启电脑）再试。
3. **没装 Obsidian，能用吗**：能。在 `.env` 里把 `VAULT_ROOT` 指向任意一个空文件夹，笔记会以 Markdown 文件形式写进去；只是没有 Obsidian 的双链和审核界面体验。
4. **WorkBuddy 一直说密钥是 EMPTY**：确认 `secrets.env` 已保存；密钥紧贴等号粘贴，前后无空格无引号；文件位置必须和 WorkBuddy 给的路径一致。
5. **视频转写返回带 STUB 标记的示例内容**：`.env` 里 `VIDEO_TO_TEXT_MCP_ENABLED` 需为 `true`，且 MCP 配置里的同名变量保持一致，改完重连。
6. **换新电脑 / 重装系统**：重走本指南一遍。注意 `secrets.env` 不会随仓库分发（防止密钥泄露），新机器要重新填。
7. **MCP 配置文件在哪**：Windows 为 `C:\Users\你的用户名\.workbuddy\mcp.json`，macOS/Linux 为 `~/.workbuddy/mcp.json`。编辑前先备份。

## 关于安全

`secrets.env` 已被仓库的 `.gitignore` 排除，不会被提交或上传；不要手动把它发给任何人，也不要复制进其他会入库的文件。API Key 泄露请立即去百炼控制台吊销重建。
