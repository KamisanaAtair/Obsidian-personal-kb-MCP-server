"""Build deterministic platform ZIPs from an explicit, credential-free payload."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.bootstrap import payload_files  # noqa: E402


def build():
    release = json.loads((ROOT / "installer/release.json").read_text())
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    artifacts = []
    for platform in ("windows-x64", "macos-arm64"):
        name = f"PersonalKB-{release['version']}-{platform}"
        path = output / f"{name}.zip"
        files = list(payload_files(ROOT)) + [ROOT / "README-FIRST.md"]
        files += [
            ROOT / relative
            for relative in (
                "docs/SETUP_FROM_ZIP.md",
                "docs/workbuddy.md",
                "docs/HOST_USAGE.md",
                "docs/LEGACY_STDIO.md",
                "personal-kb-mcp-setup/SKILL.md",
            )
        ]
        with zipfile.ZipFile(
            path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for source in sorted(set(files)):
                relative = source.relative_to(ROOT)
                if (
                    relative.parts[:2] == ("installer", "vendor")
                    and relative.parts[2] != platform
                ):
                    continue
                if source.is_symlink():
                    raise ValueError("Package source cannot be a symlink")
                entry = zipfile.ZipInfo(
                    f"{name}/{relative.as_posix()}", (2026, 9, 28, 0, 0, 0)
                )
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                executable = source.name in {"install.command", "install.sh", "uv"}
                entry.external_attr = (0o100755 if executable else 0o100644) << 16
                content = source.read_bytes()
                if source.suffix == ".cmd":
                    content = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                archive.writestr(entry, content)
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        (output / f"{path.name}.sha256").write_text(
            f"{checksum}  {path.name}\n", encoding="ascii"
        )
        artifacts.append(
            {"file": path.name, "bytes": path.stat().st_size, "sha256": checksum}
        )
    (output / "artifacts.json").write_text(
        json.dumps({"version": release["version"], "artifacts": artifacts}, indent=2)
        + "\n"
    )
    print(json.dumps(artifacts, indent=2))


if __name__ == "__main__":
    build()
