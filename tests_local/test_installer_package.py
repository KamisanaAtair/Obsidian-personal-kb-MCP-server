"""Exercise actual ZIP creation and refusal, using synthetic local payloads only.

The fixture's uv bytes are deliberately not executable. These tests verify the
packaging contract and do not claim native Windows installation coverage.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_installer import build

VERSION = "0.4.0b2"
WINDOWS_UV = "installer/vendor/windows-x64/uv.exe"
MAC_UV = "installer/vendor/macos-arm64/uv"


def put(root: Path, relative: str, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "source with 空格"
    for relative in (
        "README.md",
        "README-FIRST.md",
        "LICENSE",
        "installer/bootstrap.py",
        "installer/model-manifest.json",
        "installer/requirements-base.lock",
        "installer/requirements-video.lock",
        "installer/requirements-semantic.lock",
        "installer/third_party/NOTICE.md",
        "installer/third_party/uv-LICENSE-MIT",
        "installer/third_party/uv-LICENSE-APACHE",
        "local_app/server.py",
        "local_app/static/index.html",
        "local_app/static/app.js",
        "local_app/static/style.css",
        "docs/SETUP_FROM_ZIP.md",
        "docs/workbuddy.md",
        "docs/HOST_USAGE.md",
        "docs/LEGACY_STDIO.md",
        "docs/video-notes.md",
        "personal-kb-mcp-setup/SKILL.md",
    ):
        put(root, relative, b"Synthetic package test fixture; no real credentials.\n")
    put(root, "install.cmd", b"@echo off\necho synthetic only\r\nexit /b 0\n")
    put(root, "install.command", b"#!/bin/sh\nprintf 'synthetic only\\n'\n")
    put(root, "install.sh", b"#!/bin/sh\nprintf 'synthetic only\\n'\n")
    put(root, "pyproject.toml", f'[project]\nname = "synthetic"\nversion = "{VERSION}"\n'.encode())
    put(root, "local_app/__init__.py", f'__version__ = "{VERSION}"\n'.encode())
    binaries = {}
    for platform, relative in (("windows-x64", WINDOWS_UV), ("macos-arm64", MAC_UV)):
        content = f"NOT EXECUTABLE: synthetic uv bytes for {platform}\n".encode()
        put(root, relative, content)
        binaries[platform] = {
            "file": relative,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    release = {"version": VERSION, "python": "3.11.15", "uv": "0.12.12", "uv_binaries": binaries}
    put(root, "installer/release.json", (json.dumps(release) + "\n").encode())
    return root


def files_snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def change_release(source: Path, edit) -> None:
    path = source / "installer/release.json"
    release = json.loads(path.read_text())
    edit(release)
    path.write_text(json.dumps(release), encoding="utf-8")


def test_windows_zip_contains_required_launch_payload_and_crlf(source: Path, tmp_path: Path):
    output = tmp_path / "artifacts"
    artifacts = build(root=source, output=output, platforms=("windows-x64",))
    name = f"PersonalKB-{VERSION}-windows-x64"
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["file"] == f"{name}.zip"
    archive_path = output / artifact["file"]
    assert artifact["bytes"] == archive_path.stat().st_size
    assert artifact["sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert (output / f"{name}.zip.sha256").read_text().split() == [
        artifact["sha256"],
        artifact["file"],
    ]
    assert json.loads((output / "artifacts.json").read_text()) == {
        "version": VERSION,
        "artifacts": artifacts,
    }
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert archive.read(f"{name}/{WINDOWS_UV}") == (source / WINDOWS_UV).read_bytes()
        assert all("/installer/vendor/macos-arm64/" not in item for item in archive.namelist())
        for relative in (
            "installer/bootstrap.py",
            "installer/release.json",
            "installer/requirements-base.lock",
            "installer/requirements-video.lock",
            "installer/requirements-semantic.lock",
            "installer/third_party/NOTICE.md",
            "installer/third_party/uv-LICENSE-MIT",
            "installer/third_party/uv-LICENSE-APACHE",
            "local_app/server.py",
            "local_app/static/app.js",
            "README-FIRST.md",
            "docs/SETUP_FROM_ZIP.md",
        ):
            assert archive.read(f"{name}/{relative}") == (source / relative).read_bytes()
        assert archive.read(f"{name}/install.cmd") == (
            b"@echo off\r\necho synthetic only\r\nexit /b 0\r\n"
        )


@pytest.mark.parametrize("missing", [WINDOWS_UV, "installer/bootstrap.py", "install.cmd"])
def test_missing_launch_component_cannot_create_any_artifacts(
    source: Path, tmp_path: Path, missing: str
):
    (source / missing).unlink()
    output = tmp_path / "not-yet-created"
    with pytest.raises(ValueError):
        build(root=source, output=output, platforms=("windows-x64",))
    assert files_snapshot(output) == {}


def test_binary_tampered_at_same_size_is_rejected(source: Path, tmp_path: Path):
    binary = source / WINDOWS_UV
    content = binary.read_bytes()
    binary.write_bytes(b"X" + content[1:])
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        build(root=source, output=output, platforms=("windows-x64",))
    assert files_snapshot(output) == {}


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("bytes", 1)])
def test_manifest_binary_integrity_mismatch_is_rejected(
    source: Path, tmp_path: Path, field: str, value
):
    change_release(
        source, lambda release: release["uv_binaries"]["windows-x64"].update({field: value})
    )
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        build(root=source, output=output, platforms=("windows-x64",))
    assert files_snapshot(output) == {}


def test_failed_rebuild_preserves_existing_packages_and_checksums(source: Path, tmp_path: Path):
    output = tmp_path / "artifacts"
    build(root=source, output=output, platforms=("windows-x64",))
    before = files_snapshot(output)
    assert any(name.endswith(".zip") for name in before)
    (source / WINDOWS_UV).unlink()
    with pytest.raises(ValueError):
        build(root=source, output=output, platforms=("windows-x64",))
    assert files_snapshot(output) == before


def test_all_selected_platforms_are_validated_before_first_zip(source: Path, tmp_path: Path):
    (source / MAC_UV).unlink()
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        build(root=source, output=output, platforms=("windows-x64", "macos-arm64"))
    assert files_snapshot(output) == {}


def test_missing_unselected_platform_does_not_block_windows_package(source: Path, tmp_path: Path):
    for relative in (MAC_UV, "install.command", "install.sh"):
        (source / relative).unlink()
    output = tmp_path / "artifacts"
    artifacts = build(root=source, output=output, platforms=("windows-x64",))
    assert len(artifacts) == 1
    with zipfile.ZipFile(output / artifacts[0]["file"]) as archive:
        assert archive.testzip() is None
        assert all("/installer/vendor/macos-arm64/" not in item for item in archive.namelist())


@pytest.mark.parametrize("relative", ["pyproject.toml", "local_app/__init__.py"])
def test_inconsistent_source_version_is_rejected(source: Path, tmp_path: Path, relative: str):
    path = source / relative
    path.write_text(path.read_text().replace(VERSION, "0.0.0"), encoding="utf-8")
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        build(root=source, output=output, platforms=("windows-x64",))
    assert files_snapshot(output) == {}


@pytest.mark.parametrize("relative", [WINDOWS_UV, "installer/bootstrap.py"])
def test_symlinked_required_file_is_rejected(source: Path, tmp_path: Path, relative: str):
    path = source / relative
    external = tmp_path / "external-source"
    path.replace(external)
    try:
        path.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Platform does not permit test symlinks")
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        build(root=source, output=output, platforms=("windows-x64",))
    assert files_snapshot(output) == {}
