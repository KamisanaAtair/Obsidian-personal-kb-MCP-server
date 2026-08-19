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
# 本地视频文件扩展名（文件系统传入的判别依据）
_VIDEO_FILE_EXTS = (
    ".mp4", ".mkv", ".mov", ".avi", ".webm",
    ".flv", ".ts", ".m4v", ".wmv", ".mpg", ".mpeg", ".3gp",
)
# 从"自然语言 + 链接"混合文本中提取 URL 的正则
# 排除：空白、尖/圆/方括号、引号，以及 CJK 字符与全角标点（\u3000-\u9fff、\uff00-\uffef）
# —— 否则中文逗号/句号会粘连在 URL 尾部
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]\u3000-\u9fff\uff00-\uffef]+", re.IGNORECASE)
# URL 尾部可能粘连的标点（中英文句读）
_URL_TRAILING_PUNCT = ".,;:!?，。；：！？）)】]》》”\""


@dataclass
class TranscriptResult:
    """转写结果。"""

    text: str                       # 纯文本（已合并时间戳片段）
    source: str                     # "cc_subtitle" | "whisper" | "stub"
    srt_path: Optional[str] = None  # 原始 SRT 路径（可选保留）


def extract_video_url(text: str) -> Optional[str]:
    """从"自然语言 + 链接"混合文本中提取视频链接。

    ⚠️ 关键设计前提：用户输入**几乎总是自然语言与链接的组合**
    （如"帮我转写这个视频 https://b23.tv/xxx，重点整理方法论"），
    纯链接输入并不存在。因此不能要求整段文本就是 URL，必须在文本中查找。

    Returns
    -------
    首个命中支持站点的 URL（已去尾部标点）；无则 None。
    """
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(_URL_TRAILING_PUNCT)
        if url and any(h in url.lower() for h in _VIDEO_HOSTS):
            return url
    return None


def extract_video_file(text: str) -> Optional[str]:
    """从混合文本中提取本地视频文件路径（存在且扩展名为视频格式）。

    判别标准（双条件，避免把普通文本里的词误判为文件）：
    1. token 以视频扩展名结尾
    2. 该路径在文件系统上真实存在

    Returns
    -------
    本地视频文件路径；无则 None。
    """
    for token in text.split():
        candidate = token.strip().strip("\"'`").rstrip(_URL_TRAILING_PUNCT)
        if not candidate.lower().endswith(_VIDEO_FILE_EXTS):
            continue
        if Path(candidate).is_file():
            return candidate
    return None


def is_video_url(text: str) -> bool:
    """判别文本中**是否包含**视频链接（支持自然语言+链接的混合输入）。"""
    return extract_video_url(text) is not None


def is_video_file(text: str) -> bool:
    """判别文本中**是否包含**本地视频文件路径。"""
    return extract_video_file(text) is not None


async def transcribe_video(video_ref: str) -> str:
    """把视频（URL 或本地文件路径）转写为纯文本。

    Parameters
    ----------
    video_ref : 视频链接（yt-dlp 支持的站点）或本地视频文件路径。
        为了健壮性：若传入的是"自然语言 + 链接/路径"的混合文本，
        内部会先提取出真正的视频引用（URL 优先，其次本地文件），
        绝不会把整段自然语言当 URL 传给 yt-dlp。

    Returns
    -------
    str : 转写文本（供 Ingestion Agent 进一步结构化为 Obsidian 笔记）
    """
    s = get_settings()

    # 容错提取：混合文本 → 纯引用（URL 优先于本地文件）
    url = extract_video_url(video_ref)
    local = extract_video_file(video_ref)
    if url:
        video_ref = url
    elif local:
        video_ref = local

    if not s.video_to_text_mcp_enabled:
        logger.warning(
            "[video_to_text] STUB 模式（VIDEO_TO_TEXT_MCP_ENABLED=false）。"
            "返回占位文本。在 .env 设为 true 启用真实 yt-dlp + whisper 转写。"
        )
        return _stub_transcript(video_ref)

    result = await _transcribe_real(video_ref, s)
    return result.text


# ---------------------------------------------------------------------------
# 真实实现：三级 fallback（CC 字幕 → Whisper → 失败）
# ---------------------------------------------------------------------------

async def _transcribe_real(video_ref: str, settings: Settings) -> TranscriptResult:
    """真实转写。分两条路径：
    - 本地视频文件：无 CC 字幕可下载，直接 ffmpeg 提音频 → Whisper
    - 视频链接：CC 字幕优先 → Whisper fallback
    """
    is_local = Path(video_ref).is_file()
    if is_local:
        _check_input_exists(video_ref)
    else:
        _check_yt_dlp()

    with tempfile.TemporaryDirectory(prefix="kb_video_") as workdir:
        work = Path(workdir)

        if not is_local:
            # 1a. URL 路径：优先尝试 CC 字幕（无需 ffmpeg）
            result = await _try_cc_subtitles(video_ref, work)
            if result is not None and result.text.strip():
                logger.info("[video_to_text] 命中 CC 字幕（source=%s）", result.source)
                return result
            logger.info("[video_to_text] 无可用 CC 字幕，fallback 到 Whisper 转写")
        else:
            logger.info("[video_to_text] 本地视频文件，直接 Whisper 转写（无 CC 字幕级）")

        # 1b/2. 提取音频 → Whisper 转写（URL 走 yt-dlp，本地文件走 ffmpeg）
        result = await _try_whisper_transcription(video_ref, work, settings)
        if result is not None and result.text.strip():
            logger.info("[video_to_text] Whisper 转写完成（source=%s）", result.source)
            return result

        # 3. 全部失败
        raise RuntimeError(
            f"视频转写失败：既无 CC 字幕，Whisper 也未产出结果。源={video_ref}"
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
    video_source: str, work: Path, settings: Settings
) -> Optional[TranscriptResult]:
    """第 2 级：提取音频 → Whisper 转写。

    video_source 可为视频 URL（yt-dlp 提音频）或本地文件（ffmpeg 直接提音频）。
    """
    if not _has_ffmpeg():
        logger.error(
            "[video_to_text] ffmpeg 不在 PATH，无法提取音频做 Whisper 转写。"
            "请安装 ffmpeg（https://ffmpeg.org）后重试，或仅使用有 CC 字幕的视频。"
        )
        return None

    if Path(video_source).is_file():
        # 本地文件：ffmpeg 直接提取音频（yt-dlp 不适用于本地文件）
        audio_out = str(work / "audio.wav")
        cmd = [
            "ffmpeg", "-y", "-i", video_source,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_out,
        ]
    else:
        # URL：yt-dlp 提取音频
        audio_template = str(work / "audio.%(ext)s")
        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format", "wav",
            "--audio-quality", "0",
            "-o", audio_template,
            "--no-warnings",
            "--no-playlist",
            video_source,
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


def _check_input_exists(video_ref: str) -> None:
    """本地文件输入校验：文件不存在时给出明确错误。"""
    if not Path(video_ref).is_file():
        raise RuntimeError(f"本地视频文件不存在: {video_ref}")


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

def _stub_transcript(video_ref: str) -> str:
    return (
        f"[STUB 视频转写占位输出]\n"
        f"源视频: {video_ref}\n"
        f"（此处应为真实转写文本。在 .env 设置 VIDEO_TO_TEXT_MCP_ENABLED=true，"
        f"并确保 yt-dlp / ffmpeg / faster-whisper 已安装，即可启用真实转写：\n"
        f"  1. 优先下载平台 CC 字幕（zh-Hans/zh-CN/zh/ai-zh）\n"
        f"  2. 无 CC 字幕时提取音频用 Whisper 转写）\n\n"
        f"占位内容：本段为模拟转写，用于验证 Ingestion Agent 的结构化链路是否畅通。"
    )
