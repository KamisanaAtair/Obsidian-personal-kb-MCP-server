"""Build deterministic ZIPs only after validating every selected platform input."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.bootstrap import payload_files  # noqa: E402

PLATFORMS = ("windows-x64", "macos-arm64")
DOC_FILES = (
    "README-FIRST.md",
    "docs/SETUP_FROM_ZIP.md",
    "docs/workbuddy.md",
    "docs/HOST_USAGE.md",
    "docs/LEGACY_STDIO.md",
    "docs/video-notes.md",
    "personal-kb-mcp-setup/SKILL.md",
)
REQUIRED_FILES = (
    "pyproject.toml", "README.md", "LICENSE", "local_app/__init__.py",
    "installer/release.json", "installer/bootstrap.py",
    "installer/requirements-base.lock", "installer/requirements-video.lock",
    "installer/requirements-semantic.lock", "installer/third_party/NOTICE.md",
    "installer/third_party/uv-LICENSE-MIT", "installer/third_party/uv-LICENSE-APACHE",
    "local_app/server.py", "local_app/static/index.html",
    "local_app/static/app.js", "local_app/static/style.css", *DOC_FILES,
)


def required_file(root: Path, relative: str, *, allow_empty: bool = False) -> Path:
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
        raise ValueError(f"Package input cannot be a symlink: {relative}")
    if not path.is_file() or (not allow_empty and path.stat().st_size == 0):
        raise ValueError(f"Missing or empty required package input: {relative}")
    return path


def validate_inputs(root: Path, platforms: tuple[str, ...]) -> dict:
    if not platforms or len(set(platforms)) != len(platforms):
        raise ValueError("Select at least one distinct platform")
    if any(platform not in PLATFORMS for platform in platforms):
        raise ValueError("Unsupported package platform")
    for relative in REQUIRED_FILES:
        required_file(root, relative)
    release = json.loads((root / "installer/release.json").read_text(encoding="utf-8"))
    version = release.get("version")
    if not isinstance(version, str) or not version or any(
        c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-" for c in version
    ):
        raise ValueError("Invalid release version")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    tree = ast.parse((root / "local_app/__init__.py").read_text(encoding="utf-8"))
    runtime_version = next((
        ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    ), None)
    if version != project.get("project", {}).get("version") or version != runtime_version:
        raise ValueError("Release, project and runtime versions must match")
    for platform in platforms:
        entries = ("install.cmd",) if platform == "windows-x64" else ("install.command", "install.sh")
        for relative in entries:
            required_file(root, relative)
        filename = "uv.exe" if platform == "windows-x64" else "uv"
        relative = f"installer/vendor/{platform}/{filename}"
        expected = release.get("uv_binaries", {}).get(platform, {})
        if expected.get("file") != relative:
            raise ValueError(f"Missing or invalid binary manifest: {platform}")
        binary = required_file(root, relative).read_bytes()
        if len(binary) != expected.get("bytes") or hashlib.sha256(binary).hexdigest() != expected.get("sha256"):
            raise ValueError(f"Bundled runtime size or SHA256 mismatch: {relative}")
    return release


def build(
    *, root: Path = ROOT, output: Path | None = None, platforms: tuple[str, ...] = PLATFORMS
) -> list[dict]:
    root = Path(root).absolute()
    # Check ALL selected inputs before making any new output or replacing an old package.
    release = validate_inputs(root, platforms)
    output = Path(output) if output is not None else root / "dist"
    sources = sorted(set(payload_files(root)) | {root / name for name in DOC_FILES})
    output.mkdir(parents=True, exist_ok=True)
    artifacts = []
    with tempfile.TemporaryDirectory(prefix=".installer-build-", dir=output) as staging:
        staged = Path(staging)
        for platform in platforms:
            name = f"PersonalKB-{release['version']}-{platform}"
            path = staged / f"{name}.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for source in sources:
                    relative = source.relative_to(root)
                    if relative.parts[:2] == ("installer", "vendor") and relative.parts[2] != platform:
                        continue
                    required_file(root, relative.as_posix(), allow_empty=True)
                    entry = zipfile.ZipInfo(f"{name}/{relative.as_posix()}", (2026, 9, 28, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.create_system = 3
                    executable = source.name in {"install.command", "install.sh", "uv"}
                    entry.external_attr = (0o100755 if executable else 0o100644) << 16
                    content = source.read_bytes()
                    if source.suffix == ".cmd":
                        content = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                    archive.writestr(entry, content)
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"Corrupt output archive: {path.name}")
                expected = release["uv_binaries"][platform]
                binary = archive.read(f"{name}/{expected['file']}")
                if hashlib.sha256(binary).hexdigest() != expected["sha256"]:
                    raise ValueError(f"Output binary checksum mismatch: {platform}")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            (staged / f"{path.name}.sha256").write_text(f"{checksum}  {path.name}\n", encoding="ascii")
            artifacts.append({"file": path.name, "bytes": path.stat().st_size, "sha256": checksum})
        (staged / "artifacts.json").write_text(
            json.dumps({"version": release["version"], "artifacts": artifacts}, indent=2) + "\n",
            encoding="utf-8",
        )
        # A failed build cannot publish a partial set of newly generated packages.
        for path in staged.iterdir():
            os.replace(path, output / path.name)
    return artifacts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PLATFORMS, action="append")
    args = parser.parse_args()
    print(json.dumps(build(platforms=tuple(args.platform) if args.platform else PLATFORMS), indent=2))
