"""Optional components prepared as recoverable jobs, never during MCP handshake."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.client import HTTPException
from pathlib import Path


class SlowDownload(OSError):
    """Try the next pinned origin when a responsive connection makes little progress."""


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {} if default is None else default


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".kb-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def download_verified(
    urls: list[str], target: Path, expected: str, size: int, progress
) -> None:
    """Resume a partial file, validate its full digest before promoting it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == size and digest(target) == expected:
        progress(
            {"phase": "cached", "file": target.name, "downloaded": size, "total": size}
        )
        return
    partial = target.with_suffix(target.suffix + ".partial")
    for url in urls:
        for attempt in range(3):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset >= size:
                if offset == size and digest(partial) == expected:
                    os.replace(partial, target)
                    return
                partial.unlink()
                offset = 0
            headers = {"User-Agent": "PersonalKB/0.3", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as response:
                    if offset and response.status != 206:
                        offset = 0
                    if response.status == 206:
                        content_range = response.headers.get("Content-Range", "")
                        if not content_range.startswith(f"bytes {offset}-"):
                            raise ValueError("Unexpected download range")
                    written = offset
                    last_update = 0.0
                    started = time.monotonic()
                    with partial.open("ab" if offset else "wb") as stream:
                        while block := response.read(256 * 1024):
                            written += len(block)
                            if written > size:
                                raise ValueError("Download exceeds release size")
                            stream.write(block)
                            if time.monotonic() - last_update >= 0.5:
                                progress(
                                    {
                                        "phase": "download",
                                        "file": target.name,
                                        "downloaded": written,
                                        "total": size,
                                    }
                                )
                                last_update = time.monotonic()
                            elapsed = time.monotonic() - started
                            if (
                                elapsed > 15
                                and (written - offset) / elapsed < 128 * 1024
                                and url != urls[-1]
                            ):
                                raise SlowDownload("Trying alternate pinned source")
                if partial.stat().st_size < size:
                    # A server may end a response cleanly before delivering the
                    # whole artifact. Keep its verified-length prefix for Range
                    # retry; only a complete, invalid artifact must be discarded.
                    raise OSError("Incomplete download; resuming retained prefix")
                if partial.stat().st_size != size or digest(partial) != expected:
                    partial.unlink(missing_ok=True)
                    raise ValueError("Release checksum mismatch")
                os.replace(partial, target)
                return
            except SlowDownload:
                break
            except (OSError, ValueError, HTTPException):
                if attempt < 2:
                    time.sleep(min(2**attempt, 4))
    raise RuntimeError("下载未完成，请检查网络后重试；已校验的文件和下载进度会保留。")


class FeatureManager:
    def __init__(self, data_dir: Path, jobs, models=None):
        self.data = data_dir
        self.jobs = jobs
        self.models = models
        self.release = Path(__file__).resolve().parents[1] / "installer"
        self.lock = threading.RLock()
        self.feature_path = self.data / "features.json"
        jobs.register("prepare_semantic", self._semantic)
        jobs.register("prepare_video", self._video)
        self._add_bin_path()
        self._reconcile()

    def _environment(self, feature):
        return hashlib.sha256(
            (
                str(Path(sys.prefix).resolve())
                + digest(self.release / f"requirements-{feature}.lock")
            ).encode()
        ).hexdigest()

    def _files_present(self, feature, item):
        if feature == "video":
            return (
                self.data / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            ).is_file()
        model = Path(item.get("model_path", ""))
        if not model.is_absolute():
            return False
        try:
            return all(
                (model / entry["path"]).stat().st_size == entry["size"]
                for entry in read_json(self.release / "model-manifest.json")["files"]
            )
        except (OSError, KeyError):
            return False

    def _reconcile(self):
        """A new base environment must not inherit another version's ready flag."""
        with self.lock:
            state = read_json(self.feature_path)
            changed = False
            for feature, modules in {
                "semantic": (
                    "chromadb",
                    "sentence_transformers",
                    "langchain_huggingface",
                ),
                "video": ("yt_dlp", "imageio_ffmpeg"),
            }.items():
                item = state.get(feature, {})
                if item.get("ready") and (
                    item.get("environment") != self._environment(feature)
                    or not self._files_present(feature, item)
                    or any(importlib.util.find_spec(name) is None for name in modules)
                ):
                    state[feature] = {**item, "ready": False, "phase": "needs_prepare"}
                    changed = True
                elif item.get("phase") == "preparing" and not any(
                    job["kind"] == "prepare_" + feature
                    and job["status"] in {"queued", "running"}
                    for job in self.jobs.list()
                ):
                    state[feature] = {**item, "ready": False, "phase": "interrupted"}
                    changed = True
            if changed:
                atomic_json(self.feature_path, state)

    def _add_bin_path(self):
        local_bin = self.data / "bin"
        runtime_bin = Path(sys.executable).parent
        os.environ["PATH"] = os.pathsep.join(
            [str(local_bin), str(runtime_bin), os.environ.get("PATH", "")]
        )

    def status(self):
        self._reconcile()
        state = read_json(self.feature_path)
        configured = False
        if self.models is not None:
            from .models import ModelError

            try:
                self.models.snapshot("asr")
                configured = True
            except ModelError:
                pass
        video = {
            **state.get("video", {}),
            "key_saved": configured,
            "asr_configured": configured,
        }
        return {"semantic": state.get("semantic", {"ready": False}), "video": video}

    def save_key(self, value: str):
        if self.models is None:
            raise ValueError("请通过本机统一模型设置保存密钥。")
        from .secret_setup import SecretSetup

        return SecretSetup(self.data, self.models).save_legacy_key(value)
        return {"key_saved": bool(value), "key_validated": False}

    def prepare(self, feature: str):
        if feature not in {"semantic", "video"}:
            raise ValueError("未知功能。")
        return self.jobs.submit(
            "prepare_" + feature, {}, dedupe_key="feature:" + feature
        )

    def _set(self, feature: str, state: dict):
        with self.lock:
            values = read_json(self.feature_path)
            values[feature] = {**state, "environment": self._environment(feature)}
            atomic_json(self.feature_path, values)

    def _install(self, feature: str, progress):
        uv = os.environ.get("PERSONAL_KB_UV") or shutil.which("uv")
        if not uv or not Path(uv).is_file():
            raise RuntimeError("找不到安装组件，请使用安装包启动程序后重试。")
        requirements = self.release / f"requirements-{feature}.lock"
        progress(
            {"phase": "dependencies", "message": "正在准备功能依赖；已缓存内容会复用。"}
        )
        # The fixed lock prevents changes to versions already used by the basic runtime.
        command = [
            uv,
            "--no-config",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--require-hashes",
            "--only-binary",
            ":all:",
            "-r",
            str(requirements),
        ]
        env = {**os.environ, "UV_HTTP_TIMEOUT": "60", "UV_NO_PROGRESS": "1"}
        result = subprocess.run(
            command, capture_output=True, env=env, timeout=3600, check=False
        )
        if result.returncode:
            raise RuntimeError(
                "功能依赖下载或安装失败，请检查网络后重试。基础功能仍可使用。"
            )
        importlib.invalidate_caches()

    def _semantic(self, params, progress):
        self._set("semantic", {"ready": False, "phase": "preparing"})
        try:
            self._install("semantic", progress)
            manifest = read_json(self.release / "model-manifest.json")
            model_dir = self.data / "models" / "bge-m3"
            files = manifest["files"]
            for index, item in enumerate(files):
                name = item["path"]
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise ValueError("Invalid release manifest")
                urls = [
                    "https://modelscope.cn/models/BAAI/bge-m3/resolve/"
                    + manifest["modelscope_revision"]
                    + "/"
                    + urllib.parse.quote(name),
                    "https://huggingface.co/BAAI/bge-m3/resolve/"
                    + manifest["huggingface_revision"]
                    + "/"
                    + urllib.parse.quote(name),
                ]
                progress(
                    {
                        "phase": "model",
                        "completed_files": index,
                        "total_files": len(files),
                    }
                )
                download_verified(
                    urls, model_dir / name, item["sha256"], item["size"], progress
                )
            progress({"phase": "verify", "message": "正在验证模型可加载。"})
            probe = "from sentence_transformers import SentenceTransformer; import sys; m=SentenceTransformer(sys.argv[1],device='cpu',local_files_only=True); v=m.encode(['安装验证']); assert v.shape==(1,1024)"
            result = subprocess.run(
                [sys.executable, "-c", probe, str(model_dir)],
                capture_output=True,
                env={
                    **os.environ,
                    "HF_HUB_OFFLINE": "1",
                    "TOKENIZERS_PARALLELISM": "false",
                },
                timeout=600,
                check=False,
            )
            if result.returncode:
                raise RuntimeError("模型已下载，但加载验证失败；请重试或检查可用内存。")
            self._set(
                "semantic",
                {
                    "ready": True,
                    "model_path": str(model_dir),
                    "model": manifest["model"],
                    "phase": "ready",
                },
            )
            return {"ready": True, "feature": "semantic"}
        except Exception:
            self._set("semantic", {"ready": False, "phase": "failed"})
            raise

    def _video(self, params, progress):
        self._set("video", {"ready": False, "phase": "preparing"})
        try:
            self._install("video", progress)
            import imageio_ffmpeg

            binary = Path(imageio_ffmpeg.get_ffmpeg_exe())
            target = self.data / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, target)
            target.chmod(0o700)
            subprocess.run(
                [str(target), "-version"], capture_output=True, check=True, timeout=10
            )
            self._add_bin_path()
            self._set("video", {"ready": True, "phase": "ready"})
            return {
                "ready": True,
                "feature": "video",
                "key_saved": self.status()["video"]["key_saved"],
            }
        except Exception:
            self._set("video", {"ready": False, "phase": "failed"})
            raise
