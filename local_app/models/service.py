"""Versioned local model configuration and pooled direct streaming transport."""

# Public operations must never expose exception text from credential backends,
# HTTP transports, response decoders, or caller callbacks.
# ruff: noqa: BLE001

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from local_app.features import atomic_json

from .credentials import SystemCredentialStore
from .errors import ModelError
from .multimodal import (
    CAPABILITIES,
    audio_request,
    read_wav,
    test_image,
    test_wav,
    validate_images,
)
from .providers import (
    LEGACY_QWEN3_ALWAYS_THINK_TEMPLATE,
    PROVIDERS,
    ModelFactory,
    catalog,
    normalize_url,
    request_body,
    requires_key,
)

TASKS = ("ingest", "qa", "correlation")
PROFILE_FIELDS = {
    "id",
    "name",
    "provider",
    "api_style",
    "base_url",
    "model_id",
    "timeout_seconds",
    "max_output_tokens",
    "thinking",
    "capabilities",
    "capability_models",
    "audio_api_style",
}


def _integer(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise ModelError("invalid_config", "超时或输出长度超出允许范围。")
    return value


def _short_text(value, limit, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ModelError("invalid_config", "配置字段包含无效字符或超出长度限制。")
    value = value.strip()
    if not value and not allow_empty:
        raise ModelError("invalid_config", "请填写连接名称和模型 ID。")
    return value


def _http_error(status, *, model_list=False):
    prefix = f"HTTP {status}："
    if model_list and status in {404, 405, 501}:
        code = {404: "not_found", 405: "request_rejected", 501: "provider_unavailable"}[status]
        return ModelError(
            code,
            prefix + "该地址可能未提供模型列表接口；可手动填写官方支持的模型 ID，"
            "再运行文字连接测试。",
        )
    if status in {401, 403}:
        return ModelError(
            "authentication_failed", prefix + "模型服务拒绝认证，请检查 API Key、地域和模型权限。"
        )
    if status == 429:
        return ModelError(
            "rate_limited", prefix + "模型服务限流或额度不足，请在服务商控制台检查后手动重试。"
        )
    if 300 <= status < 400:
        return ModelError(
            "redirect_rejected", prefix + "模型地址发生重定向，已停止发送；请填写最终官方 API 地址。"
        )
    if status == 404:
        return ModelError("not_found", prefix + "模型或接口不存在，请检查模型 ID 与服务地址。")
    if status == 502:
        return ModelError(
            "provider_unavailable", prefix + "模型服务网关收到了无效的上游响应，请稍后手动重试。"
        )
    if status == 503:
        return ModelError(
            "provider_unavailable", prefix + "模型服务暂时无法提供服务，请稍后手动重试。"
        )
    if status == 504:
        return ModelError(
            "provider_unavailable", prefix + "模型服务网关等待上游响应超时，请稍后手动重试。"
        )
    if status >= 500:
        return ModelError("provider_unavailable", prefix + "模型服务暂时不可用，请稍后手动重试。")
    return ModelError(
        "request_rejected", prefix + "模型服务拒绝请求，请检查模型、参数和账户额度。"
    )


class ModelService:
    def __init__(self, data_dir, credential_store=None):
        self.data_dir = Path(data_dir).resolve()
        self.path = self.data_dir / "model-config.json"
        self.namespace = (
            "personal-kb-models-" + hashlib.sha256(str(self.data_dir).encode()).hexdigest()[:24]
        )
        self.credentials = (
            credential_store
            if credential_store is not None
            else SystemCredentialStore(self.namespace)
        )
        self._lock = threading.RLock()
        self.client = httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(120, connect=15),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
        self._config = self._load()

    def close(self):
        self.client.close()

    def _load(self):
        if not self.path.exists():
            return {
                "schema_version": 1,
                "revision": 0,
                "generation_mode": "host",
                "profiles": [],
                "default_profile": None,
                "task_profiles": {key: None for key in TASKS},
                "capability_profiles": {key: None for key in CAPABILITIES},
            }
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("schema_version") != 1 or not isinstance(value.get("profiles"), list):
                raise ValueError
            _integer(value["revision"], 0, 2**63 - 1)
            value.setdefault("capability_profiles", {key: None for key in CAPABILITIES})
            value["profiles"] = [self._normalize_profile(p, p) for p in value["profiles"]]
            self._validate_routes(value, check_keys=False)
            for profile in value["profiles"]:
                for ref in profile.get("credential_history", []):
                    self._check_reference(ref)
                if profile.get("credential_ref"):
                    self._check_reference(profile["credential_ref"])
            return value
        except (OSError, ValueError, TypeError, KeyError):
            raise ModelError(
                "config_unreadable", "模型配置文件无法读取，请恢复有效配置；没有自动覆盖现有文件。"
            ) from None

    def _check_reference(self, reference):
        if not isinstance(reference, str) or not re.fullmatch(
            re.escape(self.namespace) + r":[0-9a-f]{32}", reference
        ):
            raise ModelError(
                "invalid_credential_reference", "任务的模型凭据引用无效，请重新提交任务。"
            )

    def _key(self, profile):
        reference = profile.get("credential_ref")
        if not reference:
            return None
        self._check_reference(reference)
        try:
            return self.credentials.get(reference)
        except ModelError:
            raise
        except Exception:
            raise ModelError(
                "credential_store_unavailable", "系统凭据库读取失败，请检查系统授权。"
            ) from None

    def verify_saved_key(self, profile_id, key):
        """Verify a completed credential import without exposing the stored value."""
        if not isinstance(key, str) or not key:
            return False
        with self._lock:
            saved = self._key(self._profile(profile_id))
            return isinstance(saved, str) and hmac.compare_digest(saved.encode(), key.encode())

    def _public_profile(self, profile):
        value = {key: deepcopy(profile.get(key)) for key in PROFILE_FIELDS}
        value.update(
            {
                key: profile.get(key)
                for key in ("revision", "tested_revision", "tested_at", "test_status")
            }
        )
        value["capability_test_status"] = deepcopy(profile["capability_test_status"])
        try:
            value["credential_present"] = bool(self._key(profile))
            value["credential_error"] = None
        except ModelError as exc:
            value["credential_present"] = False
            value["credential_error"] = exc.code
        return value

    def public_config(self):
        with self._lock:
            value = {
                key: deepcopy(self._config[key])
                for key in (
                    "schema_version",
                    "revision",
                    "generation_mode",
                    "default_profile",
                    "task_profiles",
                    "capability_profiles",
                )
            }
            value["profiles"] = [
                self._public_profile(profile) for profile in self._config["profiles"]
            ]
            value["providers"] = catalog()
            return value

    def _normalize_profile(self, payload, previous=None):
        provider = payload.get("provider", (previous or {}).get("provider", "custom"))
        if provider not in PROVIDERS:
            raise ModelError("invalid_provider", "请选择受支持的模型服务商。")
        preset = PROVIDERS[provider]
        profile = (
            deepcopy(previous)
            if previous
            else {
                "id": uuid.uuid4().hex,
                "name": preset["name"],
                "provider": provider,
                "api_style": preset["api_style"],
                "base_url": preset["default_base_url"],
                "model_id": preset["default_model"],
                "timeout_seconds": 120,
                "max_output_tokens": 4096,
                "thinking": "default",
                "revision": 0,
                "credential_ref": None,
                "credential_history": [],
                "tested_revision": None,
                "tested_at": None,
                "test_status": "untested",
            }
        )
        profile.setdefault("capabilities", ["text"])
        profile.setdefault("capability_models", {key: "" for key in CAPABILITIES})
        profile.setdefault("audio_api_style", "dashscope" if provider == "qwen" else "openai_audio")
        profile.setdefault("capability_test_status", self._empty_capability_tests())
        if previous and previous["provider"] != provider:
            profile.update(
                provider=provider,
                api_style=preset["api_style"],
                base_url=preset["default_base_url"],
                model_id=preset["default_model"],
                thinking="default",
                audio_api_style="dashscope" if provider == "qwen" else "openai_audio",
            )
        profile.update({key: payload[key] for key in PROFILE_FIELDS if key in payload})
        if not isinstance(profile["id"], str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,64}", profile["id"]
        ):
            raise ModelError("invalid_profile", "连接 ID 无效。")
        profile["name"] = _short_text(profile["name"], 80)
        profile["model_id"] = _short_text(profile["model_id"], 200, allow_empty=True)
        profile["base_url"] = normalize_url(profile["base_url"])
        _integer(profile["timeout_seconds"], 5, 600)
        _integer(profile["max_output_tokens"], 16, 131072)
        if profile["api_style"] != preset["api_style"]:
            raise ModelError("invalid_api_style", "该服务商不支持所选接口类型。")
        if profile["thinking"] not in {"default", "enabled", "disabled"}:
            raise ModelError("invalid_thinking", "思考模式必须为模型默认、开启或关闭。")
        capabilities = profile["capabilities"]
        if (not isinstance(capabilities, list) or not capabilities
                or any(not isinstance(c, str) or c not in {"text", *CAPABILITIES} for c in capabilities)
                or len(capabilities) != len(set(capabilities))):
            raise ModelError("invalid_capabilities", "请选择文本、视觉或语音转写能力，不能重复。")
        models = profile["capability_models"]
        if not isinstance(models, dict) or set(models) != set(CAPABILITIES):
            raise ModelError("invalid_capability_models", "能力型号必须包含视觉和语音转写字段。")
        profile["capability_models"] = {
            key: _short_text(models[key], 200, allow_empty=True) for key in CAPABILITIES
        }
        if profile["audio_api_style"] not in {"dashscope", "openai_audio"}:
            raise ModelError("invalid_audio_api_style", "请选择 DashScope 或兼容语音转写接口。")
        if "text" in capabilities and profile["model_id"]:
            request_body(profile, "参数校验")
        return profile

    def _validate_routes(self, value, check_keys=True):
        if value["generation_mode"] not in {"host", "independent"}:
            raise ModelError("invalid_mode", "生成方式必须为宿主模型或独立模型。")
        profiles = {profile["id"]: profile for profile in value["profiles"]}
        if len(profiles) != len(value["profiles"]):
            raise ModelError("invalid_config", "模型连接 ID 重复。")
        routes = value["task_profiles"]
        if not isinstance(routes, dict) or set(routes) != set(TASKS):
            raise ModelError("invalid_route", "任务路由必须包含笔记整理、问答与关联分析。")
        for identity in [value["default_profile"], *routes.values()]:
            if identity is not None and (not isinstance(identity, str) or identity not in profiles):
                raise ModelError("invalid_route", "选中的模型连接不存在。")
        capabilities = value.get("capability_profiles")
        if not isinstance(capabilities, dict) or set(capabilities) != set(CAPABILITIES):
            raise ModelError("invalid_route", "能力路由必须包含视觉和语音转写。")
        for capability, identity in capabilities.items():
            if identity is None:
                continue
            if not isinstance(identity, str) or identity not in profiles:
                raise ModelError("invalid_route", "选中的能力连接不存在。")
            if capability not in profiles[identity]["capabilities"]:
                raise ModelError("unsupported_capability", "所选连接未启用对应能力。")
        if value["generation_mode"] == "independent":
            for task in TASKS:
                identity = routes[task] or value["default_profile"]
                if not identity:
                    raise ModelError(
                        "missing_route", "启用独立生成前，请选择默认模型或为全部任务指定模型。"
                    )
                profile = profiles[identity]
                if "text" not in profile["capabilities"]:
                    raise ModelError("unsupported_capability", "文本任务须选择启用文本能力的连接。")
                if not profile["model_id"]:
                    raise ModelError("missing_model", "启用独立生成前，请填写模型 ID。")
                if check_keys and requires_key(profile) and not self._key(profile):
                    raise ModelError(
                        "missing_api_key", "启用独立生成前，请保存云端模型的 API Key。"
                    )

    def save_config(self, payload):
        if not isinstance(payload, dict) or set(payload) - {
            "generation_mode",
            "default_profile",
            "task_profiles",
            "capability_profiles",
            "profile",
        }:
            raise ModelError("invalid_config", "模型设置请求包含未知字段。")
        with self._lock:
            updated = deepcopy(self._config)
            new_reference = None
            revoked = []
            try:
                if "profile" in payload:
                    incoming = payload["profile"]
                    if not isinstance(incoming, dict) or set(incoming) - PROFILE_FIELDS - {
                        "api_key",
                        "clear_key",
                    }:
                        raise ModelError("invalid_config", "模型连接包含未知字段。")
                    previous = next(
                        (p for p in updated["profiles"] if p["id"] == incoming.get("id")), None
                    )
                    if incoming.get("id") and previous is None:
                        raise ModelError("profile_not_found", "模型连接不存在，请刷新设置。")
                    profile = self._normalize_profile(incoming, previous)
                    key = incoming.get("api_key", "")
                    if (
                        not isinstance(key, str)
                        or len(key) > 8192
                        or any(ord(c) < 33 or ord(c) > 126 for c in key)
                    ):
                        raise ModelError(
                            "invalid_api_key", "API Key 格式无效，请检查是否含空白或换行。"
                        )
                    clear = incoming.get("clear_key", False)
                    if not isinstance(clear, bool) or (clear and key):
                        raise ModelError("invalid_api_key", "不能同时保存与清除 API Key。")
                    if previous and previous.get("credential_ref") and not (key or clear):
                        before, after = (
                            urlsplit(previous["base_url"]),
                            urlsplit(profile["base_url"]),
                        )
                        if (before.scheme, before.netloc, previous["provider"]) != (
                            after.scheme,
                            after.netloc,
                            profile["provider"],
                        ):
                            raise ModelError(
                                "credential_endpoint_changed",
                                "更换服务商或服务域名时，请重新填写 API Key 或明确清除原密钥。",
                            )
                    if clear:
                        revoked = list(profile.get("credential_history", []))
                        profile.update(credential_ref=None, credential_history=[])
                    elif key:
                        new_reference = self.namespace + ":" + uuid.uuid4().hex
                        self.credentials.set(new_reference, key)
                        profile["credential_ref"] = new_reference
                        profile.setdefault("credential_history", []).append(new_reference)
                    if profile != previous:
                        profile["revision"] += 1
                        profile.update(tested_revision=None, tested_at=None, test_status="untested",
                                       capability_test_status=self._empty_capability_tests())
                    updated["profiles"] = [
                        profile if p["id"] == profile["id"] else p for p in updated["profiles"]
                    ]
                    if previous is None:
                        if len(updated["profiles"]) >= 40:
                            raise ModelError(
                                "profile_limit", "最多保存 40 个模型连接，请先移除不再使用的连接。"
                            )
                        updated["profiles"].append(profile)
                for field in ("generation_mode", "default_profile"):
                    if field in payload:
                        if (
                            field == "default_profile"
                            and payload[field] is not None
                            and not isinstance(payload[field], str)
                        ):
                            raise ModelError("invalid_route", "默认模型必须是连接 ID 或空值。")
                        updated[field] = payload[field] or (
                            None if field == "default_profile" else payload[field]
                        )
                if "task_profiles" in payload:
                    routes = payload["task_profiles"]
                    if not isinstance(routes, dict) or set(routes) - set(TASKS):
                        raise ModelError("invalid_route", "任务路由包含未知任务。")
                    if any(
                        identity is not None and not isinstance(identity, str)
                        for identity in routes.values()
                    ):
                        raise ModelError("invalid_route", "任务模型必须是连接 ID 或空值。")
                    updated["task_profiles"].update(
                        {key: identity or None for key, identity in routes.items()}
                    )
                if "capability_profiles" in payload:
                    routes = payload["capability_profiles"]
                    if not isinstance(routes, dict) or set(routes) - set(CAPABILITIES):
                        raise ModelError("invalid_route", "能力路由包含未知能力。")
                    if any(identity is not None and not isinstance(identity, str)
                           for identity in routes.values()):
                        raise ModelError("invalid_route", "能力连接必须是连接 ID 或空值。")
                    updated["capability_profiles"].update(
                        {key: identity or None for key, identity in routes.items()}
                    )
                self._validate_routes(updated)
                if updated != self._config:
                    updated["revision"] += 1
                    # Revocation precedes config commit: a failed write can leave an
                    # unusable connection, never an old secret falsely marked removed.
                    for reference in revoked:
                        self._check_reference(reference)
                        self.credentials.delete(reference)
                    atomic_json(self.path, updated)
                    self._config = updated
                return self.public_config()
            except ModelError:
                if new_reference:
                    self.credentials.delete(new_reference)
                raise
            except Exception:
                if new_reference:
                    try:
                        self.credentials.delete(new_reference)
                    except Exception:  # noqa: S110 - logging could reveal the key
                        pass
                raise ModelError(
                    "config_save_failed", "模型设置未能保存，请检查系统凭据库与数据目录权限。"
                ) from None

    def _profile(self, identity):
        profile = next((p for p in self._config["profiles"] if p["id"] == identity), None)
        if profile is None:
            raise ModelError("profile_not_found", "模型连接不存在，请刷新设置。")
        return profile

    def delete_profile(self, identity):
        with self._lock:
            profile = self._profile(identity)
            if identity in [
                self._config["default_profile"],
                *self._config["task_profiles"].values(),
                *self._config["capability_profiles"].values(),
            ]:
                raise ModelError(
                    "profile_in_use", "该连接仍被默认模型或任务引用，请先解除引用或选择其他连接。"
                )
            try:
                for reference in profile.get("credential_history", []):
                    self._check_reference(reference)
                    self.credentials.delete(reference)
                updated = deepcopy(self._config)
                updated["profiles"] = [p for p in updated["profiles"] if p["id"] != identity]
                updated["revision"] += 1
                atomic_json(self.path, updated)
                self._config = updated
            except ModelError:
                raise
            except Exception:
                raise ModelError(
                    "config_save_failed", "连接未能删除，请检查系统凭据库与数据目录权限。"
                ) from None
            return self.public_config()

    def _snapshot_profile(self, profile):
        value = {key: deepcopy(profile[key]) for key in PROFILE_FIELDS}
        value.update(
            generation_mode="independent",
            config_revision=self._config["revision"],
            profile_revision=profile["revision"],
            credential_ref=profile.get("credential_ref"),
        )
        return value

    @staticmethod
    def _empty_capability_tests():
        return {key: {"status": "untested", "tested_revision": None, "tested_at": None}
                for key in CAPABILITIES}

    def profile_snapshot(self, profile_id, capability="text"):
        if capability not in {"text", *CAPABILITIES}:
            raise ModelError("invalid_capability", "未知模型能力。")
        with self._lock:
            profile = self._profile(profile_id)
            if capability not in profile["capabilities"]:
                raise ModelError("unsupported_capability", "该连接未启用所需能力。")
            value = self._snapshot_profile(profile)
            value["capability"] = capability
            if capability != "text":
                value["model_id"] = profile["capability_models"][capability]
                value["thinking"] = "default"
            if not value["model_id"]:
                raise ModelError("missing_model", "请先填写所选能力的模型 ID。")
            self._headers(value)
            if capability == "asr":
                audio_request(value, b"")  # Validate the destination without making a request.
            return value

    def snapshot(self, task):
        if task in CAPABILITIES:
            with self._lock:
                identity = self._config["capability_profiles"][task]
                if not identity:
                    raise ModelError("missing_route", "请在模型设置中选择所需能力的连接。")
                return self.profile_snapshot(identity, task)
        if task not in TASKS:
            raise ModelError("invalid_task", "未知模型任务。")
        with self._lock:
            if self._config["generation_mode"] == "host":
                return {"generation_mode": "host", "config_revision": self._config["revision"]}
            self._validate_routes(self._config)
            return self._snapshot_profile(
                self._profile(
                    self._config["task_profiles"][task] or self._config["default_profile"]
                )
            )

    def _headers(self, snapshot):
        key = self._key(snapshot)
        if (requires_key(snapshot) or snapshot.get("credential_ref")) and not key:
            raise ModelError(
                "missing_api_key", "该任务的模型凭据已删除或不可用，请重新配置并提交任务。"
            )
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        return headers

    @staticmethod
    def _lines(response, started, timeout):
        pending = b""
        total = 0
        for chunk in response.iter_bytes():
            if time.monotonic() - started > timeout:
                raise ModelError(
                    "timeout", "模型请求超时，未自动重试；请检查网络或调整超时后重试。"
                )
            total += len(chunk)
            pending += chunk
            if total > 16 * 1024 * 1024 or len(pending) > 1024 * 1024:
                raise ModelError("response_too_large", "模型响应超出安全大小限制，请缩短输出。")
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                try:
                    yield line.rstrip(b"\r").decode("utf-8")
                except UnicodeError:
                    raise ModelError("invalid_stream", "模型返回了无效编码的流式响应。") from None
        if pending:
            try:
                yield pending.rstrip(b"\r").decode("utf-8")
            except UnicodeError:
                raise ModelError("invalid_stream", "模型返回了无效编码的流式响应。") from None

    def generate(self, snapshot, prompt, on_event=None, *, images=None):
        if snapshot.get("generation_mode") != "independent":
            raise ModelError("host_mode", "当前任务使用宿主模型，请使用宿主生成流程。")
        profile = self._normalize_profile(snapshot, snapshot)
        pictures = validate_images(images)
        capability = snapshot.get("capability", "text")
        if pictures:
            if capability != "vision" or "vision" not in profile["capabilities"]:
                raise ModelError("unsupported_capability", "图片必须使用明确配置的视觉能力。")
        elif capability == "vision":
            raise ModelError("missing_images", "视觉调用需要至少一张真实图片。")
        elif capability != "text" or "text" not in profile["capabilities"]:
            raise ModelError("unsupported_capability", "该快照不能用于文本生成。")
        adapter = ModelFactory.create(profile)
        body = adapter.request_body(prompt)
        if pictures:
            if adapter.stream_format == "ndjson":
                body["messages"][0]["images"] = [item["data"] for item in pictures]
            else:
                body["messages"][0]["content"] = [{"type": "text", "text": prompt}] + [
                    {"type": "image_url", "image_url": {
                        "url": "data:" + item["mime_type"] + ";base64," + item["data"]
                    }} for item in pictures
                ]
        if not profile["model_id"]:
            raise ModelError("missing_model", "请先填写模型 ID。")
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt.encode()) > 2 * 1024 * 1024
        ):
            raise ModelError("invalid_prompt", "生成内容为空或过长，请缩小资料范围。")
        headers = self._headers(profile)
        if adapter.stream_format == "ndjson":
            headers["Accept"] = "application/x-ndjson"
        emit = on_event or (lambda event: None)
        started = time.monotonic()
        metrics = {"first_event_ms": None, "first_text_ms": None, "total_ms": None}
        usage = {"input_tokens": None, "output_tokens": None}
        fragments = []
        complete = False
        stream_ended = False
        event_data = []
        reasoning_seen = False

        def consume(raw):
            nonlocal complete, reasoning_seen, stream_ended
            if metrics["first_event_ms"] is None:
                metrics["first_event_ms"] = round((time.monotonic() - started) * 1000, 1)
            if raw.strip() == "[DONE]":
                complete = True
                stream_ended = True
                return
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise TypeError
            except (ValueError, TypeError):
                raise ModelError(
                    "invalid_stream", "模型返回了无法解析的流式响应，请检查接口类型。"
                ) from None
            if value.get("error"):
                raise ModelError(
                    "provider_error", "模型服务在生成过程中报错，请检查服务商控制台后手动重试。"
                )
            text = ""
            if adapter.stream_format == "ndjson":
                message = value.get("message")
                if not isinstance(message, dict):
                    raise ModelError("invalid_stream", "Ollama 返回的消息格式无效。")
                text = message.get("content") or ""
                has_reasoning = bool(message.get("thinking"))
                if value.get("done_reason") == "length":
                    raise ModelError(
                        "output_truncated",
                        "模型输出达到长度上限，请增加最大输出长度或缩小资料范围。",
                    )
                if message.get("tool_calls") or (
                    value.get("done") is True and value.get("done_reason") not in {None, "stop"}
                ):
                    raise ModelError(
                        "unsupported_result",
                        "本地模型未正常返回完整正文，请检查模型能力或输入内容。",
                    )
                complete = complete or value.get("done") is True
                stream_ended = complete
                counts = {
                    "input_tokens": value.get("prompt_eval_count"),
                    "output_tokens": value.get("eval_count"),
                }
            else:
                choices = value.get("choices")
                if not isinstance(choices, list):
                    raise ModelError("invalid_stream", "模型返回的流式消息缺少 choices 字段。")
                has_reasoning = False
                if choices:
                    choice = choices[0]
                    if not isinstance(choice, dict) or not isinstance(choice.get("delta"), dict):
                        raise ModelError("invalid_stream", "模型返回的增量消息格式无效。")
                    delta = choice["delta"]
                    if delta.get("tool_calls") or delta.get("function_call"):
                        raise ModelError(
                            "unsupported_result", "模型请求了未启用的工具，未保存该结果。"
                        )
                    text = delta.get("content") or ""
                    has_reasoning = bool(delta.get("reasoning_content") or delta.get("reasoning"))
                    reason = choice.get("finish_reason")
                    if reason == "length":
                        raise ModelError(
                            "output_truncated",
                            "模型输出达到长度上限，请增加最大输出长度或缩小资料范围。",
                        )
                    if reason in {"content_filter", "tool_calls", "function_call"}:
                        raise ModelError(
                            "unsupported_result", "模型未返回完整正文，请检查模型能力或输入内容。"
                        )
                    if reason not in {None, "stop"}:
                        raise ModelError(
                            "unsupported_result", "模型返回了未知结束状态，未保存该结果。"
                        )
                    complete = complete or reason == "stop"
                token_usage = value.get("usage") or {}
                if not isinstance(token_usage, dict):
                    raise ModelError("invalid_stream", "模型返回的用量格式无效。")
                counts = {
                    "input_tokens": token_usage.get("prompt_tokens"),
                    "output_tokens": token_usage.get("completion_tokens"),
                }
            if has_reasoning and not reasoning_seen:
                reasoning_seen = True
                emit({"type": "status", "message": "模型正在思考，等待正文。"})
            for key, count in counts.items():
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    usage[key] = count
            if not isinstance(text, str):
                raise ModelError("invalid_stream", "模型返回了不支持的正文格式。")
            if text:
                if metrics["first_text_ms"] is None:
                    metrics["first_text_ms"] = round((time.monotonic() - started) * 1000, 1)
                fragments.append(text)
                emit({"type": "delta", "text": text})

        try:
            emit({"type": "status", "message": "正在连接所选模型服务。"})
            if profile["provider"] == "ollama" and profile["thinking"] != "default":
                self._check_ollama_thinking(profile, headers)
            with self.client.stream(
                "POST",
                profile["base_url"] + adapter.chat_path,
                headers=headers,
                json=body,
                timeout=httpx.Timeout(
                    profile["timeout_seconds"], connect=min(15, profile["timeout_seconds"])
                ),
                follow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise _http_error(response.status_code)
                for line in self._lines(response, started, profile["timeout_seconds"]):
                    if adapter.stream_format == "ndjson":
                        if line.strip():
                            consume(line)
                    elif line.startswith("data:"):
                        event_data.append(line[5:].lstrip(" "))
                    elif not line:
                        if event_data:
                            consume("\n".join(event_data))
                            event_data = []
                    elif line.startswith((":", "event:", "id:", "retry:")):
                        continue
                    else:
                        raise ModelError(
                            "invalid_stream",
                            "接口未返回 SSE 流，请确认服务地址支持流式 Chat Completions。",
                        )
                    if stream_ended:
                        break
                if event_data:
                    consume("\n".join(event_data))
            if not complete:
                raise ModelError(
                    "incomplete_stream", "模型流式响应意外中断，未保存不完整结果；请手动重试。"
                )
            text = "".join(fragments).strip()
            if not text:
                raise ModelError("empty_response", "模型没有返回正文，请检查模型或增加输出长度。")
            metrics["total_ms"] = round((time.monotonic() - started) * 1000, 1)
            return {
                "text": text,
                "model": {
                    "provider": profile["provider"],
                    "profile_id": profile["id"],
                    "model_id": profile["model_id"],
                    "config_revision": snapshot["config_revision"],
                },
                "usage": usage,
                "metrics": metrics,
            }
        except ModelError:
            raise
        except httpx.TimeoutException:
            raise ModelError(
                "timeout", "模型请求超时，未自动重试；请检查网络或调整超时后重试。"
            ) from None
        except httpx.HTTPError:
            raise ModelError(
                "connection_failed", "无法连接模型服务，请检查地址、网络和 TLS 证书。"
            ) from None
        except Exception:
            raise ModelError(
                "generation_failed", "模型生成未完成，请检查连接配置后手动重试。"
            ) from None

    def list_models(self, profile_id):
        with self._lock:
            profile = self._snapshot_profile(self._profile(profile_id))
        headers = self._headers(profile)
        headers["Accept"] = "application/json"
        adapter = ModelFactory.create(profile)
        try:
            with self.client.stream(
                "GET",
                profile["base_url"] + adapter.models_path,
                headers=headers,
                timeout=profile["timeout_seconds"],
                follow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise _http_error(response.status_code, model_list=True)
                data = b""
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > 2 * 1024 * 1024:
                        raise ModelError("response_too_large", "模型列表过大，请手动填写模型 ID。")
                value = json.loads(data)
            entries = value.get(adapter.models_key)
            if not isinstance(entries, list):
                raise TypeError
            key = adapter.model_name_key
            names = sorted(
                {
                    item[key]
                    for item in entries
                    if isinstance(item, dict)
                    and isinstance(item.get(key), str)
                    and 0 < len(item[key]) <= 200
                    and all(ord(c) >= 32 for c in item[key])
                }
            )
            return {"models": names}
        except ModelError:
            raise
        except httpx.TimeoutException:
            raise ModelError("timeout", "获取模型列表超时，可手动填写模型 ID。") from None
        except httpx.HTTPError:
            raise ModelError(
                "connection_failed", "无法连接模型服务，可检查地址或手动填写模型 ID。"
            ) from None
        except Exception:
            raise ModelError(
                "invalid_model_list", "服务未返回有效模型列表，请手动填写模型 ID。"
            ) from None

    def _check_ollama_thinking(self, profile, headers):
        with self.client.stream(
            "POST",
            profile["base_url"] + "/api/show",
            json={"model": profile["model_id"]},
            headers={**headers, "Accept": "application/json"},
            timeout=profile["timeout_seconds"],
            follow_redirects=False,
        ) as response:
            if not 200 <= response.status_code < 300:
                raise _http_error(response.status_code)
            data = b""
            for chunk in response.iter_bytes():
                data += chunk
                if len(data) > 2 * 1024 * 1024:
                    raise ModelError(
                        "response_too_large", "本地模型能力信息过大，请选择模型默认思考模式。"
                    )
            try:
                value = json.loads(data)
                supports = isinstance(value, dict) and "thinking" in value.get("capabilities", [])
                descriptor = value.get("thinking") if isinstance(value, dict) else None
                if descriptor is not None:
                    values = descriptor.get("values", []) if isinstance(descriptor, dict) else []
                    requested = profile["thinking"] == "enabled"
                    supports = (
                        supports
                        and isinstance(values, list)
                        and any(type(option) is bool and option is requested for option in values)
                    )
                elif profile["thinking"] == "disabled" and isinstance(value, dict):
                    details = value.get("details") or {}
                    template = value.get("template")
                    if (
                        isinstance(details, dict)
                        and details.get("family") == "qwen3"
                        and isinstance(template, str)
                        and hashlib.sha256(template.encode()).hexdigest()
                        == LEGACY_QWEN3_ALWAYS_THINK_TEMPLATE
                    ):
                        raise ModelError(
                            "unsupported_thinking",
                            "当前 Qwen3 旧模板无法可靠关闭思考，可能把分析混入正文。"
                            "请将思考模式设为“模型默认”或“开启”，再测试连接。",
                        )
            except ModelError:
                raise
            except (ValueError, TypeError):
                supports = False
            if not supports:
                raise ModelError(
                    "unsupported_thinking",
                    "本地模型未声明支持所选思考开关，请选择“模型默认”或使用支持该开关的模型。",
                )

    def transcribe(self, snapshot, wav_path):
        if snapshot.get("generation_mode") != "independent" or snapshot.get("capability") != "asr":
            raise ModelError("unsupported_capability", "语音转写需要明确配置的 ASR 能力。")
        profile = self._normalize_profile(snapshot, snapshot)
        if "asr" not in profile["capabilities"] or not profile["model_id"]:
            raise ModelError("missing_model", "请先配置语音转写能力与模型 ID。")
        audio = read_wav(wav_path)
        url, arguments = audio_request(profile, audio)
        headers = self._headers(profile)
        headers["Accept"] = "application/json"
        if "files" in arguments:
            headers.pop("Content-Type", None)
        error_prefix = ""
        try:
            started = time.monotonic()
            with self.client.stream(
                "POST", url, headers=headers, **arguments,
                timeout=httpx.Timeout(profile["timeout_seconds"], connect=15),
                follow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    error_prefix = f"HTTP {response.status_code}："
                    # DashScope reports a silent interval as a typed 400 response.
                    # Consume only a bounded JSON body; never expose its free text.
                    if response.status_code == 400 and profile["audio_api_style"] == "dashscope":
                        try:
                            value = self._audio_json(response, started, profile["timeout_seconds"])
                        except ModelError as error:
                            raise ModelError(error.code, "HTTP 400：" + error.message) from None
                        if value.get("code") == "ASR_RESPONSE_HAVE_NO_WORDS":
                            return ""
                    raise _http_error(response.status_code)
                value = self._audio_json(response, started, profile["timeout_seconds"])
            if value.get("error") or value.get("code"):
                raise ModelError("provider_error", "转写服务返回错误，请检查服务商控制台。")
            if profile["audio_api_style"] == "openai_audio":
                text = value.get("text")
            else:
                output = value.get("output", {})
                choices = output.get("choices", [])
                content = choices[0].get("message", {}).get("content", []) if choices else []
                text = "\n".join(item["text"] for item in content
                                 if isinstance(item, dict) and isinstance(item.get("text"), str))
                if not content:
                    text = output.get("text")
            if not isinstance(text, str):
                raise ModelError("invalid_response", "转写接口没有返回有效文本字段。")
            return text.strip()
        except ModelError:
            raise
        except httpx.TimeoutException:
            raise ModelError(
                "timeout", error_prefix + "转写请求超时，未自动重试；请确认后手动重试。"
            ) from None
        except httpx.HTTPError:
            raise ModelError(
                "connection_failed", error_prefix + "无法连接转写服务，请检查地址与网络。"
            ) from None
        except Exception:
            raise ModelError(
                "transcription_failed", error_prefix + "转写未完成，请检查接口配置后手动重试。"
            ) from None

    @staticmethod
    def _audio_json(response, started, timeout):
        content = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() - started > timeout:
                raise ModelError("timeout", "转写响应超时，未自动重试。")
            if len(content) + len(chunk) > 2 * 1024 * 1024:
                raise ModelError("response_too_large", "转写响应超过大小限制。")
            content.extend(chunk)
        try:
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, TypeError):
            raise ModelError("invalid_response", "转写接口返回无效 JSON。") from None

    def test_connection(self, profile_id, on_event=None, *, capability="text"):
        snapshot = self.profile_snapshot(profile_id, capability)
        try:
            if capability == "asr":
                started = time.monotonic()
                with test_wav() as audio:
                    text = self.transcribe(snapshot, audio)
                result = {"text": text, "model": {"profile_id": profile_id,
                          "model_id": snapshot["model_id"], "provider": snapshot["provider"]},
                          "usage": {"input_tokens": None, "output_tokens": None},
                          "metrics": {"first_event_ms": None, "first_text_ms": None,
                                      "total_ms": round((time.monotonic() - started) * 1000, 1)}}
            elif capability == "vision":
                result = self.generate(snapshot, "连接测试：请描述图片颜色。", on_event,
                                       images=[test_image()])
            else:
                result = self.generate(snapshot, "这是连接测试。请只回复两个汉字：你好。", on_event)
        except ModelError:
            self._record_test(profile_id, snapshot["profile_revision"], False, capability)
            raise
        applied = self._record_test(profile_id, snapshot["profile_revision"], True, capability)
        return dict(result, success=True, capability=capability,
                    tested_revision=snapshot["profile_revision"], current_config_tested=applied)

    def _record_test(self, identity, revision, success, capability="text"):
        with self._lock:
            profile = next((p for p in self._config["profiles"] if p["id"] == identity), None)
            if profile is None or profile["revision"] != revision:
                return False
            updated = deepcopy(self._config)
            target = next(p for p in updated["profiles"] if p["id"] == identity)
            if capability == "text":
                target.update(tested_revision=revision if success else None,
                              tested_at=time.time(), test_status="passed" if success else "failed")
            else:
                target["capability_test_status"][capability] = {
                    "tested_revision": revision if success else None,
                    "tested_at": time.time(), "status": "passed" if success else "failed",
                }
            try:
                atomic_json(self.path, updated)
            except Exception:
                raise ModelError(
                    "test_status_save_failed",
                    "连接测试已结束，但测试状态保存失败，请检查数据目录权限。",
                ) from None
            self._config = updated
            return True
