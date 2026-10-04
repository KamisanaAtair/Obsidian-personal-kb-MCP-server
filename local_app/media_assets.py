"""Server-owned, no-clobber Obsidian attachments and exact frame references."""

import hashlib
import os
import re
import struct
import tempfile
from pathlib import Path

from .models import ModelError
from .video_prompts import timestamp
from .workspaces import is_link, normalize_folder

MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _fail(message="截图或附件发生变化，请保留现有文件并重新提交任务。"):
    return ModelError("media_changed", message)


def checked_png(path, expected=None):
    path = Path(path)
    if is_link(path) or not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        raise _fail()
    data = path.read_bytes()
    if len(data) < 33 or data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise _fail("截图不是有效 PNG，请重新处理视频。")
    width, height = struct.unpack(">II", data[16:24])
    if not 0 < width <= 4096 or not 0 < height <= 4096 or width * height > 8_000_000:
        raise _fail("截图像素超出范围，请重新处理视频。")
    digest = hashlib.sha256(data).hexdigest()
    if expected and digest != expected:
        raise _fail()
    return data, digest


def manifest_for(prepare_id, bundle, media_root):
    if not re.fullmatch(r"[0-9a-f]{32}", prepare_id):
        raise _fail()
    manifest = []
    root = Path(media_root).resolve()
    for frame in bundle["frames"]:
        identity = frame["id"]
        if not re.fullmatch(r"f[0-9]{3}", identity):
            raise _fail()
        source = Path(frame["path"])
        if not source.is_absolute() or not source.resolve().is_relative_to(root):
            raise _fail()
        relative_source = source.relative_to(root)
        cursor = root
        for part in relative_source.parts:
            cursor /= part
            if is_link(cursor):
                raise _fail()
        checked_png(source, frame["sha256"])
        manifest.append(
            {
                "id": identity,
                "time": frame["time"],
                "source_path": str(source),
                "sha256": frame["sha256"],
                "relative_path": f"Assets/PersonalKB/{prepare_id}/{identity}.png",
            }
        )
    if not 1 <= len(manifest) <= 8 or len({v["id"] for v in manifest}) != len(manifest):
        raise _fail("没有有效截图或截图清单重复，请重新处理视频。")
    return manifest


def _destination(root, frame):
    relative = frame["relative_path"]
    if not re.fullmatch(r"Assets/PersonalKB/[0-9a-f]{32}/f[0-9]{3}\.png", relative):
        raise _fail()
    target = root / relative
    normalize_folder(root, target.parent.as_posix())
    if is_link(target) or not target.resolve().is_relative_to(root):
        raise _fail()
    return target


def render_frames(body, manifest):
    if re.search(r"!\[|<!--|<![A-Z]|<\?|</?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>)", body):
        raise ModelError(
            "invalid_frame_reference", "图文正文只能使用提供的截图占位符，不能自建图片路径或使用 HTML。"
        )
    identities = re.findall(r"\[\[FRAME:([^\]]+)\]\]", body)
    if sorted(identities) != sorted(frame["id"] for frame in manifest):
        raise ModelError(
            "invalid_frame_reference", "图文正文存在未知、重复或遗漏的截图，请重新生成正文。"
        )
    fence = None
    for line in body.splitlines():
        if fence is not None:
            # CommonMark closing fences may contain only trailing spaces, not an info string.
            closing = r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*"
            if re.fullmatch(closing, line):
                fence = None
            elif "[[FRAME:" in line:
                raise ModelError("invalid_frame_reference", "截图不能放在代码块中，请在正文单独引用。")
            continue
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if token[0] != "`" or "`" not in line[marker.end():]:
                fence = token
    for frame in manifest:
        placeholder = f"[[FRAME:{frame['id']}]]"
        if not re.search(r"(?m)^" + re.escape(placeholder) + r"\s*$", body):
            raise ModelError("invalid_frame_reference", "每个截图占位符需要单独一行。")
        body = body.replace(
            placeholder,
            # Paragraph boundaries also prevent multiline inline-code spans swallowing an embed.
            f"\n\n![[{frame['relative_path']}]]\n\n*截图 {frame['id']} · {timestamp(frame['time'])}*\n\n",
        )
    if "[[FRAME:" in body:
        raise ModelError("invalid_frame_reference", "截图占位符格式无效。")
    return body


def publish(root, manifest):
    """Publish each immutable file atomically; preserve partial success for retry."""
    for frame in manifest:
        destination = _destination(root, frame)
        if destination.exists():
            checked_png(destination, frame["sha256"])
            continue
        data, _ = checked_png(frame["source_path"], frame["sha256"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _destination(root, frame)
        descriptor, temporary = tempfile.mkstemp(prefix=".personal-kb-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            _destination(root, frame)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                checked_png(destination, frame["sha256"])
            except OSError:
                if os.name != "nt":
                    raise
                try:
                    os.rename(temporary, destination)
                except FileExistsError:
                    checked_png(destination, frame["sha256"])
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    validate_published(root, manifest)


def validate_published(root, manifest):
    for frame in manifest:
        checked_png(_destination(root, frame), frame["sha256"])


def public_media(manifest, bundle):
    return {
        "frames": [{key: f[key] for key in ("id", "time", "relative_path")} for f in manifest],
        "timeline_precision": sorted({s["precision"] for s in bundle["timeline"]}),
        "sampling": bundle.get("sampling", "manual"),
    }
