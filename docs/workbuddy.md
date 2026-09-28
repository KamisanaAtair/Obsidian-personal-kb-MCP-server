# WorkBuddy 本机 HTTP 接入

[用户步骤](../README-FIRST.md)。本版由用户双击启动器启动独立服务，WorkBuddy 通过 `http://127.0.0.1:32123/mcp` 连接。WorkBuddy 的 Bash 沙箱不承担安装和长期计算。

浏览器中的接入按钮向 `~/.workbuddy/mcp.json` 合并一个 `obsidian-personal-kb-host` 条目，使用 `type: streamableHttp` 和随机 Bearer 凭据。保留其他条目和顶层字段，重复点击不重复新增；已有文件修改前保留私密备份。

只监听 `127.0.0.1`，管理页面与 MCP 使用不同凭据，并检查 Host / Origin。不要把凭据粘贴到聊天或公开配置。页面的“已保存”与“已收到客户端握手”分别显示，前者不代表已信任。握手不区分任意测试客户端与 WorkBuddy，页面会显示客户端声明的名称。

原生信任始终由用户在 WorkBuddy 完成。官方文档支持 Streamable HTTP 连接配置，但目标版本的外部文件热加载、信任弹窗与原会话续跑需要实机验证。若未识别，刷新连接器或重启 WorkBuddy。

参考：[连接器文档](https://open.workbuddy.cn/docs/connector)。旧的 stdio 配置示例位于 `examples/workbuddy.mcp.json`，不要与本版安装器配置混用。
