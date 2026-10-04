"""Bounded media validation and deterministic native/compatible request mapping.

Only caller-selected media is accepted. No URL images, redirects, implicit model
selection, secret lookup, network access, or billed retry occurs in this module.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import struct
import tempfile
import wave
import zlib
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .errors import ModelError

CAPABILITIES = ("vision", "asr")
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_194_304
MAX_AUDIO_BYTES = 6 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DASHSCOPE_HOSTS = {
    "dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com",
}


def _png_dimensions(data):
    """Check PNG framing, checksums and bounded raster size without an image dependency."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError
    pos, width, height, channels = 8, 0, 0, 0
    compressed = bytearray()
    ended = False
    while pos + 12 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + size
        if end > len(data):
            raise ValueError
        payload = data[pos + 8:pos + 8 + size]
        checksum = int.from_bytes(data[pos + 8 + size:end], "big")
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != checksum:
            raise ValueError
        if pos == 8:
            if kind != b"IHDR" or size != 13:
                raise ValueError
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 0)
            if (not 0 < width <= 8192 or not 0 < height <= 8192
                    or width * height > MAX_IMAGE_PIXELS or not channels
                    or depth != 8 or compression or filtering or interlace):
                raise ValueError
        elif kind == b"IHDR":
            raise ValueError
        if kind == b"IDAT":
            compressed.extend(payload)
        if kind == b"IEND":
            if size or end != len(data):
                raise ValueError
            ended = True
            break
        pos = end
    if not ended or not compressed:
        raise ValueError
    expected = height * (1 + width * channels)
    decoder = zlib.decompressobj()
    raster = decoder.decompress(bytes(compressed), expected + 1)
    if len(raster) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError
    if any(raster[row * (1 + width * channels)] > 4 for row in range(height)):
        raise ValueError
    return width, height


def validate_images(images):
    if images is None:
        return []
    if not isinstance(images, list) or not 1 <= len(images) <= 8:
        raise ModelError("invalid_images", "视觉请求需要 1–8 张 PNG 图片。")
    result, total = [], 0
    for item in images:
        try:
            if (not isinstance(item, dict) or set(item) != {"mime_type", "data"}
                    or item["mime_type"] != "image/png" or not isinstance(item["data"], str)
                    or len(item["data"]) > (MAX_IMAGE_BYTES + 2) // 3 * 4):
                raise ValueError
            data = base64.b64decode(item["data"], validate=True)
            total += len(data)
            if not data or len(data) > MAX_IMAGE_BYTES or total > 16 * 1024 * 1024:
                raise ValueError
            _png_dimensions(data)
            result.append({"mime_type": "image/png", "data": base64.b64encode(data).decode("ascii")})
        except (ValueError, TypeError, binascii.Error, zlib.error, struct.error):
            raise ModelError(
                "invalid_images", "图片须为有效的 8 位非交错 PNG，单张不超过 4 MB / 419 万像素，合计不超过 16 MB。"
            ) from None
    return result


def read_wav(path):
    try:
        selected = Path(path)
        if selected.is_symlink() or not selected.is_file() or not 44 <= selected.stat().st_size <= MAX_AUDIO_BYTES:
            raise ValueError
        with selected.open("rb") as stream:
            data = stream.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise ValueError
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                    or audio.getframerate() != 16000 or audio.getcomptype() != "NONE"
                    or not 0 < frames <= 180 * 16000
                    or len(audio.readframes(frames)) != frames * 2):
                raise ValueError
        return data
    except (OSError, TypeError, ValueError, EOFError, wave.Error):
        raise ModelError(
            "invalid_audio", "音频须为本地 PCM16、单声道、16 kHz WAV，单段不超过 180 秒或 6 MB。"
        ) from None


def audio_request(profile, audio):
    if profile["audio_api_style"] == "openai_audio":
        if profile["provider"] == "ollama":
            raise ModelError("unsupported_audio_api", "Ollama 原生接口不提供语音转写，请配置兼容 ASR 服务。")
        return profile["base_url"] + "/audio/transcriptions", {
            "data": {"model": profile["model_id"], "response_format": "json"},
            "files": {"file": ("audio.wav", audio, "audio/wav")},
        }
    if profile["audio_api_style"] != "dashscope":
        raise ModelError("invalid_audio_api_style", "语音转写接口类型无效。")
    url = urlsplit(profile["base_url"])
    official_host = url.hostname in DASHSCOPE_HOSTS or bool(re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,63}\.(cn-beijing|ap-southeast-1|us-east-1)\.maas\.aliyuncs\.com",
        url.hostname or "",
    ))
    if (url.scheme != "https" or not official_host or url.port not in {None, 443}
            or url.path not in {"", "/compatible-mode/v1", "/api/v1"}):
        raise ModelError("invalid_audio_endpoint", "DashScope 原生 ASR 须使用已支持地域的官方 HTTPS 地址。")
    endpoint = urlunsplit((url.scheme, url.netloc,
                          "/api/v1/services/aigc/multimodal-generation/generation", "", ""))
    return endpoint, {"json": {
        "model": profile["model_id"],
        "input": {"messages": [{"role": "user", "content": [{
            "audio": "data:audio/wav;base64," + base64.b64encode(audio).decode("ascii")
        }]}]},
        "parameters": {"asr_options": {"enable_itn": False}},
    }}


def test_image():
    def chunk(kind, value):
        return (struct.pack(">I", len(value)) + kind + value
                + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF))
    png = (PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\0\0" * 32) * 32)) + chunk(b"IEND", b""))
    return {"mime_type": "image/png", "data": base64.b64encode(png).decode("ascii")}


@contextmanager
def test_wav():
    with tempfile.TemporaryDirectory(prefix="personal-kb-asr-test-") as folder:
        path = Path(folder) / "test.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 16000)
        yield path
