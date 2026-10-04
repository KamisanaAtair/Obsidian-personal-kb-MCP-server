"""Bounded video evidence preparation; model calls and notebook writes live elsewhere.

Every job owns a frozen media copy. Checkpoints refer to that copy, never to a
temporary directory or a subsequently changed source. Automatic frames are a
small visual sample, not a claim that every important scene was found.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from urllib.parse import urlsplit

from .models import ModelError
from .workspaces import is_link

MAX_VIDEO_BYTES = 512 * 1024 * 1024
MAX_DURATION = 2 * 60 * 60
MAX_SUBTITLE_BYTES = 2 * 1024 * 1024
MAX_PNG_BYTES = 4 * 1024 * 1024
MAX_IMAGE_SIDE = 1600
MAX_FRAMES = 8
ASR_CHUNK_SECONDS = 30
MEDIA_FORMATS = "mov,matroska,webm,avi,mpegts,mpeg,mpegvideo,asf,flv"
VIDEO_HOSTS = ("bilibili.com", "b23.tv", "youtube.com", "youtu.be", "v.qq.com")
_ID = re.compile(r"[0-9a-f]{32}")
_SHA = re.compile(r"[0-9a-f]{64}")
_FRAME = re.compile(r"f[0-9]{3}")
_TIME = r"(?:(\d{1,3}):)?(\d{2}):(\d{2})[,.](\d{3})"
_CUE = re.compile(r"^" + _TIME + r"\s*-->\s*" + _TIME + r"(?:\s+.*)?$")


def _fail(code, message):
    raise ModelError(code, message)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _snapshot_tag(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _plain_file(path, maximum):
    path = Path(path).absolute()
    if any(is_link(item) for item in (path, *path.parents)):
        _fail("unsafe_media_path", "视频或素材路径不能经过符号链接。")
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        _fail("invalid_media_file", "视频或素材不存在、为空或超过大小限制。")
    return path


def _selected_file(value, maximum):
    # Canonicalize a user-selected root once, just like canonical_vault. This
    # permits system aliases (/tmp on macOS), but never a selected link itself.
    raw = Path(value).expanduser()
    if not raw.is_absolute() or ".." in raw.parts or is_link(raw):
        _fail("unsafe_media_path", "请选择视频实际文件的绝对路径，不能使用符号链接。")
    return _plain_file(raw.resolve(), maximum)


def _media_input(path):
    # A video must not become a playlist that opens additional files or URLs.
    return ["-protocol_whitelist", "file,pipe", "-format_whitelist", MEDIA_FORMATS, "-i", path]


def _ffmpeg():
    # The installed optional component already supplies this executable. This
    # accessor performs no installation or model download.
    try:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        executable = shutil.which("ffmpeg")
    if not executable:
        _fail("video_component_missing", "请先准备视频组件，再处理视频。")
    return executable


def _run(arguments, *, timeout=120, allow_failure=False):
    try:
        result = subprocess.run(
            [str(value) for value in arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("media_command_failed", "视频处理未完成，请检查视频组件和素材后重试。")
    if result.returncode and not allow_failure:
        # ffmpeg/yt-dlp diagnostics can contain original URLs or local paths.
        _fail("media_command_failed", "视频处理失败，请检查素材格式、网络或视频组件。")
    return result


def _seconds(groups):
    hours, minutes, seconds, millis = groups
    if int(minutes) > 59 or int(seconds) > 59:
        _fail("invalid_timeline", "字幕时间格式无效。")
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_subtitles(content, duration, source="subtitle"):
    """Parse real SRT/VTT timestamps; preserve multiline cues and provenance."""
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_SUBTITLE_BYTES:
        _fail("invalid_timeline", "字幕内容过大或格式无效。")
    cues = []
    lines = content.lstrip("\ufeff").replace("\r\n", "\n").splitlines()
    index = 0
    while index < len(lines):
        match = _CUE.fullmatch(lines[index].strip())
        index += 1
        if not match:
            continue
        start, end = _seconds(match.groups()[:4]), _seconds(match.groups()[4:])
        words = []
        while index < len(lines) and lines[index].strip():
            words.append(lines[index].strip())
            index += 1
        text = html.unescape(re.sub(r"<[^>]*>", "", "\n".join(words))).strip()
        if not text:
            continue
        if start >= duration or end <= start or end > duration + 1:
            _fail("invalid_timeline", "字幕时间超出视频范围，请检查字幕是否对应此视频。")
        cues.append({"start": start, "end": min(end, duration), "text": text,
                     "source": source, "precision": "subtitle"})
    if not cues:
        return []
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    _validate_timeline(cues, duration)
    return cues


def _validate_timeline(timeline, duration):
    if not isinstance(timeline, list) or len(timeline) > 30000:
        _fail("invalid_timeline", "视频时间轴格式无效或过长。")
    total = 0
    for segment in timeline:
        if not isinstance(segment, dict):
            _fail("invalid_timeline", "视频时间轴片段格式无效。")
        start, end, text = segment.get("start"), segment.get("end"), segment.get("text")
        if not (_number(start) and _number(end) and 0 <= start < end <= duration):
            _fail("invalid_timeline", "视频时间轴片段超出视频范围。")
        if (not isinstance(text, str) or not text.strip() or len(text) > 20000
                or segment.get("precision") not in {"subtitle", "chunk"}
                or segment.get("source") not in {"subtitle", "embedded_subtitle", "platform_subtitle", "asr"}):
            _fail("invalid_timeline", "视频时间轴文字或来源格式无效。")
        if (segment["source"] == "asr") != (segment["precision"] == "chunk"):
            _fail("invalid_timeline", "字幕与音频识别的时间精度标记不一致。")
        total += len(text.encode("utf-8"))
    if total > MAX_SUBTITLE_BYTES:
        _fail("invalid_timeline", "视频时间轴文字超过处理上限。")


def _png(path):
    path = _plain_file(path, MAX_PNG_BYTES)
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        _fail("invalid_media_image", "截图不是有效的 PNG 图片。")
    cursor, size, dimensions, has_data = 8, len(data), None, False
    while cursor + 12 <= size:
        length = struct.unpack(">I", data[cursor:cursor + 4])[0]
        kind = data[cursor + 4:cursor + 8]
        end = cursor + 12 + length
        if end > size:
            _fail("invalid_media_image", "截图 PNG 数据不完整。")
        payload = data[cursor + 8:cursor + 8 + length]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            _fail("invalid_media_image", "截图 PNG 校验失败。")
        if dimensions is None:
            if kind != b"IHDR" or length != 13:
                _fail("invalid_media_image", "截图 PNG 缺少尺寸信息。")
            width, height = struct.unpack(">II", payload[:8])
            if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE):
                _fail("invalid_media_image", "截图尺寸超过处理上限。")
            dimensions = (width, height)
        elif kind == b"IHDR":
            _fail("invalid_media_image", "截图 PNG 重复声明尺寸。")
        if kind == b"IDAT":
            has_data = True
        if kind == b"IEND":
            if length or end != size or not has_data:
                _fail("invalid_media_image", "截图 PNG 结束信息无效。")
            return data, dimensions
        cursor = end
    _fail("invalid_media_image", "截图 PNG 数据不完整。")


class MediaPipeline:
    def __init__(self, data_dir, transcribe_callback):
        self.data_dir = Path(data_dir).resolve()
        self.root = self.data_dir / "media"
        self.transcribe = transcribe_callback

    def _directory(self, identity):
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            _fail("invalid_media_id", "视频任务标识无效，请重新提交。")
        directory = self.root / identity
        if any(is_link(path) for path in (self.root, directory)):
            _fail("unsafe_media_path", "视频任务目录不能是符号链接。")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.mkdir(exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
            directory.chmod(0o700)
        return directory

    def _owned(self, path, identity, maximum):
        directory = self._directory(identity)
        candidate = _plain_file(path, maximum)
        if not candidate.is_relative_to(directory) or len(candidate.relative_to(directory).parts) != 1:
            _fail("unsafe_media_path", "视频素材不属于当前任务。")
        return candidate

    def _source(self, params, progress, directory):
        reference, source_type = params.get("source_ref"), params.get("source_type")
        if not isinstance(reference, str) or not reference or len(reference) > 8192:
            _fail("invalid_media_source", "请选择有效视频文件或视频链接。")
        identity = hashlib.sha256((source_type + "\0" + reference).encode()).hexdigest() if isinstance(source_type, str) else ""
        cached = progress.checkpoint("media_source")
        if cached is not None:
            if not isinstance(cached, dict) or cached.get("input_identity") != identity:
                _fail("media_source_changed", "视频任务来源不一致，请重新提交。")
            self._validate_source(cached, params["media_id"])
            return cached
        progress({"phase": "media_source", "message": "正在保存本次视频素材的固定副本。"})
        target = directory / "source.media"
        subtitles = []
        if source_type == "video_file":
            source = _selected_file(reference, MAX_VIDEO_BYTES)
            before = _digest(source)
            temporary = directory / "source.copying"
            if is_link(temporary) or is_link(target):
                _fail("unsafe_media_path", "视频副本路径不能是符号链接。")
            with source.open("rb") as stream, temporary.open("wb") as output:
                copied = 0
                while block := stream.read(1024 * 1024):
                    copied += len(block)
                    if copied > MAX_VIDEO_BYTES:
                        _fail("media_size_limit", "视频在复制期间超过大小限制，请重新选择。")
                    output.write(block)
            if _digest(temporary) != before or _digest(source) != before:
                temporary.unlink(missing_ok=True)
                _fail("media_source_changed", "复制期间视频发生变化，请重新提交。")
            os.replace(temporary, target)
            if os.name != "nt":
                target.chmod(0o600)
            for extension in (".srt", ".vtt"):
                sidecar = source.with_suffix(extension)
                if sidecar.exists() or is_link(sidecar):
                    sidecar = _plain_file(sidecar, MAX_SUBTITLE_BYTES)
                    saved = directory / ("subtitle" + extension)
                    if is_link(saved):
                        _fail("unsafe_media_path", "字幕副本路径不能是符号链接。")
                    shutil.copyfile(sidecar, saved)
                    subtitles.append(saved)
                    break
        elif source_type == "video_url":
            try:
                url = urlsplit(reference)
                hostname = (url.hostname or "").lower()
                port = url.port
            except ValueError:
                _fail("invalid_media_url", "视频链接格式无效。")
            if (any(ord(char) < 32 for char in reference)
                    or url.scheme not in {"http", "https"} or url.username is not None
                    or url.password is not None or port not in {None, 80, 443}
                    or not any(hostname == host or hostname.endswith("." + host) for host in VIDEO_HOSTS)):
                _fail("invalid_media_url", "请使用受支持平台的 HTTP/HTTPS 视频链接，不可附带登录凭据。")
            self._download(reference, directory)
            sources = [path for path in directory.glob("download.*")
                       if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
            if len(sources) != 1:
                _fail("media_download_failed", "未得到唯一完整视频，请检查视频链接。")
            _plain_file(sources[0], MAX_VIDEO_BYTES)
            if is_link(target):
                _fail("unsafe_media_path", "视频副本路径不能是符号链接。")
            os.replace(sources[0], target)
            subtitles = sorted(directory.glob("download.*.srt"))
        else:
            _fail("invalid_media_source", "视频来源类型无效。")
        self._owned(target, params["media_id"], MAX_VIDEO_BYTES)
        duration = self._duration(target)
        if not subtitles:
            embedded = directory / "embedded.srt"
            if is_link(embedded):
                _fail("unsafe_media_path", "字幕输出路径不能是符号链接。")
            result = _run([_ffmpeg(), "-nostdin", "-v", "error", "-y", *_media_input(target),
                           "-map", "0:s:0", "-c:s", "srt", embedded], allow_failure=True)
            if result.returncode == 0 and embedded.is_file() and embedded.stat().st_size:
                subtitles = [embedded]
        entries = []
        for path in subtitles[:1]:
            path = self._owned(path, params["media_id"], MAX_SUBTITLE_BYTES)
            entries.append({"path": str(path), "sha256": _digest(path),
                            "source": "platform_subtitle" if source_type == "video_url"
                            else "embedded_subtitle" if path.name == "embedded.srt" else "subtitle"})
        value = {"media_id": params["media_id"], "path": str(target), "sha256": _digest(target),
                 "duration": duration, "input_identity": identity, "subtitles": entries,
                 "source_policy": "frozen_copy"}
        progress.checkpoint("media_source", value)
        return value

    def _download(self, reference, directory):
        # Ignore user yt-dlp config: no cookies, external downloader or exec hook.
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
              "--no-cache-dir", "--no-progress", "--no-warnings", "--no-part",
              "--retries", "0", "--fragment-retries", "0", "--socket-timeout", "30",
              "--max-filesize", str(MAX_VIDEO_BYTES), "--match-filter", f"duration <= {MAX_DURATION}",
              "--format", "best[height<=1600]/best", "--write-subs", "--write-auto-subs",
              "--sub-langs", "zh-Hans,zh-CN,zh,en", "--convert-subs", "srt",
              "--ffmpeg-location", _ffmpeg(), "--output", str(directory / "download.%(ext)s"),
              "--", reference]
        # The server may not announce Content-Length. Monitor actual files too;
        # max-filesize by itself is only a metadata-based downloader safeguard.
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            _fail("media_download_failed", "无法启动视频下载组件。")
        deadline = time.monotonic() + 900
        try:
            while process.poll() is None:
                total = 0
                for path in directory.glob("download.*"):
                    if is_link(path):
                        _fail("unsafe_media_path", "下载素材不能包含符号链接。")
                    if path.is_file():
                        total += path.stat().st_size
                if total > MAX_VIDEO_BYTES + 4 * MAX_SUBTITLE_BYTES:
                    _fail("media_size_limit", "视频下载超过素材大小上限。")
                if time.monotonic() >= deadline:
                    _fail("media_download_timeout", "视频下载超时，请稍后手动重试。")
                time.sleep(0.1)
            if process.returncode:
                _fail("media_download_failed", "视频下载失败，请检查链接或网络后手动重试。")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    def _duration(self, source):
        result = _run([_ffmpeg(), "-nostdin", "-hide_banner", *_media_input(source)], allow_failure=True)
        info = result.stderr.decode("utf-8", errors="replace")
        found = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
        if not found or "Video:" not in info:
            _fail("invalid_media_source", "素材不包含可读取的视频画面或时长。")
        duration = int(found[1]) * 3600 + int(found[2]) * 60 + float(found[3])
        if not 0 < duration <= MAX_DURATION:
            _fail("media_duration_limit", "视频时长需大于零且不超过两小时。")
        return duration

    def _validate_source(self, source, identity):
        if (source.get("media_id") != identity or not _number(source.get("duration"))
                or not 0 < source["duration"] <= MAX_DURATION
                or not isinstance(source.get("sha256"), str) or not _SHA.fullmatch(source["sha256"])):
            _fail("invalid_media_checkpoint", "视频素材检查点无效，请重新提交。")
        path = self._owned(source.get("path", ""), identity, MAX_VIDEO_BYTES)
        if _digest(path) != source["sha256"]:
            _fail("media_source_changed", "本次任务的固定视频副本已变化，请重新提交。")
        subtitles = source.get("subtitles", [])
        if not isinstance(subtitles, list) or len(subtitles) > 1:
            _fail("invalid_media_checkpoint", "视频字幕检查点无效。")
        for entry in subtitles:
            if not isinstance(entry, dict):
                _fail("invalid_media_checkpoint", "视频字幕检查点格式无效。")
            path = self._owned(entry.get("path", ""), identity, MAX_SUBTITLE_BYTES)
            if _digest(path) != entry.get("sha256"):
                _fail("media_source_changed", "本次任务的字幕副本已变化，请重新提交。")

    def _timeline(self, params, progress, source, directory):
        cached = progress.checkpoint("media_timeline")
        if cached is not None:
            if not isinstance(cached, dict) or cached.get("source_sha256") != source["sha256"]:
                _fail("invalid_media_checkpoint", "视频时间轴与素材不匹配。")
            _validate_timeline(cached.get("timeline"), source["duration"])
            if (any(cue["source"] == "asr" for cue in cached["timeline"])
                    and cached.get("asr_snapshot_sha256") != _snapshot_tag(params.get("asr_snapshot"))):
                _fail("media_asr_config_changed", "音频识别配置与原任务不一致，请重新提交。")
            return cached["timeline"]
        timeline = []
        for entry in source["subtitles"]:
            try:
                content = Path(entry["path"]).read_text(encoding="utf-8-sig")
            except UnicodeError:
                _fail("invalid_timeline", "字幕不是有效的 UTF-8 文本。")
            timeline = parse_subtitles(content, source["duration"], entry["source"])
        if not timeline:
            snapshot = params.get("asr_snapshot")
            if not snapshot:
                _fail("missing_asr_route", "此视频没有可用字幕，请在模型服务中配置音频识别后重新提交任务。")
            if self.transcribe is None:
                _fail("missing_asr_route", "音频识别服务尚未配置，请配置后重新提交任务。")
            for index in range(math.ceil(source["duration"] / ASR_CHUNK_SECONDS)):
                start = index * ASR_CHUNK_SECONDS
                end = min(start + ASR_CHUNK_SECONDS, source["duration"])
                name = f"media_asr_{index:04d}"
                chunk = progress.checkpoint(name)
                if chunk is not None:
                    if (not isinstance(chunk, dict) or chunk.get("source_sha256") != source["sha256"]
                            or chunk.get("start") != start or chunk.get("end") != end
                            or chunk.get("asr_snapshot_sha256") != _snapshot_tag(snapshot)
                            or not isinstance(chunk.get("text"), str)):
                        _fail("invalid_media_checkpoint", "音频分段检查点无效。")
                    text = chunk["text"]
                else:
                    progress({"phase": "transcription", "message": f"正在识别第 {index + 1} 段音频（按分段范围标记时间）。"})
                    wav = directory / f"audio-{index:04d}.wav"
                    if is_link(wav):
                        _fail("unsafe_media_path", "音频输出路径不能是符号链接。")
                    _run([_ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", str(start),
                          *_media_input(source["path"]), "-t", str(end - start), "-vn", "-ac", "1",
                          "-ar", "16000", "-c:a", "pcm_s16le", wav])
                    self._owned(wav, params["media_id"], 2 * 1024 * 1024)
                    text = self.transcribe(snapshot, wav)
                    if not isinstance(text, str) or len(text) > 20000:
                        _fail("invalid_transcription", "音频识别结果格式无效或过长。")
                    progress.checkpoint(name, {"source_sha256": source["sha256"], "start": start,
                                               "end": end, "text": text,
                                               "asr_snapshot_sha256": _snapshot_tag(snapshot)})
                if text.strip():
                    timeline.append({"start": start, "end": end, "text": text.strip(),
                                     "source": "asr", "precision": "chunk"})
        _validate_timeline(timeline, source["duration"])
        if not timeline:
            _fail("empty_transcription", "视频未获得可用字幕或语音文字。")
        progress.checkpoint("media_timeline", {"source_sha256": source["sha256"], "timeline": timeline,
                                              "asr_snapshot_sha256": _snapshot_tag(params.get("asr_snapshot"))})
        return timeline

    def _frame(self, source, stamp, path):
        if is_link(path):
            _fail("unsafe_media_path", "截图输出路径不能是符号链接。")
        # ffmpeg may exit successfully without emitting a frame near a sparse
        # stream's tail. Never let a previous candidate masquerade as new output.
        path.unlink(missing_ok=True)
        _run([_ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{stamp:.6f}",
              *_media_input(source), "-frames:v", "1", "-vf",
              "scale=w='min(1600,iw)':h='min(1600,ih)':force_original_aspect_ratio=decrease",
              "-pix_fmt", "rgb24", "-threads", "1", "-f", "image2", path])
        if not path.exists():
            _fail("media_frame_unavailable", "所选时间没有可提取的视频帧，请选择更早的时间后重新提交任务。")
        _png(path)
        gray = _run([_ffmpeg(), "-nostdin", "-v", "error", "-i", path,
                     "-vf", "scale=32:32", "-frames:v", "1", "-f", "rawvideo",
                     "-pix_fmt", "gray", "pipe:1"]).stdout
        if len(gray) != 1024:
            _fail("invalid_media_image", "无法读取截图的灰度取样。")
        sharpness = sum(abs(gray[i] - gray[i - 1]) for i in range(1, 1024) if i % 32)
        sharpness += sum(abs(gray[i] - gray[i - 32]) for i in range(32, 1024))
        return gray, sharpness

    def _frames(self, params, progress, source, directory):
        times = params.get("frame_times", [])
        mode = params.get("video_mode", "text")
        if not isinstance(times, list) or len(times) > MAX_FRAMES:
            _fail("invalid_frame_times", "截图时间最多填写八个秒数。")
        if any(not _number(stamp) or not 0 <= stamp < source["duration"] for stamp in times):
            _fail("invalid_frame_times", "截图时间必须是视频范围内的有限非负秒数。")
        if len(set(times)) != len(times):
            _fail("invalid_frame_times", "截图时间不能重复。")
        if mode not in {"text", "illustrated"}:
            _fail("invalid_video_mode", "视频模式应为纯文字或图文。")
        if mode == "text" and times:
            _fail("invalid_frame_times", "手选截图时间只能用于图文模式。")
        sampling = "manual" if times else "uniform_nearby"
        descriptor = {"source_sha256": source["sha256"], "mode": mode,
                      "requested_times": times, "sampling": sampling}
        cached = progress.checkpoint("media_frames")
        if cached is not None:
            if not isinstance(cached, dict) or any(cached.get(key) != value for key, value in descriptor.items()):
                _fail("invalid_media_checkpoint", "截图选择与原任务不一致，请重新提交。")
            self._validate_frames(cached.get("frames"), params["media_id"], source["duration"])
            return cached["frames"], sampling
        frames, thumbnails = [], []
        if mode == "illustrated":
            progress({"phase": "frames", "message": "正在提取有限截图样本；自动取样不代表覆盖全部重要画面。"})
            count = min(MAX_FRAMES, max(1, math.ceil(source["duration"] / 20)))
            selected = sorted(times) if times else [source["duration"] * (index + 0.5) / count for index in range(count)]
            for center in selected:
                candidates = [center] if times else sorted(set(
                    min(max(0, center + delta), max(0, source["duration"] - 0.1)) for delta in (-0.8, 0, 0.8)))
                best = None
                for candidate_index, stamp in enumerate(candidates):
                    path = directory / f"candidate-{candidate_index}.png"
                    try:
                        thumb, sharpness = self._frame(source["path"], stamp, path)
                    except ModelError as exc:
                        if not times and exc.code == "media_frame_unavailable":
                            continue
                        raise
                    rank = (sharpness, -abs(stamp - center))
                    if best is None or rank > best[0]:
                        best = (rank, stamp, thumb, path.read_bytes())
                if best is None and not times:
                    # At most two extra seeks; record the fallback seek time,
                    # never the original center for a different extracted frame.
                    for stamp in dict.fromkeys((max(0, center - 2), 0)):
                        if stamp in candidates:
                            continue
                        path = directory / "candidate-fallback.png"
                        try:
                            thumb, sharpness = self._frame(source["path"], stamp, path)
                        except ModelError as exc:
                            if exc.code == "media_frame_unavailable":
                                continue
                            raise
                        best = ((sharpness, -abs(stamp - center)), stamp, thumb, path.read_bytes())
                        break
                if best is None:
                    _fail("media_frame_unavailable", "视频取样范围内没有可提取的画面，请检查素材或指定更早时间后重新提交。")
                _, stamp, thumb, data = best
                # Only automatic samples deduplicate: requested timestamps are
                # explicit user choices and must not silently disappear.
                if not times and any(sum(abs(a - b) for a, b in zip(thumb, old)) / 1024 < 2.0 for old in thumbnails):
                    continue
                identity = f"f{len(frames) + 1:03d}"
                target = directory / (identity + ".png")
                if is_link(target):
                    _fail("unsafe_media_path", "截图目标路径不能是符号链接。")
                temporary = directory / (identity + ".writing")
                if is_link(temporary):
                    _fail("unsafe_media_path", "截图临时路径不能是符号链接。")
                temporary.write_bytes(data)
                os.replace(temporary, target)
                frames.append({"id": identity, "time": stamp, "path": str(target),
                               "mime_type": "image/png", "sha256": hashlib.sha256(data).hexdigest()})
                thumbnails.append(thumb)
        progress.checkpoint("media_frames", {**descriptor, "frames": frames})
        return frames, sampling

    def _validate_frames(self, frames, identity, duration):
        if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
            _fail("invalid_media_checkpoint", "截图清单无效或超过数量上限。")
        identifiers = set()
        for frame in frames:
            if not isinstance(frame, dict):
                _fail("invalid_media_checkpoint", "截图记录格式无效。")
            stamp, key = frame.get("time"), frame.get("id")
            if (not _number(stamp) or not 0 <= stamp < duration or not isinstance(key, str)
                    or not _FRAME.fullmatch(key) or key in identifiers):
                _fail("invalid_media_checkpoint", "截图时间或编号无效。")
            identifiers.add(key)
            path = self._owned(frame.get("path", ""), identity, MAX_PNG_BYTES)
            if path.name != key + ".png" or frame.get("mime_type") != "image/png":
                _fail("invalid_media_image", "截图路径或类型与清单不匹配。")
            data, _ = _png(path)
            if hashlib.sha256(data).hexdigest() != frame.get("sha256"):
                _fail("media_image_changed", "截图内容已变化，请重新提交视频任务。")

    def prepare(self, params, progress):
        directory = self._directory(params.get("media_id"))
        source = self._source(params, progress, directory)
        # Validate frame selections before performing any potentially paid ASR.
        times = params.get("frame_times", [])
        if (not isinstance(times, list) or len(times) > MAX_FRAMES
                or any(not _number(stamp) or not 0 <= stamp < source["duration"] for stamp in times)):
            _fail("invalid_frame_times", "截图时间最多八个，且必须在视频范围内。")
        if len(set(times)) != len(times):
            _fail("invalid_frame_times", "截图时间不能重复。")
        mode = params.get("video_mode", "text")
        if mode not in {"text", "illustrated"} or (mode == "text" and times):
            _fail("invalid_video_mode", "视频模式或截图选择无效。")
        timeline = self._timeline(params, progress, source, directory)
        frames, sampling = self._frames(params, progress, source, directory)
        bundle = {"media_id": params["media_id"], "source_sha256": source["sha256"],
                  "source_path": source["path"], "source_policy": "frozen_copy",
                  "duration": source["duration"], "timeline": timeline, "frames": frames,
                  "sampling": sampling, "video_mode": mode,
                  "sampling_note": "自动截图是有限取样，不保证覆盖视频的全部重要场景。"}
        self.validate_bundle(bundle)
        return bundle

    def validate_bundle(self, bundle):
        if not isinstance(bundle, dict):
            _fail("invalid_media_checkpoint", "视频素材清单无效。")
        identity, duration = bundle.get("media_id"), bundle.get("duration")
        self._directory(identity)
        if not _number(duration) or not 0 < duration <= MAX_DURATION:
            _fail("invalid_media_checkpoint", "视频素材时长无效。")
        source = self._owned(bundle.get("source_path", ""), identity, MAX_VIDEO_BYTES)
        if _digest(source) != bundle.get("source_sha256"):
            _fail("media_source_changed", "视频固定副本已变化，请重新提交任务。")
        _validate_timeline(bundle.get("timeline"), duration)
        if not bundle["timeline"]:
            _fail("empty_transcription", "视频时间轴没有可用字幕或语音文字。")
        self._validate_frames(bundle.get("frames"), identity, duration)
        if bundle.get("video_mode") == "illustrated" and not bundle["frames"]:
            _fail("missing_media_images", "图文任务没有获得有效截图。")
        return bundle

    def image_payload(self, frame):
        if not isinstance(frame, dict) or not isinstance(frame.get("path"), str):
            _fail("invalid_media_image", "截图记录格式无效。")
        path = Path(frame["path"]).absolute()
        if path.parent.parent != self.root:
            _fail("unsafe_media_path", "截图不属于本机视频任务目录。")
        identity = path.parent.name
        # The actual duration is validated with the bundle before this method;
        # keep a strict finite timestamp check for independent callers as well.
        self._validate_frames([frame], identity, MAX_DURATION + 1)
        return {"mime_type": "image/png", "data": base64.b64encode(path.read_bytes()).decode("ascii")}
