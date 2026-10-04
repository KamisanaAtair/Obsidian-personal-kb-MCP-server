# Windows 启动入口修复与验证

日期：2026-10-04（Asia/Shanghai）。目标分支：`codex/local-installer-preview`。

最新结论：`0.4.0b3` 已推送至指定分支，代码提交 `718cbade172e139377c55a9e5f8144457a5ea4a3` 的三入口 Windows 自动化安装与服务验证全部通过；源码缺少启动组件及后续 Windows 服务身份误判均已修复。详细证据见本文末尾。Windows 桌面视觉及 WorkBuddy 原生验收仍未完成。

## 问题与已确认的证据

用户从源码克隆后运行 `install.cmd`，反复收到 `Installation archive is incomplete`。原提交 `b82099ec950154d0d596c9c49db9d24ad9f40f78` 的脚本必须找到 `installer/vendor/windows-x64/uv.exe`，但 `.gitignore` 排除了整个 vendor，Git 树中没有这个文件。因此该提交的源码克隆和源码 ZIP 无法从此入口启动。

重新下载同提交的实际 Windows 平台 ZIP，SHA256 为 `4860a52634747e693d1eba24672853aab03ac1dc94cc10b31c51da5cf3302d2e`，CRC 检查通过，且包含正确的 uv.exe。因此没有证据证明旧平台 ZIP 本身漏文件；用户机器实际运行目录没有远程观察。此前只让用户重新解压未解决源码入口缺陷。

另一个发布缺陷是打包脚本只枚举现有文件：缺少 vendor 时仍可产出 ZIP，缺少必要输入的失败门禁。

## 修复范围

- 版本升级为 `0.4.0b2`，旧版安装包保持原样。
- 精确将 Windows `uv.exe` 纳入 Git，使 Windows 克隆与源码 ZIP 的根目录 `install.cmd` 具有所需启动组件。其他平台 vendor 仍作为本地打包输入。
- 新提示列出缺失文件的完整路径，并说明按键只结束失败窗口；分别检查 uv.exe 与 bootstrap.py。
- 构建前检查所有所选平台的必要文件、版本一致性、二进制大小和 SHA256，拒绝链接。所有平台预检完成后才构建，临时产物通过检查后再发布到输出目录。
- 新增 Windows GitHub Actions：干净克隆、源码 archive、实际候选平台 ZIP 三条路径；真实执行 cmd、内置 uv、私有 Python、基础依赖安装与服务启动。认证页面、MCP 和持久启动入口另外检查。
- 所有 CI 安装使用合成临时目录，不注册 WorkBuddy、不调用云模型、不处理用户笔记、不输出凭据。

## 第三方二进制来源

均在本次重新下载官方 uv `0.12.12` 归档，核对 `installer/release.json` 中已有的归档 SHA256，并逐字节对比本地可执行文件。

| 平台 | 可执行文件字节数 | 可执行文件 SHA256 |
| --- | ---: | --- |
| Windows x64 | 41455408 | `efb9599543b26b3ea5adc1649bef69788633d9cc25c6cfd97b799e4dfa0c2cfb` |
| macOS ARM64 | 36498272 | `53cf843c2eed12d1cafdaab7a1ba95e53496f7df280fc2be4fa8f3d7c32a1496` |

来源与 MIT / Apache 许可证保留在 `installer/third_party/`。可执行文件哈希不代表 Windows 业务验收，实际执行结果另记。

## 审议及交付阶段

独立中书方案已由门下 `APPROVE_PLAN`。审议明确允许：先完成本地验证和独立限定结果审议，普通推送待验证候选，以触发 Windows CI；在 Windows 实际通过之前不得宣称 Windows 安装已验证。

本节记录最初的候选准备阶段；当时 Windows CI 尚未运行。后续实际命令结果、提交与 run URL 依次补记于下文。

## 验证边界

Windows 执行器上的真实安装、服务及协议测试不能替代用户 Windows 桌面双击、浏览器视觉或 WorkBuddy 原生信任和业务验收。此前整体开发任务的 Computer Use / WorkBuddy 待验项继续保留，不因本次修复而消失。云模型真实账户及 Windows 可选语义/视频组件也不属于本次基础启动检查。

## 候选推送前本地验证

- 完整回归：`python -m pytest tests tests_local -q`，190 项测试、7 个子测试通过（19.92 秒）。
- 新增 14 项打包检查，包含缺失、同大小篡改、错误清单、版本冲突、链接、跨平台预检及失败保留已有产物。
- 前后对照：在同一合成临时源码树中删去 uv，原 b82099e 构建器仍生成 ZIP；新构建器拒绝且不创建输出目录。
- 新增及修改的 Python 文件通过限定 Ruff 和语法检查。Windows 驱动尚未在本机执行，本机为 macOS。
- 已从完整受控输入生成两份新候选 ZIP；构建阶段校验 uv SHA256 和 ZIP CRC。

| 包 | 字节数 | SHA256 |
| --- | ---: | --- |
| `PersonalKB-0.4.0b2-windows-x64.zip` | 17571340 | `8171a17918643023983b62b9bea39ce19cdaef0d99199279d3cf7944addb33e0` |
| `PersonalKB-0.4.0b2-macos-arm64.zip` | 16846127 | `e92e70e889b68dfa01bb674ee5f95e553aaa5925a32824d9a08c7dc8a9bf068e` |

本表是候选文件完整性证据；Windows 安装通过须等实际 Actions 运行。

## 首轮 Windows 实测：未通过，继续修复

候选提交 `8f2fc337bf619da9020ed3d49e7dfb4172519998` 经独立限定 `APPROVE_RESULT` 后普通推送。按该提交重新下载远端 install.cmd、Windows uv 和两份 ZIP，均与已审候选一致。

[首轮 Windows CI](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/actions/runs/37173906647) 三个入口均通过启动文件与 uv 版本检查、缺文件报错负例、真实 Python 3.11.15 与基础依赖安装；均在服务启动就绪判断处失败，不能作为安装成功交付。

原启动器强制要求 `service.json.pid == Popen.pid`。官方 [CPython 3.11.15 Windows 启动器](https://github.com/python/cpython/blob/v3.11.15/PC/launcher.c#L767) 会创建并等待子进程，支持 PID 不同的根因假设；下一轮实际运行时 PID 探针继续验证，不将文档推断冒充实测。

首轮 CI 清理状态存在证据缺口：进程已经退出也被记为 `authenticated_shutdown: PASS`，因此不能据此声称真正执行过认证退出或当时服务健康。测试现明确区分 `AUTHENTICATED_SHUTDOWN`、`ALREADY_EXITED`、`NOT_STARTED`，完整成功必须实际认证关闭并确认服务进程退出。

## 0.4.0b3 增量候选

独立增量方案已获 `APPROVE_PLAN`。每次真正启动生成新的 `launch_id`，只放进该子进程的环境副本；服务记录和 health 必须同时匹配本次标识，并保留 PID 存活、端口、实例、版本和 payload 校验。已有服务复用保持原启动身份。该标识不替代 UI/MCP 认证，也没有放宽回环边界、增加超时或修改 Windows JobObject 标志。

新增检查覆盖不同 launcher/interpreter PID、旧或缺失启动标识、其他身份不一致、环境不被修改和已运行服务复用。HTTP 实测验证启动标识记录及原认证隔离。Windows CI 加入实际 PID 探针，并要求 cmd/uv 退出后服务继续提供页面与 MCP。

本地完整回归：193 项测试、18 个子测试通过（18.69 秒）。修复期间曾因复用测试 fixture 的参数变化出现 7 个 setup 错误，已保持原接口并完整重跑，相关失败记录留在本地验证目录；不影响旧候选结果的如实保留。

| 新包 | 字节数 | SHA256 |
| --- | ---: | --- |
| `PersonalKB-0.4.0b3-windows-x64.zip` | 17571636 | `3f27fa70ad88a2b518329bcb07311f3da91f8532d86012b9eac566ecdad53670` |
| `PersonalKB-0.4.0b3-macos-arm64.zip` | 16846423 | `1555f5e4588f8fe969f5a37c96754167f1d14a6b0d7c6180fdc5edee90f1a151` |

0.4.0b2 候选及原哈希保留，0.4.0b3 的真实 Windows 结果如下。

## 第二轮 Windows 实测：三个入口全部通过

独立增量结果审议批准候选推送后，代码提交 `718cbade172e139377c55a9e5f8144457a5ea4a3` 已普通推送至指定分支。[Windows CI 37174858885](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/actions/runs/37174858885) 在 2026-10-04 完成，三个 Windows Server 2022 作业均为 `success`。各作业均真实运行 `install.cmd`，使用含中文和空格的独立临时源码及安装目录。

| 输入方式 | 安装及服务 | 运行时启动器 PID → 实际解释器 PID | MCP 与退出 |
| --- | --- | --- | --- |
| 指定提交的干净克隆 | PASS | 6952 → 956 | PASS |
| 指定提交的源码 ZIP | PASS | 3004 → 544 | PASS |
| 仓库中的实际 Windows 平台 ZIP | PASS | 1104 → 7004 | PASS |

三个实际 PID 探针均确认：解释器 PID 不同于启动器 PID，解释器的父 PID 等于启动器 PID，探针退出码为 0。该证据支持本次改用每次启动标识识别服务的修复；不再仅凭官方源码推断 Windows 进程行为。

每个入口均通过以下检查：

- 启动文件及官方 uv 完整性，缺失 uv / bootstrap 时的失败提示。
- 真实准备私有 Python `3.11.15` 及锁定的基础依赖；`--prepare-only` 不启动服务。
- `install.cmd --no-browser` 成功返回，服务 health、版本、实例、payload 与本次启动标识匹配。
- 页面静态资源及 HTTP 认证隔离；安装后 MCP SDK 列出全部 10 个工具，并成功调用 `get_status`。未把列出工具视为十项业务均已执行。
- 移走原始源码目录后，持久启动入口仍能打开并复用相同服务 PID、实例及启动标识。
- 实际认证关闭服务并确认进程退出，结果明确为 `AUTHENTICATED_SHUTDOWN`，没有用已退出状态替代成功。

三个作业的 `passed` 均为 `true`。浏览器自动打开、桌面视觉与真实 WorkBuddy 原生操作未执行，仍为待验证；本次结论限定于 Windows 安装、后台服务和已列明的协议检查。

## 远端交付与证据范围

已按完整代码提交 SHA 重新下载 GitHub 上的 `installer/bootstrap.py`、`local_app/server.py` 及两份 `0.4.0b3` ZIP，字节与本地审议产物一致；两包大小、SHA256 与上表一致。每份 ZIP 的 70 个源码/文档文件与提交树匹配（cmd 统一 CRLF），剩余 uv 文件与已验证的官方二进制匹配，ZIP CRC 通过。候选文本扫描未发现秘密；二进制来源由官方精确哈希和包内容核对支持，不把文本扫描称为完整二进制安全检测。

此次后续提交仅补记本报告，安装源码、CI 和安装包保持已通过的 `718cbad` 内容。未修改默认分支，未创建 Release，未覆盖旧版包。历史内部报告、私有项目记忆、原始 CI 日志及合成安装数据不纳入上传。

用户可[直接下载 Windows 0.4.0b3 ZIP](https://github.com/KamisanaAtair/Obsidian-personal-kb-MCP-server/raw/refs/heads/codex/local-installer-preview/preview-releases/0.4.0b3/PersonalKB-0.4.0b3-windows-x64.zip)，完整解压后运行 `install.cmd`；源码克隆须指定 `codex/local-installer-preview` 分支。首次安装仍需要联网下载私有 Python 和基础依赖。
