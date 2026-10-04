"""Check platform-source selection without claiming native Windows acceptance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import windows_installer_smoke as smoke

VERSION = "0.5.0b1"
REVISION = "1" * 40
NAME = f"PersonalKB-{VERSION}-windows-x64.zip"
RELEASE = {"version": VERSION}
PAYLOAD = b"synthetic committed payload; no executable or credentials"


def package(directory: Path, *, members: dict[str, bytes] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / NAME
    if members is None:
        members = {
            f"{archive.stem}/installer/release.json": json.dumps(RELEASE).encode(),
            f"{archive.stem}/payload.txt": PAYLOAD,
        }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
        for name, content in members.items():
            zipped.writestr(name, content)
    write_integrity(archive)
    return archive


def write_integrity(archive: Path) -> dict:
    artifact = {
        "file": archive.name,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "bytes": archive.stat().st_size,
    }
    archive.with_name(archive.name + ".sha256").write_text(
        f"{artifact['sha256']}  {archive.name}\n", encoding="ascii"
    )
    (archive.parent / "artifacts.json").write_text(
        json.dumps({"version": VERSION, "artifacts": [artifact]}), encoding="utf-8"
    )
    return artifact


@pytest.fixture
def context(tmp_path: Path, monkeypatch):
    root = tmp_path / "checked-out-source"
    root.mkdir()
    (root / "payload.txt").write_bytes(b"working tree must not enter the candidate")
    work = tmp_path / "work 中文"
    work.mkdir()
    monkeypatch.setattr(smoke, "ROOT", root)
    exported = []
    built = []

    def archive_revision(command, *, cwd, timeout):
        assert command[:3] == ["git", "archive", "--format=zip"]
        assert command[-1] == REVISION
        assert cwd == root and timeout == 120
        archive = Path(command[3].removeprefix("--output="))
        assert archive.parent == work
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("payload.txt", PAYLOAD)
        exported.append(REVISION)
        return subprocess.CompletedProcess(command, 0, "")

    def build_candidate(*, root, output, platforms):
        assert root == work / "源码 ZIP"
        assert root != smoke.ROOT
        assert (root / "payload.txt").read_bytes() == PAYLOAD
        assert output == work / "候选平台包"
        assert platforms == ("windows-x64",)
        built.append(root)
        package(output)

    monkeypatch.setattr(smoke, "run", archive_revision)
    monkeypatch.setattr(smoke, "build", build_candidate)
    return root, work, root / "preview-releases" / VERSION, exported, built


def test_absent_release_builds_and_validates_only_the_requested_revision(context):
    root, work, release_directory, exported, built = context
    info = {}
    source = smoke.prepare_source("platform-zip", work, RELEASE, REVISION, artifact_info=info)
    assert (source / "payload.txt").read_bytes() == PAYLOAD
    assert source == work / "平台 ZIP" / Path(NAME).stem
    assert exported == [REVISION] and built == [work / "源码 ZIP"]
    assert not release_directory.exists()
    assert (root / "payload.txt").read_bytes() != PAYLOAD
    archive = work / "候选平台包" / NAME
    assert info == {
        "source": "source_build",
        "version": VERSION,
        "file": NAME,
        "sha256": smoke.digest(archive),
        "bytes": archive.stat().st_size,
    }


def test_existing_complete_release_uses_original_archive(context):
    _, work, release_directory, exported, built = context
    archive = package(release_directory)
    before = archive.read_bytes()
    info = {}
    source = smoke.prepare_source("platform-zip", work, RELEASE, REVISION, artifact_info=info)
    assert (source / "payload.txt").read_bytes() == PAYLOAD
    assert not exported and not built
    assert archive.read_bytes() == before
    assert info == {
        "source": "existing_release",
        "version": VERSION,
        "file": NAME,
        "sha256": smoke.digest(archive),
        "bytes": len(before),
    }


@pytest.mark.parametrize("missing", [NAME, NAME + ".sha256", "artifacts.json", "all"])
def test_incomplete_existing_directory_never_falls_back(context, missing):
    _, work, release_directory, exported, built = context
    if missing == "all":
        release_directory.mkdir(parents=True)
    else:
        package(release_directory)
        (release_directory / missing).unlink()
    with pytest.raises(FileNotFoundError):
        smoke.prepare_source("platform-zip", work, RELEASE, REVISION)
    assert not exported and not built


@pytest.mark.parametrize("bad_checksum", ["0" * 64 + "  " + NAME, "0" * 64 + "  other.zip"])
def test_bad_checksum_never_falls_back(context, bad_checksum):
    _, work, release_directory, exported, built = context
    archive = package(release_directory)
    archive.with_name(NAME + ".sha256").write_text(bad_checksum, encoding="ascii")
    with pytest.raises(smoke.SmokeFailure, match="checksum"):
        smoke.prepare_source("platform-zip", work, RELEASE, REVISION)
    assert not exported and not built


@pytest.mark.parametrize("change", ["version", "missing", "duplicate", "sha256", "bytes", "json"])
def test_bad_manifest_never_falls_back(context, change):
    _, work, release_directory, exported, built = context
    package(release_directory)
    manifest = release_directory / "artifacts.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if change == "version":
        data["version"] = "0.0.0"
    elif change == "missing":
        data["artifacts"] = []
    elif change == "duplicate":
        data["artifacts"] *= 2
    elif change in ("sha256", "bytes"):
        data["artifacts"][0][change] = "0" * 64 if change == "sha256" else 1
    manifest.write_text("{" if change == "json" else json.dumps(data), encoding="utf-8")
    with pytest.raises((smoke.SmokeFailure, json.JSONDecodeError)):
        smoke.prepare_source("platform-zip", work, RELEASE, REVISION)
    assert not exported and not built


def test_build_failure_propagates(context, monkeypatch):
    _, work, release_directory, exported, _ = context
    failure = ValueError("synthetic build failure")

    def fail(**kwargs):
        raise failure

    monkeypatch.setattr(smoke, "build", fail)
    with pytest.raises(ValueError) as caught:
        smoke.prepare_source("platform-zip", work, RELEASE, REVISION)
    assert caught.value is failure
    assert exported == [REVISION] and not release_directory.exists()
    assert not (work / "平台 ZIP").exists()


def test_generated_candidate_must_pass_the_same_manifest_validation(context, monkeypatch):
    _, work, _, _, _ = context

    def corrupt_build(*, root, output, platforms):
        package(output)
        (output / "artifacts.json").write_text('{"version":"wrong","artifacts":[]}', encoding="utf-8")

    monkeypatch.setattr(smoke, "build", corrupt_build)
    with pytest.raises(smoke.SmokeFailure, match="manifest"):
        smoke.prepare_source("platform-zip", work, RELEASE, REVISION)


@pytest.mark.parametrize("damage", ["crc", "escape", "missing-root"])
def test_zip_content_checks_still_reject_invalid_archives(context, damage):
    _, work, release_directory, exported, built = context
    if damage == "crc":
        archive = package(release_directory)
        content = archive.read_bytes()
        assert content.count(PAYLOAD) == 1
        archive.write_bytes(content.replace(PAYLOAD, b"X" + PAYLOAD[1:]))
        write_integrity(archive)
    else:
        name = "../escape.txt" if damage == "escape" else "wrong-root/payload.txt"
        package(release_directory, members={name: PAYLOAD})
    with pytest.raises((smoke.SmokeFailure, zipfile.BadZipFile)):
        smoke.prepare_source("platform-zip", work, RELEASE, REVISION)
    assert not exported and not built
    assert not (work / "escape.txt").exists()


def test_dangling_version_symlink_is_not_an_absent_release(context):
    _, work, release_directory, exported, built = context
    release_directory.parent.mkdir(parents=True)
    try:
        release_directory.symlink_to(work / "absent", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Platform does not permit a synthetic directory symlink")
    with pytest.raises(FileNotFoundError):
        smoke.prepare_source("platform-zip", work, RELEASE, REVISION)
    assert not exported and not built
