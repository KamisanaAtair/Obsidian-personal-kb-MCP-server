"""Explicit, local-only secret import; never return secrets to UI or jobs."""

import json
import os
import stat
from pathlib import Path

from .features import atomic_json
from .models import ModelError
from .workspaces import is_link

TEMPLATE = """# Personal KB 手动密钥模板。也可以直接在本机设置页填写 Key。
# 复制此文件为同目录 secrets.env，仅填写一个字段，再在设置页选中连接并导入。
# 不要将填写后的文件上传到 Git、聊天或云盘。导入成功后清空已导入字段。
# 本地免 Key 服务无需填写。不会执行本文件中的命令或自动读取其他 .env。
API_KEY=
"""


class SecretSetup:
    def __init__(self, data, models):
        self.data, self.models = Path(data), models
        self.template = self.data / "secrets.env.example"
        self.input = self.data / "secrets.env"
        if not self.template.exists() and not is_link(self.template):
            descriptor = os.open(self.template, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(TEMPLATE)

    def _read(self, path):
        if is_link(path):
            raise ModelError("unsafe_secret_file", "密钥文件不能是符号链接或目录联接。")
        if not path.exists():
            return ""
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32768:
            raise ModelError("unsafe_secret_file", "密钥文件必须是小于 32 KB 的普通文本文件。")
        try:
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            raise ModelError(
                "secret_read_failed", "无法读取密钥文件，请检查本机文件权限。"
            ) from None

    def status(self):
        # Legacy presence is a boolean only. No legacy key is used implicitly.
        present = False
        try:
            raw = self._read(self.data / "credentials.json")
            value = json.loads(raw) if raw else {}
            present = isinstance(value, dict) and bool(value.get("dashscope_api_key"))
        except (ValueError, ModelError):
            pass
        return {
            "secret_template_path": str(self.template),
            "secret_input_path": str(self.input),
            "legacy_secret_present": present,
        }

    def _store(self, profile_id, key):
        if not key:
            raise ModelError("empty_secret", "所选文件的密钥字段为空，请先在本机填写。")
        self.models.save_config({"profile": {"id": profile_id, "api_key": key}})
        if not self.models.verify_saved_key(profile_id, key):
            raise ModelError("secret_verification_failed", "系统凭据库回读校验失败，原文件已保留。")

    def import_secret(self, profile_id, source):
        # A user selects the exact target in authenticated settings. No arbitrary
        # path, environment expansion, shell evaluation or host MCP import API.
        with self.models._lock:
            profile = self.models._profile(profile_id)
            if source == "legacy":
                if profile["provider"] != "qwen":
                    raise ModelError(
                        "secret_target_mismatch", "旧 DashScope Key 只能迁移到 Qwen 连接。"
                    )
                path = self.data / "credentials.json"
                raw = self._read(path)
                try:
                    value = json.loads(raw) if raw else {}
                    key = value.get("dashscope_api_key", "")
                except (ValueError, AttributeError):
                    raise ModelError(
                        "invalid_secret_file", "旧凭据文件格式无效，原文件已保留。"
                    ) from None
                if not isinstance(key, str):
                    raise ModelError("invalid_secret_file", "旧凭据字段格式无效。")
                self._store(profile_id, key)
                if self._read(path) != raw:
                    raise ModelError(
                        "secret_file_changed", "导入期间原文件发生变化，未清除原字段。"
                    )
                value.pop("dashscope_api_key", None)
                atomic_json(path, value)
            elif source == "template":
                raw = self._read(self.input)
                entries = []
                lines = raw.splitlines()
                for index, line in enumerate(lines):
                    if not line.strip() or line.lstrip().startswith("#"):
                        continue
                    name, sep, value = line.partition("=")
                    if not sep or name.strip() not in {"API_KEY", "DASHSCOPE_API_KEY"}:
                        raise ModelError(
                            "invalid_secret_file",
                            "模板仅接受 API_KEY 或 DASHSCOPE_API_KEY 的单行赋值。",
                        )
                    if value.strip():
                        entries.append((index, name.strip(), value.strip()))
                if len(entries) != 1:
                    raise ModelError("invalid_secret_file", "请只填写一个密钥字段后再导入。")
                index, name, key = entries[0]
                if name == "DASHSCOPE_API_KEY" and profile["provider"] != "qwen":
                    raise ModelError(
                        "secret_target_mismatch", "DashScope 密钥字段只能导入 Qwen 连接。"
                    )
                self._store(profile_id, key)
                if self._read(self.input) != raw:
                    raise ModelError("secret_file_changed", "导入期间模板发生变化，未清除原字段。")
                lines[index] = name + "="
                # Replacement has private permissions and cannot follow a final
                # symlink; re-check the selected source before removing its key.
                import tempfile

                descriptor, temporary = tempfile.mkstemp(prefix=".secret-", dir=self.data)
                try:
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        stream.write("\n".join(lines) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    if self._read(self.input) != raw:
                        raise ModelError("secret_file_changed", "模板已变化，未清除原字段。")
                    os.replace(temporary, self.input)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            else:
                raise ModelError(
                    "invalid_secret_source", "请选择空模板文件或旧 DashScope 凭据作为来源。"
                )
        return {"imported": True, "source_cleared": True}

    def save_legacy_key(self, value):
        """Compatibility endpoint writes to the system store, never credentials.json."""
        if not isinstance(value, str):
            raise ModelError("invalid_api_key", "密钥格式无效。")
        with self.models._lock:
            identity = self.models.public_config()["capability_profiles"].get("asr")
            if identity:
                profile = self.models._profile(identity)
                if profile["provider"] != "qwen":
                    raise ModelError(
                        "secret_target_mismatch", "当前 ASR 不是 Qwen，请在统一设置中修改对应连接。"
                    )
                incoming = {"id": identity}
            else:
                incoming = {
                    "provider": "qwen",
                    "name": "视频语音识别",
                    "model_id": "",
                    "capabilities": ["asr"],
                    "capability_models": {"asr": "qwen3-asr-flash", "vision": ""},
                    "audio_api_style": "dashscope",
                }
            incoming.update({"api_key": value} if value else {"clear_key": True})
            config = self.models.save_config({"profile": incoming})
            if not identity and value:
                identity = config["profiles"][-1]["id"]
                self.models.save_config({"capability_profiles": {"asr": identity}})
        return {"saved": bool(value)}
