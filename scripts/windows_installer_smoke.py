"""Run the real Windows installer in an isolated home; never register WorkBuddy.

The driver uses only the standard library. Its MCP subcommand is executed by
the installed runtime and therefore exercises the shipped, pinned MCP SDK.
Only a sanitized summary is printed; installation homes and logs are private
test inputs, not upload artifacts. This is not desktop/WorkBuddy UI acceptance.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from ctypes import wintypes
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

if __package__:
    from .build_installer import build
else:
    from build_installer import build

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "get_status",
    "ingest_content",
    "ingest_content_prepare",
    "ingest_content_finalize",
    "start_index",
    "query_kb",
    "trigger_correlation",
    "get_job",
    "retry_job",
    "prepare_feature",
}
SECRETS: set[str] = set()
OPENER = build_opener(ProxyHandler({}))


class SmokeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def sanitized(value: str) -> str:
    for secret in sorted(SECRETS, key=len, reverse=True):
        value = value.replace(secret, "[redacted]")
    value = re.sub(r"(?i)Bearer\s+[^\s\"'<>]+", "Bearer [redacted]", value)
    value = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", value)
    return value[-12000:]


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), "Expected a JSON object")
    return value


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(
    command, *, cwd: Path, env: dict | None = None, timeout=1800, expect_success=True
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure("Command exceeded its deadline") from exc
    if expect_success and result.returncode:
        raise SmokeFailure(f"Command exited with {result.returncode}: {sanitized(result.stdout)}")
    return result


def cmd(
    entry: Path, arguments: list[str], env: dict, *, timeout=1800, expect_success=True
) -> subprocess.CompletedProcess:
    require(
        all(re.fullmatch(r"[a-zA-Z0-9-]+", arg) for arg in arguments), "Unexpected cmd argument"
    )
    shell = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    # A raw Windows command line avoids list2cmdline's C-runtime escaping of
    # quotes, which is inappropriate for cmd.exe's own /s /c parsing rules.
    command = f'"{shell}" /d /s /c ""{entry}" {" ".join(arguments)}"'
    return run(command, cwd=entry.parent, env=env, timeout=timeout, expect_success=expect_success)


def extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            target = (destination / entry.filename).resolve()
            require(
                target.is_relative_to(destination.resolve()),
                "ZIP member escapes its extraction directory",
            )
            require((entry.external_attr >> 16) & 0o170000 != 0o120000, "ZIP contains a symlink")
        zipped.extractall(destination)


def prepare_source(
    case: str, work: Path, release: dict, revision: str, *, artifact_info: dict | None = None
) -> Path:
    if case == "checkout":
        source = work / "源码 检出"
        run(
            ["git", "clone", "--no-hardlinks", "--no-checkout", str(ROOT), str(source)],
            cwd=work,
            timeout=120,
        )
        run(["git", "checkout", "--detach", revision], cwd=source, timeout=120)
        require(
            not run(["git", "status", "--porcelain"], cwd=source).stdout.strip(),
            "Cloned worktree is not clean",
        )
        return source
    if case == "source-zip":
        archive = work / "源码.zip"
        run(
            ["git", "archive", "--format=zip", f"--output={archive}", revision],
            cwd=ROOT,
            timeout=120,
        )
        source = work / "源码 ZIP"
        extract(archive, source)
        return source
    name = f"PersonalKB-{release['version']}-windows-x64.zip"
    release_directory = ROOT / "preview-releases" / release["version"]
    artifact_source = "existing_release"
    # An existing but incomplete release must fail its integrity checks. Only a
    # wholly absent version gets a temporary candidate built from this revision.
    if not os.path.lexists(release_directory):
        candidate_source = prepare_source("source-zip", work, release, revision)
        release_directory = work / "候选平台包"
        build(root=candidate_source, output=release_directory, platforms=("windows-x64",))
        artifact_source = "source_build"
    archive = release_directory / name
    checksum = archive.with_name(name + ".sha256").read_text(encoding="ascii").split()
    require(
        len(checksum) == 2 and checksum[1] == name,
        "Platform ZIP checksum file does not name the selected archive",
    )
    require(digest(archive) == checksum[0], "Platform ZIP checksum mismatch")
    artifacts = read_json(archive.parent / "artifacts.json")
    candidates = [item for item in artifacts.get("artifacts", []) if item["file"] == name]
    require(
        artifacts.get("version") == release["version"] and len(candidates) == 1,
        "Platform ZIP is absent from the release artifacts manifest",
    )
    require(
        candidates[0]["sha256"] == checksum[0] and candidates[0]["bytes"] == archive.stat().st_size,
        "Platform ZIP differs from the release artifacts manifest",
    )
    destination = work / "平台 ZIP"
    extract(archive, destination)
    source = destination / archive.stem
    require(source.is_dir(), "Platform ZIP root directory is missing")
    if artifact_info is not None:
        artifact_info.update(
            source=artifact_source,
            version=release["version"],
            file=name,
            sha256=checksum[0],
            bytes=archive.stat().st_size,
        )
    return source


def http(port: int, path: str, token: str | None = None, *, method="GET"):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if method == "POST":
        headers["Content-Type"] = "application/json"
        data = b"{}"
    request = Request(f"http://127.0.0.1:{port}{path}", headers=headers, data=data, method=method)
    try:
        with OPENER.open(request, timeout=10) as response:
            return response.status, response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        return exc.code, exc.read(2 * 1024 * 1024)


def process_alive(pid: int) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5
    try:
        status = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(status))) and status.value == 259
    finally:
        kernel.CloseHandle(handle)


def probe_runtime_process(python: Path, app: Path, env: dict) -> dict:
    """Observe the actual Windows launcher/interpreter relationship, without mocks."""
    code = (
        "import json, os; print(json.dumps({'interpreter_pid': os.getpid(), "
        "'interpreter_ppid': os.getppid()}), flush=True)"
    )
    process = subprocess.Popen(
        [str(python), "-c", code],
        cwd=app,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        encoding="utf-8",
        errors="replace",
    )
    try:
        output, _ = process.communicate(timeout=20)
    except subprocess.TimeoutExpired as exc:
        # This is the direct handle of our short-lived synthetic probe, never
        # a service PID recovered from a state file.
        process.kill()
        process.communicate(timeout=10)
        raise SmokeFailure("Installed interpreter PID probe timed out") from exc
    require(process.returncode == 0, "Installed interpreter PID probe failed")
    observed = json.loads(output)
    require(
        all(
            type(observed.get(key)) is int and observed[key] > 0
            for key in ("interpreter_pid", "interpreter_ppid")
        ),
        "Installed interpreter did not return valid PID observations",
    )
    return {
        "launcher_pid": process.pid,
        **observed,
        "pid_differs": process.pid != observed["interpreter_pid"],
        "interpreter_parent_is_launcher": process.pid == observed["interpreter_ppid"],
        "exit_code": process.returncode,
    }


def matching_launch_id(record: dict, health: dict) -> bool:
    value = record.get("launch_id")
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{32}", value)
        and health.get("launch_id") == value
    )


def auth_for(home: Path) -> dict:
    auth = read_json(home / "data" / "auth.json")
    for key in ("token", "ui_token"):
        require(
            isinstance(auth.get(key), str) and len(auth[key]) >= 32,
            "Local authentication material is invalid",
        )
        SECRETS.add(auth[key])
    require(auth["token"] != auth["ui_token"], "UI and MCP tokens must be distinct")
    return auth


def stop_owned_service(home: Path, port: int) -> str:
    record_path = home / "data" / "service.json"
    if not record_path.exists():
        return "NOT_STARTED"
    record = read_json(record_path)
    require(isinstance(record.get("pid"), int) and record["pid"] > 0, "Invalid owned service PID")
    if not process_alive(record["pid"]):
        return "ALREADY_EXITED"
    status, raw = http(port, "/health")
    health = json.loads(raw)
    active = read_json(home / "active.json")
    require(
        status == 200
        and record.get("port") == port
        and health.get("instance_id") == record.get("instance_id")
        and matching_launch_id(record, health)
        and health.get("payload_sha256")
        == active.get("payload_sha256")
        == record.get("payload_sha256"),
        "Refusing to stop a service without matching test ownership",
    )
    auth = auth_for(home)
    status, _ = http(port, "/api/shutdown", auth["ui_token"], method="POST")
    require(status == 200, "Owned service rejected authenticated shutdown")
    deadline = time.monotonic() + 30
    while process_alive(record["pid"]) and time.monotonic() < deadline:
        time.sleep(0.25)
    require(not process_alive(record["pid"]), "Owned service did not exit after shutdown")
    return "AUTHENTICATED_SHUTDOWN"


def failure_service_log(home: Path) -> str | None:
    """Read only the isolated test log after registering its tokens for redaction."""
    try:
        auth_for(home)
        with (home / "logs" / "service.log").open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 12000))
            return sanitized(stream.read(12000).decode("utf-8", errors="replace"))
    except (SmokeFailure, OSError, ValueError, KeyError):
        # Without valid synthetic credentials, suppress the log instead of
        # guessing whether its contents are safe to publish.
        return None


async def mcp_check(home: Path, port: int) -> dict:
    # These imports must happen only in the installed runtime, never the driver.
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    auth = auth_for(home)
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + auth["token"]}, trust_env=False, timeout=20
    ) as transport:
        async with streamable_http_client(
            f"http://127.0.0.1:{port}/mcp", http_client=transport
        ) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                require(names == EXPECTED_TOOLS, "Installed MCP tool set differs")
                status = await session.call_tool("get_status", {})
                require(not status.isError, "MCP get_status failed")
                value = status.structuredContent or json.loads(status.content[0].text)
                require(
                    value["basic_ready"] and value["models"]["generation_mode"] == "host",
                    "Installed MCP returned an unexpected initial state",
                )
                return {"tools": sorted(names), "version": value["version"], "get_status": "PASS"}


def smoke(case: str) -> int:
    require(sys.platform == "win32", "This acceptance driver requires real Windows")
    revision = run(["git", "rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
    require(
        not run(["git", "status", "--porcelain"], cwd=ROOT).stdout.strip(),
        "CI checkout must be clean before accepting its artifacts",
    )
    release = read_json(ROOT / "installer" / "release.json")
    require(
        release["python"] == "3.11.15" and release["uv"] == "0.12.12",
        "Unexpected pinned runtime versions",
    )
    work = Path(tempfile.mkdtemp(prefix="Personal KB 中文 ")).resolve()
    home = work / "独立安装 Home"
    env = dict(os.environ)
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "PERSONAL_KB_INDEX_URL",
        "UV_INDEX",
        "UV_DEFAULT_INDEX",
        "UV_INDEX_URL",
        "UV_EXTRA_INDEX_URL",
    ):
        env.pop(key, None)
    env.update(PERSONAL_KB_HOME=str(home), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    summary = {
        "case": case,
        "commit": revision,
        "version": release["version"],
        "runner": "real Windows",
        "checks": {},
        "desktop_ui_verified": False,
        "workbuddy_native_verified": False,
        "passed": False,
    }
    checks = summary["checks"]
    phase = "source"
    port = 0
    try:
        artifact_info = {}
        source = prepare_source(case, work, release, revision, artifact_info=artifact_info)
        if artifact_info:
            summary["platform_zip"] = artifact_info
        require(
            read_json(source / "installer" / "release.json") == release,
            "Source release manifest differs from the checked-out release",
        )
        uv_spec = release["uv_binaries"]["windows-x64"]
        uv = source / uv_spec["file"]
        require(
            uv.is_file()
            and uv.stat().st_size == uv_spec["bytes"]
            and digest(uv) == uv_spec["sha256"],
            "Bundled uv executable checksum mismatch",
        )
        uv_version = run([str(uv), "--version"], cwd=source, env=env, timeout=20).stdout.strip()
        require(uv_version.split()[:2] == ["uv", release["uv"]], "Bundled uv version differs")
        checks["source_and_uv"] = "PASS"

        phase = "missing-file diagnostics"
        missing = work / "缺少 uv 文件"
        missing.mkdir()
        shutil.copyfile(source / "install.cmd", missing / "install.cmd")
        result = cmd(
            missing / "install.cmd", ["--prepare-only"], env, timeout=20, expect_success=False
        )
        require(
            result.returncode != 0
            and "Missing required file:" in result.stdout
            and str(missing / uv_spec["file"]) in result.stdout,
            "Missing uv must fail promptly with its exact missing path",
        )
        destination = missing / uv_spec["file"]
        destination.parent.mkdir(parents=True)
        shutil.copyfile(uv, destination)
        result = cmd(
            missing / "install.cmd", ["--prepare-only"], env, timeout=20, expect_success=False
        )
        require(
            result.returncode != 0
            and "Missing required file:" in result.stdout
            and str(missing / "installer" / "bootstrap.py") in result.stdout,
            "Missing bootstrap must fail promptly with its exact missing path",
        )
        checks["missing_uv_and_bootstrap"] = "PASS"

        phase = "prepare-only"
        cmd(source / "install.cmd", ["--prepare-only"], env)
        active = read_json(home / "active.json")
        runtime = Path(active["runtime"]).resolve()
        python = Path(active["python"]).resolve()
        app = Path(active["app"]).resolve()
        require(
            runtime.is_relative_to(home)
            and python.is_relative_to(runtime)
            and app.is_relative_to(runtime),
            "Installed paths escaped the isolated home",
        )
        require(
            active["version"] == release["version"] and python.is_file(),
            "Prepared active runtime differs from the release",
        )
        ready = read_json(runtime / "ready.json")
        require(
            ready["ready"] and ready["payload_sha256"] == active["payload_sha256"],
            "Prepared runtime is not verified for its payload",
        )
        require(
            not (home / "data" / "service.json").exists()
            and not (home / "data" / "auth.json").exists(),
            "Prepare-only unexpectedly started the service",
        )
        require(
            digest(app / uv_spec["file"]) == uv_spec["sha256"],
            "Installed uv differs from the verified executable",
        )
        inspect = (
            "import json, sys; from pathlib import Path; from installer.bootstrap import payload_digest; "
            "print(json.dumps({'python': '.'.join(map(str,sys.version_info[:3])), "
            "'base_prefix': sys.base_prefix, "
            "'installed_payload': payload_digest(Path.cwd()), "
            "'source_payload': payload_digest(Path(sys.argv[1]))}))"
        )
        verification = json.loads(
            run([str(python), "-c", inspect, str(source)], cwd=app, env=env, timeout=60).stdout
        )
        require(
            verification["python"] == release["python"]
            and Path(verification["base_prefix"]).resolve().is_relative_to(home / "python")
            and verification["installed_payload"]
            == verification["source_payload"]
            == active["payload_sha256"],
            "Installed Python/payload validation failed",
        )
        checks["real_prepare_only"] = {
            "status": "PASS",
            "python": verification["python"],
            "payload_sha256": active["payload_sha256"],
        }

        phase = "installed interpreter PID probe"
        checks["runtime_process_probe"] = probe_runtime_process(python, app, env)

        phase = "service start"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cmd(source / "install.cmd", ["--no-browser", "--port", str(port)], env, timeout=120)
        record = read_json(home / "data" / "service.json")
        status, raw = http(port, "/health")
        health = json.loads(raw)
        require(
            status == 200
            and health["app"] == "personal-kb"
            and health["version"] == release["version"] == record["version"]
            and health["payload_sha256"] == active["payload_sha256"] == record["payload_sha256"]
            and health["instance_id"] == record["instance_id"]
            and matching_launch_id(record, health)
            and record["port"] == port
            and process_alive(record["pid"]),
            "Health does not identify the prepared test service",
        )
        checks["health"] = "PASS"

        phase = "HTTP interface and authentication"
        for path, marker in (
            ("/", b"Personal KB"),
            ("/assets/app.js", b"/api/status"),
            ("/assets/style.css", b"data-theme"),
        ):
            status, raw = http(port, path)
            require(status == 200 and marker in raw, "Installed UI asset could not be served")
        auth = auth_for(home)
        require(http(port, "/api/status")[0] == 401, "UI API accepted an unauthenticated request")
        require(
            http(port, "/api/status", auth["token"])[0] == 401, "UI API accepted the MCP credential"
        )
        require(http(port, "/mcp", auth["ui_token"])[0] == 401, "MCP accepted the UI credential")
        status, raw = http(port, "/api/status", auth["ui_token"])
        state = json.loads(raw)
        require(
            status == 200
            and state["basic_ready"]
            and state["version"] == release["version"]
            and state["models"]["generation_mode"] == "host"
            and not state["jobs"],
            "Authenticated interface has an unexpected initial state",
        )
        require(
            not (home / "data" / "registration.json").exists(),
            "Installer unexpectedly registered WorkBuddy",
        )
        checks["ui_http_authentication"] = "PASS"

        phase = "installed MCP SDK"
        child = run(
            [
                str(python),
                str(Path(__file__).resolve()),
                "--mcp-home",
                str(home),
                "--port",
                str(port),
            ],
            cwd=app,
            env=env,
            timeout=90,
        )
        mcp = json.loads(child.stdout)
        require(
            mcp.get("version") == release["version"] and mcp.get("get_status") == "PASS",
            "Installed MCP SDK check did not pass",
        )
        checks["installed_mcp"] = mcp

        phase = "persistent launcher"
        source.rename(source.with_name(source.name + " - 已移走"))
        require(not source.exists(), "Original installation source is still accessible")
        launcher = home / "Open Personal KB.cmd"
        require(launcher.is_file(), "Persistent Windows launcher is missing")
        cmd(launcher, ["--no-browser", "--port", str(port)], env, timeout=120)
        reopened = read_json(home / "data" / "service.json")
        status, raw = http(port, "/health")
        reopened_health = json.loads(raw)
        require(
            status == 200
            and reopened["pid"] == record["pid"]
            and reopened["instance_id"] == reopened_health["instance_id"] == record["instance_id"]
            and matching_launch_id(reopened, reopened_health)
            and reopened["launch_id"] == record["launch_id"]
            and reopened_health["payload_sha256"] == active["payload_sha256"]
            and process_alive(record["pid"]),
            "Persistent launcher failed to reuse the same running service",
        )
        checks["persistent_launcher_without_source_same_pid"] = "PASS"
        summary["passed"] = True
    except Exception as exc:
        summary["failed_phase"] = phase
        log = failure_service_log(home)
        if log:
            summary["service_log_tail"] = log
        summary["error"] = sanitized(f"{type(exc).__name__}: {exc}")
    finally:
        if port:
            try:
                cleanup = stop_owned_service(home, port)
                checks["authenticated_shutdown"] = cleanup
                if summary["passed"] and cleanup != "AUTHENTICATED_SHUTDOWN":
                    summary["passed"] = False
                    summary["cleanup_error"] = (
                        "Successful acceptance requires authenticated shutdown and process exit"
                    )
            except (SmokeFailure, OSError, URLError, ValueError, KeyError) as exc:
                summary["passed"] = False
                summary["cleanup_error"] = sanitized(f"{type(exc).__name__}: {exc}")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("checkout", "source-zip", "platform-zip"))
    parser.add_argument("--mcp-home", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.mcp_home:
        try:
            require(args.port is not None and 1024 <= args.port <= 65535, "Invalid MCP test port")
            print(json.dumps(asyncio.run(mcp_check(args.mcp_home, args.port))))
            return 0
        except Exception as exc:
            print(json.dumps({"error": sanitized(f"{type(exc).__name__}: {exc}")}))
            return 1
    require(args.case is not None, "Select an installation source with --case")
    return smoke(args.case)


if __name__ == "__main__":
    raise SystemExit(main())
