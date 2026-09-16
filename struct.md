# 目录说明

```text
Obsidian-personal-kb-MCP-server/
├── README.md                       # 安装与入口
├── PROJECT_README.md               # 项目目标与架构
├── PROJECT_CONTEXT.md              # 当前开发上下文
├── docs/
│   ├── HOST_USAGE.md               # stdio 连接、工具契约、Host 交互和调试
│   ├── DECISIONS.md                # 决策与计划偏差
│   └── IMPLEMENTATION_REPORT.md    # 实际实现、测试结果及未验证项
├── pyproject.toml                  # Python >=3.11，包版本 0.2.0
├── .env.example                    # Vault、本地模型、会话 TTL 配置
├── langgraph.json                  # 四个图入口
├── config/
│   ├── settings.py                 # 无服务端生成 LLM 配置
│   └── prompts.py                  # 六个保留的模板，格式化后返回 Host
├── core/
│   ├── state.py                    # KBState：包括 prepare_id、candidates、error
│   ├── graph.py                    # 导出四个子图
│   ├── nodes/
│   │   ├── ingestion.py           # prepare 获取原文 / finalize 校验落盘
│   │   ├── correlation.py         # promoted 目标的候选检索
│   │   └── retrieval_qa.py        # promoted 片段及回答 prompt
│   ├── subgraphs/
│   │   ├── ingestion_prepare_graph.py
│   │   ├── ingestion_finalize_graph.py
│   │   ├── correlation_graph.py
│   │   └── retrieval_graph.py
│   └── tools/
│       ├── session_store.py        # UUID 来源配对，内存会话 + TTL
│       ├── obsidian_skill.py       # YAML 校验、来源补全、强制 staged
│       ├── vault_io.py             # Vault 读写及信任闸门
│       ├── obsidian_cli.py         # 可选 CLI 适配，文件系统 fallback
│       ├── vault_resolver.py       # 可选 Vault 路径发现
│       ├── embeddings.py           # 本地 bge-m3 模型下载/加载
│       ├── retriever.py            # promoted 索引维护及检索
│       ├── hybrid_search.py        # BM25 + 向量 + RRF
│       ├── path_url_recognizer.py  # 确定性路径与 URL 识别
│       └── video_to_text.py        # 保留上游视频转写模块
├── mcp_server/
│   └── server.py                   # 四个 FastMCP 工具，stdio
├── scripts/
│   ├── debug_run.py                # ingest/prepare/correlate/query/index/status
│   └── download_embed_model.py     # 保留上游 embedding 下载脚本
├── tests/                          # host-delegated 契约和业务行为验证
└── LICENSE                         # 保留上游许可证
```

运行时可生成 `.venv/`、模型缓存和 `.chroma_db/`，这些不是源码。Vault 由 `.env` 的 `VAULT_ROOT` 指定；摄取会话只保存在内存，不生成会话数据库。
