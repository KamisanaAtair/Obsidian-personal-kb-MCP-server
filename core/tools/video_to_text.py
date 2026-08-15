"""视频转文档工具 —— 独立实现（参考 bilibili-render-pdf skill 三级 fallback 方法论）。

方法论来源与边界
----------------
bilibili-render-pdf 是一个 WorkBuddy skill（仅 WorkBuddy Host 可用）。本系统目标是
多 Host（Codex / Claude Code / WorkBuddy 等）通用，**不能假设 Host 自带该 skill**。
因此参考其"视频→文本"部分的三级 fallback 方法论，在本模块独立实现：

    1. 优先下载平台 CC 字幕（zh-Hans / zh-CN / zh / ai-zh）
    2. 无 CC 字幕时，提取音频 → Whisper 转写
    3. 音质过差时纯视觉抽帧 —— 超出 MVP 范围，本期不实现

原 skill 的 LaTeX/PDF 渲染部分**不适用**（需求产出 Obsidian Markdown 笔记，非 PDF），
故只取转写能力。

依赖
----
- yt-dlp（字幕下载 / 音频提取）
- ffmpeg（yt-dlp 音频提取后端，需系统安装并在 PATH）—— 缺失时仅 CC 字幕路径可用
- faster-whisper（默认，轻量）或 openai-whisper（精度高、依赖 torch）

切换开关：.env VIDEO_TO_TEXT_MCP_ENABLED=true 启用真实实现，false 走 stub。
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# CC 字幕语言优先级（参考 skill：手动 > 自动，简体 > 繁体 > 通用）
_SUBTITLE_LANGS = "zh-Hans,zh-CN,zh,ai-zh,zh-Hant,en,en-US,en-GB"
# 支持的视频站点关键字（快速判别视频链接）
_VIDEO_HOSTS = ("bilibili.com", "b23.tv", "youtube.com", "youtu.be", "v.qq.com")


@dataclass
class TranscriptResult:
    """转写结果。"""

    text: str                       # 纯文本（已合并时间戳片段）
    source: str                     # "cc_subtitle" | "whisper" | "stub"
    srt_path: Optional[str] = None  # 原始 SRT 路径（可选保留）


def is_video_url(text: str) -> bool:
    """快速判别是否为视频链接。"""
    lowered = text.strip().lower()
    return lowered.startswith(("http://", "https://")) and any(h in lowered for h in _VIDEO_HOSTS)


async def transcribe_video(video_url: str) -> str:
    """把视频链接转写为纯文本。

    Parameters
    ----------
    video_url : 视频链接（Bilibili / YouTube 等 yt-dlp 支持的站点）

    Returns
    -------
    str : 转写文本（供 Ingestion Agent 进一步结构化为 Obsidian 笔记）
    """
    s = get_settings()

    if not s.video_to_text_mcp_enabled:
        logger.warning(
            "[video_to_text] STUB 模式（VIDEO_TO_TEXT_MCP_ENABLED=false）。"
            "返回占位文本。在 .env 设为 true 启用真实 yt-dlp + whisper 转写。"
        )
        return _stub_transcript(video_url)

    result = await _transcribe_real(video_url, s)
    return result.text


# ---------------------------------------------------------------------------
# 真实实现：三级 fallback（CC 字幕 → Whisper → 失败）
# ---------------------------------------------------------------------------

async def _transcribe_real(video_url: str, settings: Settings) -> TranscriptResult:
    """真实转写：CC 字幕优先 → Whisper fallback。"""
    _check_yt_dlp()

    with tempfile.TemporaryDirectory(prefix="kb_video_") as workdir:
        work = Path(workdir)

        # 1. 优先尝试 CC 字幕（无需 ffmpeg）
        result = await _try_cc_subtitles(video_url, work)
        if result is not None and result.text.strip():
            logger.info("[video_to_text] 命中 CC 字幕（source=%s）", result.source)
            return result

        # 2. fallback：提取音频 → Whisper 转写（需 ffmpeg）
        logger.info("[video_to_text] 无可用 CC 字幕，fallback 到 Whisper 转写")
        result = await _try_whisper_transcription(video_url, work, settings)
        if result is not None and result.text.strip():
            logger.info("[video_to_text] Whisper 转写完成（source=%s）", result.source)
            return result

        # 3. 全部失败
        raise RuntimeError(
            f"视频转写失败：既无 CC 字幕，Whisper 也未产出结果。URL={video_url}"
        )


async def _try_cc_subtitles(video_url: str, work: Path) -> Optional[TranscriptResult]:
    """第 1 级：下载平台 CC 字幕。"""
    out_template = str(work / "%(title)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "--write-subs",
        "--write-auto-subs",          # 也尝试自动生成的字幕
        "--sub-langs", _SUBTITLE_LANGS,
        "--convert-subs", "srt",
        "--skip-download",
        "--no-warnings",
        "--no-playlist",              # 仅处理单 P（分 P 由上层决定）
        "-o", out_template,
        video_url,
    ]
    logger.debug("[video_to_text] 下载 CC 字幕: %s", " ".join(cmd))
    await _run_async(cmd)

    srt_files = sorted(work.glob("*.srt"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not srt_files:
        logger.info("[video_to_text] 未下载到 CC 字幕")
        return None

    srt_path = srt_files[0]
    raw = srt_path.read_text(encoding="utf-8", errors="ignore")
    text = _srt_to_text(raw)
    if not text.strip():
        return None
    return TranscriptResult(text=text, source="cc_subtitle", srt_path=str(srt_path))


async def _try_whisper_transcription(
    video_url: str, work: Path, settings: Settings
) -> Optional[TranscriptResult]:
    """第 2 级：提取音频 → Whisper 转写。"""
    if not _has_ffmpeg():
        logger.error(
            "[video_to_text] ffmpeg 不在 PATH，无法提取音频做 Whisper 转写。"
            "请安装 ffmpeg（https://ffmpeg.org）后重试，或仅使用有 CC 字幕的视频。"
        )
        return None

    audio_template = str(work / "audio.%(ext)s")
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", audio_template,
        "--no-warnings",
        "--no-playlist",
        video_url,
    ]
    logger.debug("[video_to_text] 提取音频: %s", " ".join(cmd))
    await _run_async(cmd)

    audio_files = list(work.glob("audio.*"))
    if not audio_files:
        logger.warning("[video_to_text] 音频提取失败")
        return None
    audio_file = audio_files[0]

    # Whisper 转写（在线程池跑，避免阻塞事件循环）
    srt_text = await asyncio.to_thread(
        _whisper_transcribe, str(audio_file), str(work), settings
    )
    if not srt_text.strip():
        return None

    srt_path = work / "whisper.srt"
    srt_path.write_text(srt_text, encoding="utf-8")
    text = _srt_to_text(srt_text)
    return TranscriptResult(text=text, source="whisper", srt_path=str(srt_path))


def _whisper_transcribe(audio_path: str, out_dir: str, settings: Settings) -> str:
    """同步 Whisper 转写 → SRT 字符串。"""
    if settings.whisper_backend == "openai-whisper":
        return _whisper_openai(audio_path, settings)
    return _whisper_faster(audio_path, settings)


def _whisper_faster(audio_path: str, settings: Settings) -> str:
    """faster-whisper 转写（默认，轻量，无需完整 torch）。"""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper 未安装。pip install faster-whisper，"
            "或在 .env 切换 WHISPER_BACKEND=openai-whisper。"
        ) from e

    logger.info("[whisper] faster-whisper 加载模型 %s (device=%s, compute=%s) ...",
                settings.whisper_model, settings.whisper_device, settings.whisper_compute_type)
    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    segments, info = model.transcribe(
        audio_path,
        language=settings.whisper_language,
        vad_filter=True,
        beam_size=5,
    )
    logger.info("[whisper] 检测语言=%s 概率=%.2f", info.language, info.language_probability)

    lines, idx = [], 1
    for seg in segments:
        lines.append(_format_srt_block(idx, seg.start, seg.end, seg.text.strip()))
        idx += 1
    return "\n".join(lines)


def _whisper_openai(audio_path: str, settings: Settings) -> str:
    """openai-whisper 转写（精度高但依赖 torch，较重）。"""
    try:
        import whisper  # type: ignore  # openai-whisper
    except ImportError as e:
        raise RuntimeError(
            "openai-whisper 未安装。pip install openai-whisper，"
            "或在 .env 切换 WHISPER_BACKEND=faster-whisper。"
        ) from e

    logger.info("[whisper] openai-whisper 加载模型 %s ...", settings.whisper_model)
    model = whisper.load_model(settings.whisper_model, device=settings.whisper_device)
    result = model.transcribe(
        audio_path, language=settings.whisper_language, task="transcribe"
    )
    lines, idx = [], 1
    for seg in result.get("segments", []):
        lines.append(_format_srt_block(idx, seg["start"], seg["end"], seg["text"].strip()))
        idx += 1
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SRT 解析与格式化
# ---------------------------------------------------------------------------

def _srt_to_text(srt_content: str) -> str:
    """把 SRT 字幕转为可读纯文本（去时间戳、去序号、合并连续片段）。"""
    lines = srt_content.splitlines()
    text_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->", line):
            continue
        text_parts.append(line)
    return " ".join(text_parts)


def _format_srt_block(index: int, start: float, end: float, text: str) -> str:
    """格式化单个 SRT 片段。"""
    return (
        f"{index}\n"
        f"{_seconds_to_srt_time(start)} --> {_seconds_to_srt_time(end)}\n"
        f"{text}\n"
    )


def _seconds_to_srt_time(seconds: float) -> str:
    """秒数 → SRT 时间码 HH:MM:SS,mmm。"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------

def _check_yt_dlp() -> None:
    if not shutil.which("yt-dlp"):
        raise RuntimeError(
            "yt-dlp 不在 PATH。pip install yt-dlp 后重试。"
        )


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def _run_async(cmd: list[str]) -> subprocess.CompletedProcess:
    """异步执行命令，捕获输出。失败时记日志但不立即抛出（由调用方判断结果）。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.debug(
            "[video_to_text] 命令返回码 %d: %s\nstderr: %s",
            proc.returncode, " ".join(cmd), stderr.decode(errors="ignore")[:500],
        )
    return subprocess.CompletedProcess(
        args=cmd, returncode=proc.returncode or 0,
        stdout=stdout.decode(errors="ignore"), stderr=stderr.decode(errors="ignore"),
    )


# ---------------------------------------------------------------------------
# Stub（占位，用于无依赖环境调试）
# ---------------------------------------------------------------------------

def _stub_transcript(video_url: str) -> str:
    return (
        f"[STUB 视频转写占位输出]\n"
        f"源视频: {video_url}\n"
        f"（此处应为真实转写文本。在 .env 设置 VIDEO_TO_TEXT_MCP_ENABLED=true，"
        f"并确保 yt-dlp / ffmpeg / faster-whisper 已安装，即可启用真实转写：\n"
        f"  1. 优先下载平台 CC 字幕（zh-Hans/zh-CN/zh/ai-zh）\n"
        f"  2. 无 CC 字幕时提取音频用 Whisper 转写）\n\n"
        f"占位内容：本段为模拟转写，用于验证 Ingestion Agent 的结构化链路是否畅通。"
    )
