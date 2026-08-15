"""内部工具集（不对外暴露）。

⚠️ 工具粒度边界（需求第5节、术语表）：这些是原子操作，仅 core 内部节点调用，
MCP Server 层绝不直接包装暴露给 Host——避免 Host 绕过编排顺序与信任闸门。

- llm.py            : LLM 工厂（Ollama / API 占位符）
- video_to_text.py  : 视频转文本（yt-dlp CC 字幕 + whisper 三级 fallback，参考 bilibili-render-pdf skill 方法论独立实现）
- obsidian_skill.py : 笔记格式化（LLM 优先，占位符时基础包装 fallback；产出 Obsidian Markdown）
- obsidian_cli.py   : Obsidian CLI 适配层（官方 obs / yakitrak obsidian-cli / 文件系统 三级 fallback）
- vault_io.py       : 笔记读写 + status 管理（仅内部；改 status 不暴露给 MCP，信任闸门）
- retriever.py      : RAG 检索（仅 status=promoted，metadata 物理隔离）
"""
