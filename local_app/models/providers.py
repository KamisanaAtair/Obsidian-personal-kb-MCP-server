"""Provider presets and explicit capability mapping, checked against official docs.

Sources (Qwen connection guidance rechecked 2026-10-04):
https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
https://help.aliyun.com/zh/model-studio/base-url
https://help.aliyun.com/zh/model-studio/coding-plan
https://help.aliyun.com/zh/model-studio/deep-thinking
https://huggingface.co/moonshotai/Kimi-K2.5
https://raw.githubusercontent.com/MoonshotAI/kimi-cli/main/packages/kosong/src/kosong/chat_provider/kimi.py
https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode.md
https://api-docs.deepseek.com/guides/thinking_mode/
https://docs.ollama.com/api/chat

Listed models are suggestions, not a claim about account access. Unknown model IDs
can always be used with provider defaults; optional thinking needs known support.
"""

import ipaddress
import re
from copy import deepcopy
from typing import ClassVar
from urllib.parse import urlsplit, urlunsplit

from .errors import ModelError

# The official legacy Qwen3 template always prefills "<think>". On Ollama
# 0.33.3, think=false disables reasoning separation without removing that prefill,
# causing reasoning to appear in content. Exact blob matching avoids interpreting
# or stripping user/model prose, or rejecting unrelated/custom model templates.
# https://registry.ollama.ai/v2/library/qwen3/blobs/sha256:2d54db2b9bb29ce7db54fea63a891f5859603813c555b1f88b5e0994652897f9
LEGACY_QWEN3_ALWAYS_THINK_TEMPLATE = (
    "2d54db2b9bb29ce7db54fea63a891f5859603813c555b1f88b5e0994652897f9"
)

PROVIDERS = {
    "qwen": {
        "name": "Qwen · 百炼按量 API",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "api_style": "openai_chat",
        "thinking_models": [
            "qwen-plus",
            "qwen-plus-latest",
            "qwen-flash",
            "qwen-turbo",
            "qwen3-max",
            "qwen3.5-plus",
            "qwen3.6-plus",
            "qwen3.7-plus",
            "qwen3.8-max",
        ],
        "help_url": "https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope",
        "hint": (
            "普通百炼按量 API，非 Coding Plan 套餐。Key、地域和业务空间须匹配；"
            "支持控制台提供的业务空间专属 Base URL。"
        ),
        "regions": [
            {"name": "中国北京", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
            {
                "name": "新加坡",
                "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            },
            {
                "name": "美国弗吉尼亚",
                "base_url": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            },
        ],
    },
    "kimi": {
        "name": "Kimi",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2.5",
        "api_style": "openai_chat",
        "thinking_models": ["kimi-k2.5"],
        "help_url": "https://platform.kimi.com/docs/guide/use-thinking-models",
        "hint": "使用 Kimi 开放平台 API Key；Kimi Code 订阅凭据不能替代开放平台密钥。",
    },
    "glm": {
        "name": "智谱 GLM",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4.7",
        "api_style": "openai_chat",
        "thinking_models": ["glm-4.5", "glm-4.5-air", "glm-4.6", "glm-4.7", "glm-4.7-flash"],
        "help_url": "https://docs.bigmodel.cn/cn/guide/develop/openai/introduction",
        "hint": "使用智谱开放平台通用 API Key 与地址；Coding Plan 专用端点需按订阅文档配置。",
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-flash",
        "api_style": "openai_chat",
        "thinking_models": ["deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash"],
        "help_url": "https://api-docs.deepseek.com/guides/thinking_mode/",
        "hint": "直连 DeepSeek 官方接口；旧模型名称请以控制台当前模型列表为准。",
    },
    "ollama": {
        "name": "本地 Ollama",
        "default_base_url": "http://127.0.0.1:11434",
        "default_model": "",
        "api_style": "ollama_chat",
        "thinking_models": [],
        "thinking_dynamic": True,
        "help_url": "https://docs.ollama.com/api/chat",
        "hint": "先启动 Ollama 并下载模型，再获取本机模型列表；不会自动下载模型。",
    },
    "custom": {
        "name": "自定义兼容服务",
        "default_base_url": "",
        "default_model": "",
        "api_style": "openai_chat",
        "thinking_models": [],
        "help_url": "",
        "hint": "填写兼容 Chat Completions 的服务地址和模型 ID；远程连接须使用 HTTPS。",
    },
}


def catalog():
    return [
        dict(
            deepcopy(value),
            id=key,
            supports_thinking=bool(value["thinking_models"])
            or value.get("thinking_dynamic", False),
        )
        for key, value in PROVIDERS.items()
    ]


def is_loopback(hostname):
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def normalize_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ModelError("invalid_url", "请填写有效的模型服务地址。")
    if any(ord(c) < 33 for c in value) or any(c in value for c in "\\{}"):
        raise ModelError("invalid_url", "服务地址不能包含空白、反斜杠或占位符。")
    try:
        url = urlsplit(value)
        port = url.port
        if (
            url.scheme not in {"https", "http"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or "?" in value
            or "#" in value
        ):
            raise ValueError
        if url.scheme == "http" and not is_loopback(url.hostname):
            raise ModelError(
                "insecure_url", "远程模型服务必须使用 HTTPS；只有本机回环地址允许 HTTP。"
            )
        if port == 0 or not re.fullmatch(r"[A-Za-z0-9.:[\]-]+", url.netloc):
            raise ValueError
        if "%" in url.path or any(part in {".", ".."} for part in url.path.split("/")):
            raise ValueError
        return urlunsplit((url.scheme, url.netloc.lower(), url.path.rstrip("/"), "", ""))
    except ModelError:
        raise
    except ValueError:
        raise ModelError(
            "invalid_url", "服务地址不能包含凭据、查询参数、片段或无效端口。"
        ) from None


def requires_key(profile):
    return not (
        profile["provider"] in {"ollama", "custom"}
        and is_loopback(urlsplit(profile["base_url"]).hostname)
    )


class CompatibleAdapter:
    chat_path = "/chat/completions"
    models_path = "/models"
    models_key = "data"
    model_name_key = "id"
    stream_format = "sse"

    def __init__(self, profile):
        self.profile = profile

    def validate_thinking(self):
        if (
            self.profile["thinking"] != "default"
            and self.profile["model_id"]
            not in PROVIDERS[self.profile["provider"]]["thinking_models"]
        ):
            raise ModelError("unsupported_thinking", "该模型的思考开关尚未核验，请选择“模型默认”。")

    def request_body(self, prompt):
        self.validate_thinking()
        return {
            "model": self.profile["model_id"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": self.profile["max_output_tokens"],
        }


class QwenAdapter(CompatibleAdapter):
    def request_body(self, prompt):
        body = super().request_body(prompt)
        body["stream_options"] = {"include_usage": True}
        if self.profile["thinking"] != "default":
            body["enable_thinking"] = self.profile["thinking"] == "enabled"
        return body


class ThinkingObjectAdapter(CompatibleAdapter):
    def request_body(self, prompt):
        body = super().request_body(prompt)
        if self.profile["thinking"] != "default":
            body["thinking"] = {"type": self.profile["thinking"]}
        return body


class KimiAdapter(ThinkingObjectAdapter):
    def request_body(self, prompt):
        body = super().request_body(prompt)
        # Kimi K2.5's official model card recommends these sampling values.
        if self.profile["model_id"] == "kimi-k2.5":
            body["temperature"] = 0.6 if self.profile["thinking"] == "disabled" else 1.0
        return body


class GLMAdapter(ThinkingObjectAdapter):
    pass


class DeepSeekAdapter(ThinkingObjectAdapter):
    def request_body(self, prompt):
        body = super().request_body(prompt)
        body["stream_options"] = {"include_usage": True}
        return body


class OllamaAdapter(CompatibleAdapter):
    chat_path = "/api/chat"
    models_path = "/api/tags"
    models_key = "models"
    model_name_key = "name"
    stream_format = "ndjson"

    def validate_thinking(self):
        # Native Ollama capabilities are verified by /api/show immediately before
        # requesting generation, because a model tag can be replaced locally.
        pass

    def request_body(self, prompt):
        body = {
            "model": self.profile["model_id"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "options": {"num_predict": self.profile["max_output_tokens"]},
        }
        if self.profile["thinking"] != "default":
            body["think"] = self.profile["thinking"] == "enabled"
        return body


class ModelFactory:
    """Select a provider adapter, while ModelService owns one shared HTTP pool."""

    adapters: ClassVar[dict] = {
        "qwen": QwenAdapter,
        "kimi": KimiAdapter,
        "glm": GLMAdapter,
        "deepseek": DeepSeekAdapter,
        "ollama": OllamaAdapter,
        "custom": CompatibleAdapter,
    }

    @classmethod
    def create(cls, profile):
        provider = profile.get("provider")
        if provider not in cls.adapters:
            raise ModelError("invalid_provider", "请选择受支持的模型服务商。")
        return cls.adapters[provider](profile)


def request_body(profile, prompt):
    return ModelFactory.create(profile).request_body(prompt)
