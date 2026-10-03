import json

import httpx
import pytest

from local_app.models import MemoryCredentialStore, ModelError, ModelService
from local_app.models.providers import PROVIDERS, normalize_url, request_body


@pytest.fixture
def service(tmp_path):
    value = ModelService(tmp_path, MemoryCredentialStore())
    yield value
    value.close()


def add(service, provider="custom", **kwargs):
    profile = {
        "provider": provider,
        "name": "测试连接",
        "base_url": "http://127.0.0.1:18999/v1",
        "model_id": "test-model",
        **kwargs,
    }
    return service.save_config({"profile": profile})["profiles"][-1]


def activate(service, profile):
    service.save_config({"default_profile": profile["id"], "generation_mode": "independent"})
    return service.snapshot("qa")


def stream(*values, done=True):
    body = "".join(
        "data: " + json.dumps(value, ensure_ascii=False) + "\r\n\r\n" for value in values
    )
    if done:
        body += "data: [DONE]\n\n"
    return body.encode()


def delta(text, **kwargs):
    return {"choices": [{"delta": {"content": text}, **kwargs}]}


def mock(service, handler):
    service.client.close()
    service.client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


def test_host_default_has_no_side_effect(service):
    assert service.snapshot("ingest") == {"generation_mode": "host", "config_revision": 0}
    assert not service.path.exists()
    assert len(service.public_config()["providers"]) == 6


def test_secret_never_written_and_snapshot_uses_immutable_credential(service):
    profile = add(service, api_key="synthetic-key-one")
    before = activate(service, profile)
    service.save_config({"profile": {"id": profile["id"], "api_key": "synthetic-key-two"}})
    after = service.snapshot("qa")
    assert before["credential_ref"] != after["credential_ref"]
    assert service._headers(before)["Authorization"] == "Bearer synthetic-key-one"
    assert service._headers(after)["Authorization"] == "Bearer synthetic-key-two"
    assert not any(
        key in json.dumps(service.public_config())
        for key in ("synthetic-key", "credential_ref", "credential_history")
    )
    assert "synthetic-key" not in service.path.read_text()
    assert "synthetic-key" not in json.dumps(before)
    assert service.path.stat().st_mode & 0o777 == 0o600


def test_snapshots_remain_stable_after_configuration_changes(service):
    profile = add(service)
    before = activate(service, profile)
    service.save_config({"profile": {"id": profile["id"], "model_id": "new-model"}})
    after = service.snapshot("qa")
    assert before["model_id"] == "test-model" and after["model_id"] == "new-model"
    assert before["config_revision"] < after["config_revision"]


def test_clear_revokes_all_versions_without_falling_back(service):
    profile = add(service, api_key="synthetic-key-one")
    before = activate(service, profile)
    service.save_config({"profile": {"id": profile["id"], "api_key": "synthetic-key-two"}})
    after = service.snapshot("qa")
    service.save_config({"profile": {"id": profile["id"], "clear_key": True}})
    for snapshot in (before, after):
        with pytest.raises(ModelError, match="已删除"):
            service._headers(snapshot)


def test_credentials_isolated_between_instances_and_deletion(service, tmp_path):
    other = ModelService(tmp_path / "other", service.credentials)
    try:
        first = add(service, api_key="synthetic-first")
        second = add(other, api_key="synthetic-second")
        first_snap = activate(service, first)
        other_snap = activate(other, second)
        assert first_snap["credential_ref"] != other_snap["credential_ref"]
        with pytest.raises(ModelError) as exc:
            other._headers(first_snap)
        assert exc.value.code == "invalid_credential_reference"
        service.save_config({"generation_mode": "host", "default_profile": None})
        service.delete_profile(first["id"])
        assert other._headers(other_snap)["Authorization"] == "Bearer synthetic-second"
        with pytest.raises(ModelError):
            service._headers(first_snap)
    finally:
        other.close()


def test_cloud_key_and_routes_required_before_activation(service):
    profile = add(
        service, "qwen", base_url=PROVIDERS["qwen"]["default_base_url"], model_id="qwen-plus"
    )
    with pytest.raises(ModelError) as exc:
        activate(service, profile)
    assert exc.value.code == "missing_api_key"
    assert service.public_config()["generation_mode"] == "host"
    service.save_config({"profile": {"id": profile["id"], "api_key": "synthetic-test"}})
    activate(service, profile)
    with pytest.raises(ModelError):
        service.save_config({"profile": {"id": profile["id"], "clear_key": True}})
    assert service.public_config()["profiles"][0]["credential_present"]


def test_task_override_and_delete_guard(service):
    first, second = add(service), add(service, name="第二连接", model_id="other")
    activate(service, first)
    service.save_config({"task_profiles": {"ingest": second["id"]}})
    assert service.snapshot("ingest")["id"] == second["id"]
    assert service.snapshot("qa")["id"] == first["id"]
    with pytest.raises(ModelError) as exc:
        service.delete_profile(second["id"])
    assert exc.value.code == "profile_in_use"
    service.save_config({"task_profiles": {"ingest": None}})
    assert len(service.delete_profile(second["id"])["profiles"]) == 1


def test_no_credential_fallback_on_unavailable_store(tmp_path):
    class BrokenStore:
        def get(self, reference):
            raise RuntimeError("synthetic-private-error")

        def set(self, reference, key):
            raise RuntimeError(key)

        def delete(self, reference):
            pass

    service = ModelService(tmp_path, BrokenStore())
    try:
        with pytest.raises(ModelError) as exc:
            add(service, api_key="synthetic-private-key")
        assert "synthetic-private" not in str(exc.value)
        assert not service.path.exists()
    finally:
        service.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://user:password@example.com/v1",
        "https://example.com/v1?key=secret",
        "https://example.com/v1#secret",
        "https://example.com:0/v1",
        "https://example.com:wrong/v1",
        "https://example.com/../v1",
        "https://example.com/%2e%2e/v1",
        "https://example.com\\other",
        "https://{workspace}.example.com/v1",
        " https://example.com/v1",
        "file:///etc/passwd",
        "https://example.com/v1?",
    ],
)
def test_reject_unsafe_urls_without_echoing_them(url):
    with pytest.raises(ModelError) as exc:
        normalize_url(url)
    assert "password" not in str(exc.value) and "secret" not in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434/",
        "http://[::1]:11434",
        "https://example.com/api/v4/",
    ],
)
def test_allow_https_and_loopback(url):
    assert normalize_url(url) == url.rstrip("/")


def test_endpoint_change_cannot_send_old_key_to_new_host(service):
    profile = add(service, api_key="synthetic-secret")
    with pytest.raises(ModelError) as exc:
        service.save_config(
            {"profile": {"id": profile["id"], "base_url": "https://another.example/v1"}}
        )
    assert exc.value.code == "credential_endpoint_changed"
    assert service.public_config()["profiles"][0]["base_url"] == profile["base_url"]


def test_direct_streaming_preserves_unicode_counts_and_emits_only_answer(service):
    profile = add(service)
    snapshot = activate(service, profile)
    requests, events = [], []

    class SplitStream(httpx.SyncByteStream):
        def __iter__(self):
            payload = stream(
                {"choices": [{"delta": {"reasoning_content": "private reasoning"}}]},
                delta("你"),
                delta("好", finish_reason="stop"),
                {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
            )
            for index in range(0, len(payload), 2):
                yield payload[index : index + 2]

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=SplitStream())

    mock(service, handler)
    result = service.generate(snapshot, "测试文本", events.append)
    assert result["text"] == "你好"
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 2}
    assert (
        result["metrics"]["total_ms"]
        >= result["metrics"]["first_text_ms"]
        >= result["metrics"]["first_event_ms"]
    )
    assert [event["text"] for event in events if event["type"] == "delta"] == ["你", "好"]
    assert "private reasoning" not in json.dumps(result) + json.dumps(events)
    assert str(requests[0].url) == "http://127.0.0.1:18999/v1/chat/completions"
    body = json.loads(requests[0].content)
    assert body["stream"] is True and body["messages"][0]["content"] == "测试文本"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication_failed"),
        (403, "authentication_failed"),
        (429, "rate_limited"),
        (302, "redirect_rejected"),
        (500, "provider_unavailable"),
        (404, "not_found"),
        (400, "request_rejected"),
    ],
)
def test_http_errors_are_redacted_and_never_retried_or_redirected(service, status, code):
    snapshot = activate(service, add(service, api_key="synthetic-sensitive"))
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://other.example"},
            text="synthetic-sensitive and private prompt",
        )

    mock(service, handler)
    with pytest.raises(ModelError) as exc:
        service.generate(snapshot, "private prompt")
    assert exc.value.code == code
    assert "synthetic-sensitive" not in str(exc.value) and "private prompt" not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "response,code",
    [
        (b"not SSE", "invalid_stream"),
        (b"data: secret malformed JSON\n\n", "invalid_stream"),
        (stream(delta("partial"), done=False), "incomplete_stream"),
        (stream(delta("")), "empty_response"),
        (stream({"error": {"message": "synthetic-sensitive"}}), "provider_error"),
        (stream(delta("part", finish_reason="length")), "output_truncated"),
        (stream({"choices": [{"delta": {"content": ["bad"]}}]}), "invalid_stream"),
        (stream({"choices": ["bad"]}), "invalid_stream"),
        (stream({"choices": [], "usage": "bad"}), "invalid_stream"),
    ],
)
def test_bad_streams_never_become_success(service, response, code):
    snapshot = activate(service, add(service))
    mock(service, lambda request: httpx.Response(200, content=response))
    with pytest.raises(ModelError) as exc:
        service.generate(snapshot, "test")
    assert exc.value.code == code
    assert "synthetic-sensitive" not in str(exc.value)


def test_timeout_no_retry_and_no_exception_leak(service):
    snapshot = activate(service, add(service))
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("synthetic-sensitive", request=request)

    mock(service, handler)
    with pytest.raises(ModelError) as exc:
        service.generate(snapshot, "test")
    assert exc.value.code == "timeout" and "synthetic-sensitive" not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "provider,model,key,value",
    [
        ("qwen", "qwen-plus", "enable_thinking", False),
        ("kimi", "kimi-k2.5", "thinking", {"type": "disabled"}),
        ("glm", "glm-4.7", "thinking", {"type": "disabled"}),
        ("deepseek", "deepseek-flash", "thinking", {"type": "disabled"}),
    ],
)
def test_provider_specific_thinking_at_wire_top_level(provider, model, key, value):
    profile = {
        "provider": provider,
        "model_id": model,
        "thinking": "disabled",
        "max_output_tokens": 4096,
    }
    body = request_body(profile, "hi")
    assert body[key] == value and "extra_body" not in body
    if provider == "kimi":
        assert body["temperature"] == 0.6
    profile["thinking"] = "default"
    assert key not in request_body(profile, "hi")


def test_unknown_model_does_not_silently_ignore_thinking(service):
    with pytest.raises(ModelError) as exc:
        add(service, "qwen", model_id="unverified-model", thinking="enabled")
    assert exc.value.code == "unsupported_thinking"


def test_ollama_native_stream_and_models(service):
    profile = add(service, "ollama", base_url="http://localhost:11434", model_id="local-test")
    snapshot = activate(service, profile)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "local-test"}]})
        body = json.loads(request.content)
        assert body["options"] == {"num_predict": 4096}
        assert "max_tokens" not in body and "Authorization" not in request.headers
        content = "\n".join(
            json.dumps(value, ensure_ascii=False)
            for value in [
                {"message": {"content": "你好"}, "done": False},
                {"message": {"content": ""}, "done": True, "prompt_eval_count": 4, "eval_count": 2},
            ]
        )
        return httpx.Response(200, content=content.encode())

    mock(service, handler)
    assert service.list_models(profile["id"]) == {"models": ["local-test"]}
    result = service.generate(snapshot, "hi")
    assert result["text"] == "你好" and result["usage"]["input_tokens"] == 4
    assert requests[-1].url.path == "/api/chat"


def test_test_revision_invalidates_and_empty_key_preserves(service):
    profile = add(service, api_key="synthetic-test")
    mock(
        service,
        lambda request: httpx.Response(200, content=stream(delta("你好", finish_reason="stop"))),
    )
    result = service.test_connection(profile["id"])
    tested = service.public_config()["profiles"][0]
    assert result["success"] is True and tested["tested_revision"] == tested["revision"]
    service.save_config({"profile": {"id": profile["id"], "api_key": ""}})
    assert service.public_config()["profiles"][0]["test_status"] == "passed"
    service.save_config({"profile": {"id": profile["id"], "model_id": "other-model"}})
    current = service.public_config()["profiles"][0]
    assert (
        current["credential_present"]
        and current["tested_revision"] is None
        and current["test_status"] == "untested"
    )


def test_completed_test_cannot_mark_new_config_as_tested(service):
    profile = add(service)

    def handler(request):
        service.save_config({"profile": {"id": profile["id"], "model_id": "new"}})
        return httpx.Response(200, content=stream(delta("你好", finish_reason="stop")))

    mock(service, handler)
    result = service.test_connection(profile["id"])
    assert result["current_config_tested"] is False
    assert service.public_config()["profiles"][0]["test_status"] == "untested"


def test_config_round_trip_and_corruption_fail_closed(service):
    profile = add(service)
    activate(service, profile)
    restored = ModelService(service.data_dir, service.credentials)
    try:
        assert restored.public_config() == service.public_config()
    finally:
        restored.close()
    service.path.write_text('{"schema_version": 999}', encoding="utf-8")
    with pytest.raises(ModelError) as exc:
        ModelService(service.data_dir, service.credentials)
    assert exc.value.code == "config_unreadable"
    assert service.path.read_text() == '{"schema_version": 999}'


def test_list_models_deduplicates_valid_ids(service):
    profile = add(service)
    mock(
        service,
        lambda request: httpx.Response(
            200,
            json={"data": [{"id": "z"}, {"id": "a"}, {"id": "a"}, {"id": "bad\nvalue"}, {"id": 1}]},
        ),
    )
    assert service.list_models(profile["id"]) == {"models": ["a", "z"]}


def test_runtime_ignores_proxy_environment(service, monkeypatch, tmp_path):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    instance = ModelService(tmp_path / "proxy", MemoryCredentialStore())
    try:
        assert instance.client._trust_env is False
        assert instance.client.follow_redirects is False
        assert instance.client._mounts == {}
    finally:
        instance.close()


@pytest.mark.parametrize(
    "capabilities,allowed",
    [(["completion", "thinking"], True), (["completion"], False), ([], False)],
)
def test_ollama_thinking_uses_verified_capability_and_native_boolean(
    service, capabilities, allowed
):
    profile = add(
        service,
        "ollama",
        base_url="http://localhost:11434",
        model_id="qwen3:0.6b",
        thinking="disabled",
    )
    snapshot = activate(service, profile)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/show":
            assert json.loads(request.content) == {"model": "qwen3:0.6b"}
            return httpx.Response(200, json={"capabilities": capabilities})
        assert json.loads(request.content)["think"] is False
        assert "thinking" not in json.loads(request.content)
        return httpx.Response(
            200, json={"message": {"content": "你好"}, "done": True, "done_reason": "stop"}
        )

    mock(service, handler)
    if allowed:
        assert service.generate(snapshot, "hi")["text"] == "你好"
        assert len(requests) == 2
    else:
        with pytest.raises(ModelError) as exc:
            service.generate(snapshot, "hi")
        assert exc.value.code == "unsupported_thinking" and len(requests) == 1


@pytest.mark.parametrize(
    "reason,tools,code",
    [
        ("length", [], "output_truncated"),
        ("unknown", [], "unsupported_result"),
        ("stop", [{"function": {"name": "test"}}], "unsupported_result"),
    ],
)
def test_ollama_incomplete_or_tool_output_cannot_be_saved(service, reason, tools, code):
    snapshot = activate(service, add(service, "ollama"))
    mock(
        service,
        lambda request: httpx.Response(
            200,
            json={
                "message": {"content": "partial", "tool_calls": tools},
                "done": True,
                "done_reason": reason,
            },
        ),
    )
    with pytest.raises(ModelError) as exc:
        service.generate(snapshot, "hi")
    assert exc.value.code == code


def test_factory_chooses_distinct_provider_adapters():
    from local_app.models import ModelFactory

    adapters = [type(ModelFactory.create({"provider": name})) for name in PROVIDERS]
    assert len(set(adapters)) == 6


def test_ollama_model_with_named_thinking_levels_cannot_silently_ignore_boolean(service):
    profile = add(service, "ollama", thinking="disabled")
    snapshot = activate(service, profile)
    mock(
        service,
        lambda request: httpx.Response(
            200,
            json={
                "capabilities": ["completion", "thinking"],
                "thinking": {"values": ["low", "high"], "default": "high"},
            },
        ),
    )
    with pytest.raises(ModelError) as exc:
        service.generate(snapshot, "hi")
    assert exc.value.code == "unsupported_thinking"


@pytest.mark.parametrize("payload", [{"default_profile": False}, {"task_profiles": {"qa": []}}])
def test_invalid_route_types_cannot_silently_clear_existing_selection(service, payload):
    profile = add(service)
    activate(service, profile)
    previous = service.public_config()
    with pytest.raises(ModelError) as exc:
        service.save_config(payload)
    assert exc.value.code == "invalid_route"
    assert service.public_config() == previous


# Captured official Ollama Qwen3 template from the real content-contamination regression.
LEGACY_QWEN3_TEMPLATE = '{{- $lastUserIdx := -1 -}}\n{{- range $idx, $msg := .Messages -}}\n{{- if eq $msg.Role "user" }}{{ $lastUserIdx = $idx }}{{ end -}}\n{{- end }}\n{{- if or .System .Tools }}<|im_start|>system\n{{ if .System }}{{ .System }}\n\n{{ end }}\n{{- if .Tools }}# Tools\n\nYou may call one or more functions to assist with the user query.\n\nYou are provided with function signatures within <tools></tools> XML tags:\n<tools>\n{{- range .Tools }}\n{"type": "function", "function": {{ .Function }}}\n{{- end }}\n</tools>\n\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>\n{{- end -}}\n<|im_end|>\n{{ end }}\n{{- range $i, $_ := .Messages }}\n{{- $last := eq (len (slice $.Messages $i)) 1 -}}\n{{- if eq .Role "user" }}<|im_start|>user\n{{ .Content }}<|im_end|>\n{{ else if eq .Role "assistant" }}<|im_start|>assistant\n{{ if (and $.IsThinkSet (and .Thinking (or $last (gt $i $lastUserIdx)))) -}}\n<think>{{ .Thinking }}</think>\n{{ end -}}\n{{ if .Content }}{{ .Content }}{{ end }}\n{{- if .ToolCalls }}\n{{- range .ToolCalls }}\n<tool_call>\n{"name": "{{ .Function.Name }}", "arguments": {{ .Function.Arguments }}}\n</tool_call>\n{{- end }}\n{{- end }}{{ if not $last }}<|im_end|>\n{{ end }}\n{{- else if eq .Role "tool" }}<|im_start|>user\n<tool_response>\n{{ .Content }}\n</tool_response><|im_end|>\n{{ end }}\n{{- if and (ne .Role "assistant") $last }}<|im_start|>assistant\n<think>\n{{ end }}\n{{- end }}'


def test_legacy_qwen3_template_rejects_disabled_before_generation(service):
    profile = add(service, "ollama", model_id="qwen3:4b", thinking="disabled")
    snapshot = activate(service, profile)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path.endswith("/api/show")
        return httpx.Response(
            200,
            json={
                "capabilities": ["completion", "thinking"],
                "details": {"family": "qwen3"},
                "template": LEGACY_QWEN3_TEMPLATE,
            },
        )

    mock(service, handler)
    with pytest.raises(ModelError) as exc:
        service.generate(snapshot, "请整理真实资料")
    assert exc.value.code == "unsupported_thinking"
    assert "旧模板" in exc.value.message and "模型默认" in exc.value.message
    assert len(requests) == 1
    assert service.public_config()["profiles"][0]["thinking"] == "disabled"


@pytest.mark.parametrize(
    "mode,kind",
    [
        ("enabled", "legacy"),
        ("default", "legacy"),
        ("disabled", "new_template"),
        ("disabled", "declared_values"),
        ("disabled", "unrelated_family"),
    ],
)
def test_ollama_safe_controls_keep_wire_choice_and_literal_user_markup(service, mode, kind):
    profile = add(service, "ollama", model_id="qwen3:4b", thinking=mode)
    snapshot = activate(service, profile)
    events = []
    literal = "教程正文中的字面量 <think>示例</think> 不得被删除。"
    metadata = {
        "capabilities": ["completion", "thinking"],
        "details": {"family": "qwen3"},
        "template": LEGACY_QWEN3_TEMPLATE,
    }
    if kind == "new_template":
        metadata["template"] = LEGACY_QWEN3_TEMPLATE.replace(
            "<think>\n{{ end }}",
            "{{ if .Think }}<think>{{ else }}<think></think>{{ end }}\n{{ end }}",
        )
        assert metadata["template"] != LEGACY_QWEN3_TEMPLATE
    elif kind == "declared_values":
        metadata["thinking"] = {"values": [False, True], "default": True}
    elif kind == "unrelated_family":
        metadata["details"]["family"] = "different-family"

    def handler(request):
        if request.url.path.endswith("/api/show"):
            return httpx.Response(200, json=metadata)
        body = json.loads(request.content)
        if mode == "default":
            assert "think" not in body
        else:
            assert body["think"] is (mode == "enabled")
        return httpx.Response(
            200,
            json={
                "message": {"content": literal, "thinking": "synthetic private reasoning"},
                "done": True,
                "done_reason": "stop",
            },
        )

    mock(service, handler)
    result = service.generate(snapshot, "hi", events.append)
    assert result["text"] == literal
    assert "synthetic private reasoning" not in json.dumps(result) + json.dumps(events)
