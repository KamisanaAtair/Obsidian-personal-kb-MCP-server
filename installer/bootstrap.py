"""Standard-library bootstrap for the downloadable, per-user installation.

Run by the bundled uv, not by a globally installed Python. No personal Vault is
inspected and no WorkBuddy configuration is changed here: registration is a
separate action in the local interface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

SOURCE_ROOT = Path(__file__).resolve().parent.parent
PAYLOAD_DIRS = ("config", "core", "mcp_server", "local_app", "installer")
PAYLOAD_FILES = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "install.cmd",
    "install.command",
    "install.sh",
)
EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "tests",
    "tests_local",
    "project-memory",
    ".pytest_cache",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".env"}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class InstallError(RuntimeError):
    pass


def application_home() -> Path:
    override = os.environ.get("PERSONAL_KB_HOME")
    if override:
        return Path(override).expanduser().absolute()
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            / "PersonalKB"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PersonalKB"
    return (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        / "PersonalKB"
    )


def platform_key() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        if int(platform.mac_ver()[0].split(".")[0]) < 14:
            raise InstallError(
                "This preview requires macOS 14 or later on Apple Silicon."
            )
        return "macos-arm64"
    if sys.platform.startswith("linux") and machine in {"x86_64", "amd64"}:
        return "linux-x64"
    raise InstallError(
        f"This preview does not include a runtime for {sys.platform}/{machine}."
    )


def uv_path(root: Path) -> Path:
    filename = "uv.exe" if sys.platform == "win32" else "uv"
    path = root / "installer" / "vendor" / platform_key() / filename
    if not path.is_file():
        raise InstallError(
            "Bundled uv is missing. Extract the complete installation ZIP before running it."
        )
    return path


def read_json(path: Path, default: dict | None = None) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(value, dict):
            return value
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return {} if default is None else default


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def process_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: conservatively alive
        try:
            result = wintypes.DWORD()
            return (
                bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(result)))
                and result.value == 259
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def installation_lock(home: Path):
    """One bootstrap writer; recover only an identified, no-longer-live owner."""
    home.mkdir(parents=True, exist_ok=True)
    lock = home / "installation.lock"
    owner = {"pid": os.getpid(), "id": uuid4().hex, "created": time.time()}
    for attempt in range(2):
        try:
            fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            old = read_json(lock)
            if not old or process_is_alive(old.get("pid")):
                raise InstallError(
                    "Another installation is running. Wait for its window to finish."
                ) from None
            # Recheck its bytes to avoid deleting a replacement lock.
            if read_json(lock) == old and attempt == 0:
                lock.unlink(missing_ok=True)
                continue
            raise InstallError(
                "Installation lock changed; retry in a moment."
            ) from None
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(owner, stream)
            break
    try:
        yield
    finally:
        if read_json(lock).get("id") == owner["id"]:
            lock.unlink(missing_ok=True)


def payload_files(source: Path):
    """Explicit payload allowlist: no user data, repository history or reports."""
    for filename in PAYLOAD_FILES:
        path = source / filename
        if path.is_file() and not path.is_symlink():
            yield path
    for dirname in PAYLOAD_DIRS:
        directory = source / dirname
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(source)
            if any(
                part in EXCLUDED_DIRS or part.startswith(".") for part in relative.parts
            ):
                continue
            if any(
                parent.is_symlink()
                for parent in (path, *path.parents)
                if parent != source.parent
            ):
                continue
            if not path.is_file() or path.suffix in EXCLUDED_SUFFIXES:
                continue
            if path.name in {
                "secrets.env",
                "service.json",
                "auth.json",
                "install-state.json",
            }:
                continue
            yield path


def payload_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in payload_files(source):
        digest.update(path.relative_to(source).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def copy_payload(source: Path, destination: Path) -> None:
    for original in payload_files(source):
        target = destination / original.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)


def runtime_python(runtime: Path) -> Path:
    return (
        runtime
        / ".venv"
        / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )


def runtime_environment(home: Path, runtime: Path, uv: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "PERSONAL_KB_HOME": str(home),
            "PERSONAL_KB_UV": str(uv),
            "UV_PYTHON_INSTALL_DIR": str(home / "python"),
            "UV_CACHE_DIR": str(home / "cache" / "uv"),
            "UV_PYTHON_DOWNLOADS": "automatic",
            "UV_MANAGED_PYTHON": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
            "PATH": str(runtime_python(runtime).parent)
            + os.pathsep
            + env.get("PATH", ""),
        }
    )
    if env.get("PERSONAL_KB_INDEX_URL"):
        env["UV_INDEX_URL"] = env["PERSONAL_KB_INDEX_URL"]
    return env


def run_step(
    command: list[str], cwd: Path, env: dict[str, str], timeout: int = 1800
) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise InstallError(
            "This installation step timed out. Reopen the installer to resume cached downloads."
        ) from exc
    except OSError as exc:
        raise InstallError(
            "Could not launch a bundled installation component."
        ) from exc
    if result.returncode:
        raise InstallError(
            "A dependency step failed. Check your connection, then reopen the installer to continue."
        )


def check_runtime(runtime: Path, env: dict[str, str], python_version: str) -> bool:
    python = runtime_python(runtime)
    if not python.is_file():
        return False
    code = (
        "import sys, importlib; "
        f"assert '.'.join(map(str, sys.version_info[:3])) == {python_version!r}; "
        "import mcp, pydantic_settings, yaml; importlib.import_module('local_app.server')"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", code],
            cwd=runtime / "app",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def write_persistent_launcher(home: Path, runtime: Path) -> Path:
    """Keep a user-local entry point after the downloaded folder is removed."""
    relative = (runtime / "app").relative_to(home).as_posix()
    if sys.platform == "win32":
        target = home / "Open Personal KB.cmd"
        relative = relative.replace("/", "\\")
        content = (
            "@echo off\r\nsetlocal DisableDelayedExpansion\r\n"
            'set "PERSONAL_KB_HOME=%~dp0"\r\n'
            f'"%~dp0{relative}\\install.cmd" %*\r\n'
        )
    else:
        target = home / (
            "Open Personal KB.command"
            if sys.platform == "darwin"
            else "Open Personal KB.sh"
        )
        content = (
            "#!/bin/sh\n"
            'PERSONAL_KB_HOME=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1\n'
            "export PERSONAL_KB_HOME\n"
            f'exec /bin/sh "$PERSONAL_KB_HOME/{relative}/install.sh" "$@"\n'
        )
    fd, temporary = tempfile.mkstemp(prefix=".launcher.", dir=str(home))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.chmod(temporary, 0o700)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def prepare_runtime(source: Path, home: Path) -> tuple[Path, dict, dict[str, str]]:
    release = read_json(source / "installer" / "release.json")
    version = release.get("version")
    python_version = release.get("python")
    if (
        not isinstance(version, str)
        or not version
        or any(
            c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-"
            for c in version
        )
    ):
        raise InstallError("The installation archive has an invalid release manifest.")
    if python_version != "3.11.15" or release.get("uv") != "0.12.12":
        raise InstallError(
            "This installer needs its matching Python/uv release manifest."
        )
    digest = payload_digest(source)
    runtime = home / "versions" / f"{version}-{digest[:12]}"
    app = runtime / "app"
    marker = runtime / "ready.json"
    app.mkdir(parents=True, exist_ok=True)
    # A verified version is immutable. Reopening does not recopy its payload or
    # overwrite files that a still-running service may have imported.
    ready = read_json(marker)
    if ready.get("payload_sha256") != digest:
        copy_payload(source, app)
    uv = uv_path(app)
    if sys.platform != "win32":
        uv.chmod(0o755)
    env = runtime_environment(home, runtime, uv)
    env["PERSONAL_KB_PAYLOAD_SHA256"] = digest
    state = {"version": version, "payload_sha256": digest, "runtime": str(runtime)}

    def phase(name: str):
        atomic_json(
            home / "install-state.json",
            {**state, "phase": name, "updated": time.time()},
        )

    if ready.get("payload_sha256") == digest and check_runtime(
        runtime, env, python_version
    ):
        print("Basic components are already ready.", flush=True)
    else:
        phase("python")
        print("[1/3] Preparing the private Python runtime...", flush=True)
        if not runtime_python(runtime).exists():
            run_step(
                [
                    str(uv),
                    "--no-config",
                    "venv",
                    "--clear",
                    "--python",
                    python_version,
                    str(runtime / ".venv"),
                ],
                app,
                env,
            )
        phase("dependencies")
        print("[2/3] Installing basic components (downloads are cached)...", flush=True)
        lock = app / "installer" / "requirements-base.lock"
        if not lock.is_file():
            raise InstallError(
                "The hashed base requirements are missing from this archive."
            )
        install_command = [
            str(uv),
            "--no-config",
            "pip",
            "install",
            "--python",
            str(runtime_python(runtime)),
            "--require-hashes",
            "-r",
            str(lock),
        ]
        if ready.get("ready"):
            # Verification failed for a previously complete runtime: reinstall
            # pinned base packages from the cache, rather than trusting metadata.
            install_command.append("--reinstall")
        run_step(install_command, app, env)
        phase("checking")
        print("[3/3] Checking the installed components...", flush=True)
        if not check_runtime(runtime, env, python_version):
            raise InstallError(
                "Basic runtime verification failed; the previous installation remains available."
            )
        atomic_json(marker, {**state, "ready": True, "verified": time.time()})
    # Do not point to a new version until its import/version checks have passed.
    atomic_json(
        home / "active.json",
        {**state, "python": str(runtime_python(runtime)), "app": str(app)},
    )
    write_persistent_launcher(home, runtime)
    phase("ready")
    return runtime, release, env


def health(port: int) -> dict:
    try:
        request = Request(
            f"http://127.0.0.1:{port}/health", headers={"Accept": "application/json"}
        )
        with urlopen(request, timeout=1) as response:
            value = json.loads(response.read(65536))
        return value if isinstance(value, dict) else {}
    except (OSError, URLError, ValueError):
        return {}


def known_service(
    data: Path,
    port: int,
    version: str,
    payload_sha256: str | None = None,
    *,
    expected_launch_id: str | None = None,
) -> dict | None:
    record = read_json(data / "service.json")
    if (
        record.get("port") != port
        or not record.get("instance_id")
        or not process_is_alive(record.get("pid"))
    ):
        return None
    current = health(port)
    if expected_launch_id is not None and (
        len(expected_launch_id) != 32
        or any(c not in "0123456789abcdef" for c in expected_launch_id)
        or record.get("launch_id") != expected_launch_id
        or current.get("launch_id") != expected_launch_id
    ):
        return None
    if payload_sha256 and (
        record.get("payload_sha256") != payload_sha256
        or current.get("payload_sha256") != payload_sha256
    ):
        return None
    if (
        current.get("instance_id") == record["instance_id"]
        and current.get("version") == record.get("version") == version
    ):
        return record
    return None


def port_in_use(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def start_service(runtime: Path, home: Path, release: dict, env: dict[str, str], port: int) -> dict:
    data = home / "data"
    data.mkdir(parents=True, exist_ok=True)
    existing = known_service(data, port, release["version"], env.get("PERSONAL_KB_PAYLOAD_SHA256"))
    if existing:
        return existing
    if port_in_use(port):
        raise InstallError(
            f"Port {port} is already in use. Close the previous Personal KB service or choose another port with --port."
        )
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    options: dict = (
        {"start_new_session": True}
        if sys.platform != "win32"
        else {
            "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    )
    command = [
        str(runtime_python(runtime)),
        "-m",
        "local_app.server",
        "--data-dir",
        str(data),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-browser",
    ]
    log_path = logs / "service.log"
    # Windows venv launchers may create a child interpreter with another PID.
    # Bind readiness to this launch without weakening the existing identity checks.
    launch_id = uuid4().hex
    child_env = {**env, "PERSONAL_KB_LAUNCH_ID": launch_id}
    with log_path.open("ab") as log:
        if sys.platform != "win32":
            log_path.chmod(0o600)
        process = subprocess.Popen(
            command,
            cwd=runtime / "app",
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            **options,
        )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise InstallError(f"The local service exited during startup. See {log_path}")
        record = known_service(
            data,
            port,
            release["version"],
            env.get("PERSONAL_KB_PAYLOAD_SHA256"),
            expected_launch_id=launch_id,
        )
        if record:
            return record
        time.sleep(0.25)
    # Never kill a PID obtained from an untrusted/stale status file.
    raise InstallError(
        f"The local service has not become ready yet. Reopen the installer to check again. Log: {log_path}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install and open the local Personal KB interface."
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Install and verify without launching a service.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the service without opening a browser.",
    )
    parser.add_argument("--port", type=int, default=32123)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    home = application_home()
    try:
        with installation_lock(home):
            runtime, release, env = prepare_runtime(SOURCE_ROOT, home)
            if args.prepare_only:
                print(
                    "Basic installation is ready. No service was started.", flush=True
                )
                return 0
            service = start_service(runtime, home, release, env, args.port)
            auth = read_json(home / "data" / "auth.json")
            token = auth.get("ui_token")
            if not isinstance(token, str) or not token:
                raise InstallError(
                    "The local service has not created its interface credentials; reopen the installer."
                )
            url = f"http://127.0.0.1:{service['port']}/#{quote(token, safe='')}"
            print(
                "Personal KB is running locally. The browser interface manages optional features and the WorkBuddy connection.",
                flush=True,
            )
            print(
                "No notebook folder is required during installation. You can close this terminal window.",
                flush=True,
            )
            if not args.no_browser and not webbrowser.open(url):
                raise InstallError(
                    "Could not open your default browser. Set a default browser and reopen the installer."
                )
        return 0
    except (InstallError, OSError) as exc:
        print(f"Installation paused: {exc}", file=sys.stderr, flush=True)
        print(
            "Your existing runtime and downloaded cache are retained. Reopen this installer to resume.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    except KeyboardInterrupt:
        print("Installation paused. Reopen the installer to resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
