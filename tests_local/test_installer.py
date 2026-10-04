"""Installer tests use temporary directories, never the user's host configuration."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from installer import bootstrap, workbuddy


def managed_entry(port: int = 32123) -> dict:
    return {
        "type": "streamableHttp",
        "url": f"http://127.0.0.1:{port}/mcp",
        "headers": {"Authorization": "Bearer synthetic-test-only-not-a-real-token"},
        "description": "Personal KB managed installer 0.3.0b1",
    }


class WorkBuddyMergeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.path = self.root / "workbuddy" / "mcp.json"

    def write(self, value: object, *, bom: bool = False) -> bytes:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if bom:
            raw = b"\xef\xbb\xbf" + raw
        self.path.write_bytes(raw)
        return raw

    def test_create_and_idempotent_without_rewriting(self):
        entry = managed_entry()
        first = workbuddy.merge_config(self.path, entry)
        self.assertTrue(first["saved"])
        self.assertFalse(first["noop"])
        self.assertIsNone(first["backup"])
        before = self.path.read_bytes()
        stat = self.path.stat().st_mtime_ns
        second = workbuddy.merge_config(self.path, entry)
        self.assertTrue(second["noop"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, stat)
        self.assertEqual(set(first), {"saved", "path", "backup", "noop"})

    def test_preserves_unknown_settings_other_servers_bom_and_backup(self):
        other = {"command": "existing-program", "args": ["--value", "中文"]}
        original = {
            "mcpServers": {"other": other},
            "custom": {"nested": [1, True]},
            "trust": ["native-record"],
        }
        raw = self.write(original, bom=True)
        result = workbuddy.merge_config(self.path, managed_entry())
        self.assertEqual(Path(result["backup"]).read_bytes(), raw)
        saved = self.path.read_bytes()
        self.assertTrue(saved.startswith(b"\xef\xbb\xbf"))
        parsed = json.loads(saved.decode("utf-8-sig"))
        self.assertEqual(parsed["mcpServers"]["other"], other)
        self.assertEqual(parsed["custom"], original["custom"])
        self.assertEqual(parsed["trust"], original["trust"])
        if os.name != "nt":
            self.assertEqual(Path(result["backup"]).stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_existing_managed_entry_can_be_upgraded(self):
        self.write({"mcpServers": {workbuddy.DEFAULT_SERVER_ID: managed_entry(32000)}})
        result = workbuddy.merge_config(self.path, managed_entry(32123))
        self.assertFalse(result["noop"])
        self.assertIsNotNone(result["backup"])

    def test_same_id_unmanaged_entry_is_not_overwritten(self):
        raw = self.write({"mcpServers": {workbuddy.DEFAULT_SERVER_ID: {"command": "python"}}})
        with self.assertRaises(workbuddy.ConfigError):
            workbuddy.merge_config(self.path, managed_entry())
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(list(self.path.parent.glob("*.backup-*")), [])

    def test_description_alone_does_not_establish_ownership(self):
        entry = managed_entry()
        entry["url"] = "https://remote.example.invalid/mcp"
        raw = self.write({"mcpServers": {workbuddy.DEFAULT_SERVER_ID: entry}})
        with self.assertRaises(workbuddy.ConfigError):
            workbuddy.merge_config(self.path, managed_entry())
        self.assertEqual(self.path.read_bytes(), raw)

    def test_malformed_and_wrong_shapes_are_preserved(self):
        for raw in (
            b"{broken",
            b"[]",
            b'{"mcpServers":[]}',
            b"",
            b"\xff",
            b'{"same": 1, "same": 2}',
            b'{"value": NaN}',
        ):
            with self.subTest(raw=raw):
                self.path.parent.mkdir(exist_ok=True)
                self.path.write_bytes(raw)
                with self.assertRaises(workbuddy.ConfigError):
                    workbuddy.merge_config(self.path, managed_entry())
                self.assertEqual(self.path.read_bytes(), raw)

    def test_symlink_config_and_parent_are_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        file = actual / "mcp.json"
        file.write_text("{}", encoding="utf-8")
        try:
            self.path.parent.symlink_to(actual, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Platform does not permit test symlinks")
        with self.assertRaises(workbuddy.ConfigError):
            workbuddy.merge_config(self.path, managed_entry())
        self.assertEqual(file.read_text(), "{}")

    def test_retry_preserves_interleaved_editor_change(self):
        self.write({"mcpServers": {"old": {"command": "old"}}})
        real_read = workbuddy._read
        count = 0

        def interleaved(path):
            nonlocal count
            count += 1
            if count == 2:
                self.write(
                    {
                        "mcpServers": {
                            "old": {"command": "old"},
                            "new": {"command": "new"},
                        }
                    }
                )
            return real_read(path)

        with patch.object(workbuddy, "_read", side_effect=interleaved):
            workbuddy.merge_config(self.path, managed_entry())
        parsed = json.loads(self.path.read_text())
        self.assertIn("new", parsed["mcpServers"])
        self.assertIn("old", parsed["mcpServers"])

    def test_interruption_before_replace_preserves_original(self):
        original = self.write({"mcpServers": {"other": {"command": "keep"}}})
        with patch.object(workbuddy.os, "replace", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                workbuddy.merge_config(self.path, managed_entry())
        self.assertEqual(self.path.read_bytes(), original)
        backups = list(self.path.parent.glob("*.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob(".mcp.json.*")), [])

    def test_no_credentials_in_success_result(self):
        result = workbuddy.merge_config(self.path, managed_entry())
        serialized = json.dumps(result)
        self.assertNotIn("synthetic-test-only", serialized)
        self.assertNotIn("Authorization", serialized)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def payload(self) -> Path:
        source = self.root / "source with 空格"
        (source / "installer").mkdir(parents=True)
        (source / "local_app").mkdir()
        (source / "local_app" / "server.py").write_text("# test payload\n", encoding="utf-8")
        (source / "installer" / "release.json").write_text(
            json.dumps(
                {
                    "version": "0.3.0b1",
                    "python": "3.11.15",
                    "uv": "0.12.12",
                }
            ),
            encoding="utf-8",
        )
        (source / "installer" / "requirements-base.lock").write_text(
            "# synthetic test lock\n", encoding="utf-8"
        )
        uv = (
            source
            / "installer"
            / "vendor"
            / bootstrap.platform_key()
            / ("uv.exe" if os.name == "nt" else "uv")
        )
        uv.parent.mkdir(parents=True)
        uv.write_bytes(b"synthetic executable fixture, never executed")
        return source

    def test_payload_excludes_private_files_reports_and_caches(self):
        source = self.payload()
        for relative in (
            ".env",
            "secrets.env",
            "project-memory/reports/report.md",
            "tests/test.py",
            "core/secrets.env",
            "core/__pycache__/private.pyc",
            "local_app/.private.json",
        ):
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("must not copy", encoding="utf-8")
        destination = self.root / "installed"
        bootstrap.copy_payload(source, destination)
        names = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        self.assertIn("local_app/server.py", names)
        self.assertIn("installer/release.json", names)
        self.assertFalse(
            any(
                "private" in name or "secret" in name or "report" in name or "test.py" in name
                for name in names
            )
        )
        before = bootstrap.payload_digest(source)
        (source / "secrets.env").write_text("changed private data", encoding="utf-8")
        self.assertEqual(bootstrap.payload_digest(source), before)
        (source / "local_app" / "server.py").write_text("# changed product code", encoding="utf-8")
        self.assertNotEqual(bootstrap.payload_digest(source), before)

    def test_active_runtime_not_replaced_when_new_health_check_fails(self):
        source = self.payload()
        home = self.root / "home"
        old = {"runtime": "previous-working-version"}
        bootstrap.atomic_json(home / "active.json", old)
        with (
            patch.object(bootstrap, "run_step"),
            patch.object(bootstrap, "check_runtime", return_value=False),
        ):
            with self.assertRaises(bootstrap.InstallError):
                bootstrap.prepare_runtime(source, home)
        self.assertEqual(bootstrap.read_json(home / "active.json"), old)
        self.assertEqual(list((home / "versions").glob("*/ready.json")), [])

    def test_verified_runtime_is_reused_after_reopening(self):
        source = self.payload()
        home = self.root / "home"
        with (
            patch.object(bootstrap, "run_step") as run,
            patch.object(bootstrap, "check_runtime", return_value=True),
        ):
            runtime, release, env = bootstrap.prepare_runtime(source, home)
            self.assertEqual(run.call_count, 2)
            run.reset_mock()
            resumed, _, _ = bootstrap.prepare_runtime(source, home)
            run.assert_not_called()
        self.assertEqual(resumed, runtime)
        self.assertEqual(bootstrap.read_json(home / "active.json")["version"], release["version"])
        self.assertEqual(env["UV_PYTHON_INSTALL_DIR"], str(home / "python"))
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertTrue(Path(env["PERSONAL_KB_UV"]).is_relative_to(runtime))
        launchers = list(home.glob("Open Personal KB.*"))
        self.assertEqual(len(launchers), 1)
        self.assertIn(runtime.name, launchers[0].read_text())

    def test_installation_lock_recovers_exited_owner_but_rejects_live_owner(self):
        home = self.root / "home"
        bootstrap.atomic_json(home / "installation.lock", {"pid": 424242, "id": "stale"})
        with patch.object(bootstrap, "process_is_alive", return_value=False):
            with bootstrap.installation_lock(home):
                self.assertEqual(
                    bootstrap.read_json(home / "installation.lock")["pid"], os.getpid()
                )
        self.assertFalse((home / "installation.lock").exists())
        bootstrap.atomic_json(home / "installation.lock", {"pid": os.getpid(), "id": "live"})
        with self.assertRaises(bootstrap.InstallError):
            with bootstrap.installation_lock(home):
                self.fail("Should not enter another installer's lock")

    def test_service_reuse_requires_local_record_and_matching_health_identity(self):
        data = self.root / "data"
        record = {
            "pid": os.getpid(),
            "port": 32123,
            "version": "0.3.0b1",
            "instance_id": "ours",
        }
        bootstrap.atomic_json(data / "service.json", record)
        with patch.object(
            bootstrap,
            "health",
            return_value={"version": "0.3.0b1", "instance_id": "someone-else"},
        ):
            self.assertIsNone(bootstrap.known_service(data, 32123, "0.3.0b1"))
        with patch.object(
            bootstrap,
            "health",
            return_value={"version": "0.3.0b1", "instance_id": "ours"},
        ):
            self.assertEqual(bootstrap.known_service(data, 32123, "0.3.0b1"), record)
            self.assertIsNone(bootstrap.known_service(data, 32123, "0.4.0"))
            self.assertIsNone(bootstrap.known_service(data, 32123, "0.3.0b1", "new-payload"))

    def test_launch_identity_accepts_interpreter_pid_different_from_launcher(self):
        home = self.root / "home"
        payload = "synthetic-payload"
        inherited = "0" * 32
        env = {"PERSONAL_KB_PAYLOAD_SHA256": payload, "PERSONAL_KB_LAUNCH_ID": inherited}
        original = dict(env)
        record = {}
        process = Mock(pid=os.getpid() + 100000)
        process.poll.return_value = None

        def launched(*args, **kwargs):
            launch_id = kwargs["env"]["PERSONAL_KB_LAUNCH_ID"]
            self.assertNotEqual(launch_id, inherited)
            record.update(
                pid=os.getpid(),
                port=32123,
                version="0.4.0b3",
                instance_id="synthetic-instance",
                payload_sha256=payload,
                launch_id=launch_id,
            )
            bootstrap.atomic_json(home / "data" / "service.json", record)
            return process

        with (
            patch.object(bootstrap, "port_in_use", return_value=False),
            patch.object(bootstrap, "health", side_effect=lambda port: dict(record)),
            patch.object(bootstrap.subprocess, "Popen", side_effect=launched) as spawn,
        ):
            result = bootstrap.start_service(
                self.root / "runtime", home, {"version": "0.4.0b3"}, env, 32123
            )
            self.assertEqual(result, record)
            self.assertNotEqual(result["pid"], process.pid)
            self.assertEqual(env, original)
            self.assertEqual(
                bootstrap.start_service(
                    self.root / "runtime", home, {"version": "0.4.0b3"}, env, 32123
                ),
                record,
            )
            spawn.assert_called_once()

    def test_expected_launch_id_preserves_every_existing_identity_check(self):
        data = self.root / "data"
        expected = "a" * 32  # Synthetic correlation ID, not an authentication credential.
        base = {
            "pid": os.getpid(),
            "port": 32123,
            "version": "0.4.0b3",
            "instance_id": "synthetic-instance",
            "payload_sha256": "synthetic-payload",
            "launch_id": expected,
        }
        mutations = [
            (side, field, value)
            for side in ("record", "health")
            for field, value in (
                ("launch_id", None),
                ("launch_id", "b" * 32),
                ("version", "old"),
                ("instance_id", "other"),
                ("payload_sha256", "other"),
            )
        ]
        mutations += [("record", "port", 32124)]
        for side, field, value in mutations:
            with self.subTest(side=side, field=field, value=value):
                record, current = dict(base), dict(base)
                (record if side == "record" else current)[field] = value
                bootstrap.atomic_json(data / "service.json", record)
                with patch.object(bootstrap, "health", return_value=current):
                    self.assertIsNone(
                        bootstrap.known_service(
                            data, 32123, "0.4.0b3", "synthetic-payload", expected_launch_id=expected
                        )
                    )
        bootstrap.atomic_json(data / "service.json", base)
        with patch.object(bootstrap, "health", return_value=base):
            self.assertEqual(
                bootstrap.known_service(
                    data, 32123, "0.4.0b3", "synthetic-payload", expected_launch_id=expected
                ),
                base,
            )
            self.assertIsNone(
                bootstrap.known_service(
                    data, 32123, "0.4.0b3", "synthetic-payload", expected_launch_id="invalid"
                )
            )
            with patch.object(bootstrap, "process_is_alive", return_value=False):
                self.assertIsNone(
                    bootstrap.known_service(
                        data, 32123, "0.4.0b3", "synthetic-payload", expected_launch_id=expected
                    )
                )

    def test_unknown_occupied_port_never_launches_or_kills_a_process(self):
        with (
            patch.object(bootstrap, "known_service", return_value=None),
            patch.object(bootstrap, "port_in_use", return_value=True),
            patch.object(bootstrap.subprocess, "Popen") as spawn,
        ):
            with self.assertRaises(bootstrap.InstallError):
                bootstrap.start_service(
                    self.root / "runtime",
                    self.root / "home",
                    {"version": "0.3.0b1"},
                    {},
                    32123,
                )
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
