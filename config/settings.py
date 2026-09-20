"""host-delegated 配置：生成工作交给 Host，本服务保留本地检索和转写。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，从 .env 文件与环境变量加载。"""

    # env_file 列表：后面的文件优先级更高。
    # secrets.env 集中存放 API Key 等敏感凭据（已 gitignore，维护在私密库），
    # 克隆/部署后放回项目根目录即可生效；不存在时自动跳过，不影响启动。
    model_config = SettingsConfigDict(
        env_file=(".env", "secrets.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 本地 Embedding（生成工作由 Host 执行）----
    embed_provider: Literal["local"] = "local"
    embed_model_name: str = "BAAI/bge-m3"
    embed_model_source: Literal["modelscope", "huggingface"] = "modelscope"
    embed_model_cache_dir: str = "models/bge-m3"  # 本地缓存目录（相对于项目根）
    embed_device: str = "cpu"                      # cpu | cuda

    # ---- Obsidian Vault ----
    # vault_root 仅作 fallback：默认空，优先动态解析（见 vault_path property）。
    # 遵循 obsidian skill 规范 "Avoid hardcoded vault paths; prefer print-default / obsidian.json"。
    # 生产环境：装了 Obsidian 桌面端即可自动发现，无需手动设；无 Obsidian 时在 .env 设 VAULT_ROOT。
    vault_root: str = Field(
        default="",
        description="Obsidian 本地笔记库根目录。留空则动态解析（obsidian-cli/obsidian.json）；仅作 fallback。",
    )
    vault_autodiscover: bool = Field(
        default=True,
        description="是否动态解析 vault 路径（obsidian-cli print-default / obsidian.json open:true）。"
        "测试或强制指定路径时设 false。",
    )
    vault_inbox_dir: str = Field(
        default="Inbox",
        description="staged 草稿笔记落地目录，便于人工找到待审队列",
    )
    note_status_field: str = Field(
        default="status",
        description="frontmatter 状态字段名，取值 staged / promoted",
    )

    # ---- RAG / 向量库 ----
    chroma_persist_dir: str = ".chroma_db"
    rag_collection_name: str = "kb_notes"
    rag_top_k: int = 6                       # 检索时返回rag top k个文档块

    correlation_top_k: int = 5
    correlation_min_score: float = 0.35

    # ---- 混合检索（BM25 + 向量 + RRF 融合）----
    # BM25 稀疏检索擅长精确关键词/术语/ID 匹配，向量 Dense 检索擅长语义相似，
    # 两者互补。通过 RRF（Reciprocal Rank Fusion）融合排名，k=60 为业界经验常数。
    hybrid_search_enabled: bool = True       # 关闭则退回纯向量检索
    hybrid_bm25_weight: float = 0.5          # BM25 路权重（0=纯向量, 1=纯BM25, 0.5=等权）
    hybrid_rrf_k: int = 60                   # RRF 平滑常数（越大各排名差异越小）
    hybrid_candidate_multiplier: int = 3     # 每路取 top_k×multiplier 候选再融合截断

    # ---- 视频转文档（独立实现，参考 bilibili-render-pdf skill 三级 fallback 方法论）----
    # 注意：本系统不依赖任何 Host 的 skill；此处参考其"yt-dlp CC 字幕 → Whisper 转写"
    # 方法论在 core/tools/video_to_text.py 独立实现，产出纯文本（非 PDF）。
    # ENABLED=false 时走 stub（用于无 ffmpeg/网络环境调试）。
    video_to_text_mcp_enabled: bool = False  # 命名保留兼容；实际控制视频转写真实/stub

    # ---- 阿里百炼（DashScope）云端 ASR：替代本地 Whisper ----
    # 背景：本地 faster-whisper medium (CPU) 转写 30 分钟音频实测需 32.4 分钟，
    # 远超 MCP 同步请求超时；改用云端 qwen-audio-3.0-asr-flash（选型调研见
    # ASR_PRICING_AND_FREE_TIER.md）。
    dashscope_api_key: str = ""                        # 阿里百炼 API Key（DASHSCOPE_API_KEY）
    dashscope_asr_model: str = "qwen-audio-3.0-asr-flash"
    dashscope_asr_format: str = "wav"                  # 音频格式（与 ffmpeg/yt-dlp 提取输出一致）
    dashscope_asr_sample_rate: int = 16000             # 采样率（Hz）

    # [已停用 2026-09-20] 本地 Whisper 转写配置 —— 已改用上方阿里百炼 ASR。
    # 如需回退本地转写：取消下方注释，并恢复 core/tools/video_to_text.py 中
    # _whisper_transcribe / _whisper_faster / _whisper_openai 及其调用点。
    # whisper_backend: Literal["faster-whisper", "openai-whisper"] = "faster-whisper"
    # whisper_model: str = "medium"          # faster-whisper/openai-whisper 模型规格
    # whisper_language: str = "zh"           # 转写语言
    # whisper_device: str = "cpu"            # cpu | cuda
    # whisper_compute_type: str = "int8"     # int8(cpu) | float16(gpu) | float32

    # ---- 确定性路径/URL 识别 ----
    # 歧义候选由 needs_review 标记；服务端不调用模型消歧。
    path_recognizer_confidence_threshold: float = 0.7

    # ---- prepare/finalize 进程内会话 ----
    ingest_session_ttl_minutes: int = Field(default=60, ge=1)

    # ---- Obsidian 整理（参考 obsidian-official-cli + yakitrak obsidian-cli）----
    # 本系统不依赖 Host 的 obsidian skill；在 core/tools/obsidian_cli.py 独立封装 CLI 适配层。
    # 优先用官方 CLI（obs，需 Obsidian 1.12+ 运行），其次 yakitrak CLI（obsidian-cli），
    # 都不可用则 fallback 文件系统。⚠️ yakitrak 的 create/move 也依赖 Obsidian 桌面端（obsidian:// URI），
    # 真正不依赖 Obsidian 的兜底只有文件系统；yakitrak 的 print-default/search/list 才独立于 Obsidian 运行。
    # ENABLED=true 时尝试用 CLI 落地（自动更新双链等）。
    obsidian_skill_enabled: bool = False   # 命名保留兼容；实际控制是否尝试用 CLI 落地

    # ---- 日志 ----
    log_level: str = "INFO"

    # ---- 派生属性 ----
    @property
    def vault_path(self) -> Path:
        """Vault 根路径。

        解析顺序（遵循 obsidian skill：不硬编码）：
        1. vault_autodiscover=true 时，先动态解析（obsidian-cli print-default → obsidian.json open:true）
        2. .env 显式配置的 vault_root（fallback）
        3. 都失败返回空 Path（后续 mkdir 会暴露配置缺失）

        测试 / 强制指定路径：设 vault_autodiscover=false + vault_root=... 绕过动态解析，
        保证测试隔离（避免读到真实 Obsidian vault）。
        """
        if self.vault_autodiscover:
            from core.tools.vault_resolver import resolve_vault_path

            resolved = resolve_vault_path()
            if resolved is not None:
                return resolved
        if self.vault_root.strip():
            return Path(self.vault_root)
        # 都失败：返回空 Path，调用方 mkdir/read 时会自然报错暴露配置问题
        return Path(self.vault_root)

    @property
    def inbox_path(self) -> Path:
        return self.vault_path / self.vault_inbox_dir

    @property
    def chroma_path(self) -> Path:
        return Path(self.chroma_persist_dir)

    @property
    def embed_cache_path(self) -> Path:
        """Embedding 模型本地缓存目录的绝对路径。"""
        p = Path(self.embed_model_cache_dir)
        return p if p.is_absolute() else Path.cwd() / p

    @property
    def is_stub_mode(self) -> bool:
        """视频使用 stub 且 Obsidian CLI 未启用；与 Host 的生成能力无关。"""
        return not self.video_to_text_mcp_enabled and not self.obsidian_skill_enabled


@lru_cache
def get_settings() -> Settings:
    """获取单例配置（整个应用共享一份）。"""
    return Settings()
