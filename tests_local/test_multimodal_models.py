"""Media bytes and configuration contracts; synthetic input, no real provider calls."""

import base64
import json
import struct
import wave
import zlib

import httpx
import pytest

from local_app.models import MemoryCredentialStore, ModelError, ModelService
from local_app.models.multimodal import audio_request
from local_app.models.multimodal import test_image as sample_image
from local_app.models.multimodal import test_wav as sample_wav


@pytest.mark.parametrize("region", ["cn-beijing", "ap-southeast-1", "us-east-1"])
def test_dashscope_workspace_domain_stays_on_same_official_origin(region):
    origin = f"https://synthetic-workspace.{region}.maas.aliyuncs.com"
    endpoint, body = audio_request(
        {
            "base_url": origin + "/compatible-mode/v1",
            "audio_api_style": "dashscope",
            "model_id": "synthetic-asr",
        },
        b"synthetic",
    )
    assert endpoint == origin + "/api/v1/services/aigc/multimodal-generation/generation"
    assert "audio" in body["json"]["input"]["messages"][0]["content"][0]
    with pytest.raises(ModelError):
        audio_request(
            {
                "base_url": origin + ".evil.invalid/compatible-mode/v1",
                "audio_api_style": "dashscope",
                "model_id": "synthetic-asr",
            },
            b"",
        )


@pytest.fixture
def service(tmp_path):
    value = ModelService(tmp_path, MemoryCredentialStore())
    yield value
    value.close()


def add(service, **extra):
    return service.save_config(
        {
            "profile": {
                "provider": "custom",
                "name": "合成连接",
                "base_url": "http://127.0.0.1:18999/v1",
                "model_id": "text-model",
                "capabilities": ["text", "vision", "asr"],
                "capability_models": {"vision": "vision-model", "asr": "asr-model"},
                **extra,
            }
        }
    )["profiles"][-1]


def route(service, profile, capability):
    service.save_config({"capability_profiles": {capability: profile["id"]}})
    return service.snapshot(capability)


def mock(service, callback):
    service.client.close()
    service.client = httpx.Client(transport=httpx.MockTransport(callback), trust_env=False)


def success(request):
    if request.url.path.endswith("/api/chat"):
        return httpx.Response(200, text=json.dumps({"message": {"content": "红色"}, "done": True}))
    return httpx.Response(
        200,
        text='data: {"choices":[{"delta":{"content":"红色"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
    )


def test_historical_configuration_upgrades_in_memory_without_rewriting(service):
    profile = add(service)
    raw = json.loads(service.path.read_text())
    raw.pop("capability_profiles")
    for entry in raw["profiles"]:
        for key in (
            "capabilities",
            "capability_models",
            "audio_api_style",
            "capability_test_status",
        ):
            entry.pop(key)
    service.path.write_text(json.dumps(raw))
    before = service.path.read_bytes()
    other = ModelService(service.data_dir, service.credentials)
    try:
        value = other.public_config()
        assert value["profiles"][0]["capabilities"] == ["text"]
        assert value["capability_profiles"] == {"vision": None, "asr": None}
        assert other.path.read_bytes() == before
        with pytest.raises(ModelError) as exc:
            other.profile_snapshot(profile["id"], "vision")
        assert exc.value.code == "unsupported_capability"
    finally:
        other.close()


def test_explicit_routes_reuse_key_and_freeze_capability_model(service):
    profile = add(service, api_key="synthetic-key", thinking="default")
    text = service.profile_snapshot(profile["id"])
    visual = route(service, profile, "vision")
    asr = route(service, profile, "asr")
    assert service.snapshot("ingest")["generation_mode"] == "host"
    assert text["model_id"] == "text-model"
    assert visual["model_id"] == "vision-model" and visual["thinking"] == "default"
    assert asr["model_id"] == "asr-model"
    assert text["credential_ref"] == visual["credential_ref"] == asr["credential_ref"]
    service.save_config(
        {
            "profile": {
                "id": profile["id"],
                "capability_models": {"vision": "changed", "asr": "other-asr"},
            }
        }
    )
    assert visual["model_id"] == "vision-model"
    assert service.snapshot("vision")["model_id"] == "changed"
    assert service.verify_saved_key(profile["id"], "synthetic-key")
    assert not service.verify_saved_key(profile["id"], "synthetic-wrong")
    assert "synthetic-key" not in service.path.read_text()
    assert "synthetic-key" not in json.dumps(service.public_config())
    service.save_config({"profile": {"id": profile["id"], "clear_key": True}})
    with pytest.raises(ModelError) as exc:
        service._headers(asr)
    assert exc.value.code == "missing_api_key"


def test_audio_only_profile_can_save_but_cannot_be_text_route(service):
    profile = add(
        service, model_id="", capabilities=["asr"], capability_models={"vision": "", "asr": ""}
    )
    route_value = service.save_config({"capability_profiles": {"asr": profile["id"]}})
    assert route_value["capability_profiles"]["asr"] == profile["id"]
    with pytest.raises(ModelError) as exc:
        service.snapshot("asr")
    assert exc.value.code == "missing_model"
    with pytest.raises(ModelError) as exc:
        service.save_config({"generation_mode": "independent", "default_profile": profile["id"]})
    assert exc.value.code == "unsupported_capability"
    with pytest.raises(ModelError) as exc:
        service.delete_profile(profile["id"])
    assert exc.value.code == "profile_in_use"
    with pytest.raises(ModelError) as exc:
        service.snapshot("vision")
    assert exc.value.code == "missing_route"


@pytest.mark.parametrize("provider", ["custom", "ollama", "qwen", "kimi", "glm", "deepseek"])
def test_actual_png_is_sent_to_each_transport(service, provider):
    profile = add(service, provider=provider, api_key="synthetic-token")
    snapshot = route(service, profile, "vision")
    picture = sample_image()
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        message = body["messages"][0]
        if provider == "ollama":
            encoded = message["images"][0]
            assert message["content"] == "看图"
        else:
            assert message["content"][0] == {"type": "text", "text": "看图"}
            encoded = message["content"][1]["image_url"]["url"].split(",", 1)[1]
        assert base64.b64decode(encoded) == base64.b64decode(picture["data"])
        assert body["model"] == "vision-model"
        assert request.headers["authorization"] == "Bearer synthetic-token"
        return success(request)

    mock(service, handler)
    assert service.generate(snapshot, "看图", images=[picture])["text"] == "红色"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"mime_type": "image/jpeg", "data": "abc"}],
        [{"mime_type": "image/png", "data": "https://remote.example"}],
        [{"mime_type": "image/png", "data": base64.b64encode(b"fake png").decode()}],
    ],
)
def test_invalid_images_do_not_send(service, bad):
    snapshot = route(service, add(service), "vision")
    mock(service, lambda _: pytest.fail("invalid image must not reach HTTP"))
    with pytest.raises(ModelError) as exc:
        service.generate(snapshot, "看图", images=bad)
    assert exc.value.code == "invalid_images"


def test_oversize_png_dimensions_and_text_image_mismatch_rejected(service):
    profile = add(service)
    image = sample_image()
    raw = bytearray(base64.b64decode(image["data"]))
    raw[16:24] = struct.pack(">II", 8192, 8192)
    raw[29:33] = struct.pack(">I", zlib.crc32(raw[12:29]) & 0xFFFFFFFF)
    image["data"] = base64.b64encode(raw).decode()
    mock(service, lambda _: pytest.fail("invalid image must not reach HTTP"))
    with pytest.raises(ModelError) as exc:
        service.generate(route(service, profile, "vision"), "看图", images=[image])
    assert exc.value.code == "invalid_images"
    with pytest.raises(ModelError) as exc:
        service.generate(service.profile_snapshot(profile["id"]), "看图", images=[sample_image()])
    assert exc.value.code == "unsupported_capability"


def test_native_asr_same_region_audio_field_and_credential(service):
    profile = add(
        service,
        provider="qwen",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        api_key="synthetic-key",
        capabilities=["asr"],
        model_id="",
    )
    snapshot = route(service, profile, "asr")
    requests = []
    with sample_wav() as wav:
        expected = wav.read_bytes()

        def handler(request):
            requests.append(request)
            assert (
                str(request.url)
                == "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
            )
            body = json.loads(request.content)
            encoded = body["input"]["messages"][0]["content"][0]["audio"]
            assert encoded.startswith("data:audio/wav;base64,")
            assert base64.b64decode(encoded.split(",", 1)[1]) == expected
            assert body["parameters"] == {"asr_options": {"enable_itn": False}}
            assert request.headers["authorization"] == "Bearer synthetic-key"
            return httpx.Response(
                200,
                json={"output": {"choices": [{"message": {"content": [{"text": "合成转写"}]}}]}},
            )

        mock(service, handler)
        assert service.transcribe(snapshot, wav) == "合成转写"
    assert len(requests) == 1


def test_local_compatible_asr_multipart_no_key(service):
    snapshot = route(service, add(service), "asr")
    with sample_wav() as wav:
        audio = wav.read_bytes()

        def handler(request):
            assert request.url.path == "/v1/audio/transcriptions"
            assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
            assert "authorization" not in request.headers
            assert audio in request.content and b"asr-model" in request.content
            assert b'filename="audio.wav"' in request.content
            return httpx.Response(200, json={"text": "本地合成转写"})

        mock(service, handler)
        assert service.transcribe(snapshot, wav) == "本地合成转写"


@pytest.mark.parametrize(
    "status,code",
    [
        (302, "redirect_rejected"),
        (401, "authentication_failed"),
        (429, "rate_limited"),
        (503, "provider_unavailable"),
    ],
)
def test_asr_errors_redacted_not_retried(service, status, code):
    snapshot = route(service, add(service, api_key="synthetic-secret"), "asr")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"location": "https://other.example"},
            text="synthetic-secret private audio",
        )

    mock(service, handler)
    with sample_wav() as wav, pytest.raises(ModelError) as exc:
        service.transcribe(snapshot, wav)
    assert exc.value.code == code
    assert "synthetic-secret" not in str(exc.value) and "private audio" not in str(exc.value)
    assert len(requests) == 1


def test_asr_timeout_no_retry_and_wrong_wav_rejected(service, tmp_path):
    snapshot = route(service, add(service), "asr")
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("synthetic-private-error")

    mock(service, handler)
    with sample_wav() as wav, pytest.raises(ModelError) as exc:
        service.transcribe(snapshot, wav)
    assert exc.value.code == "timeout" and "synthetic-private-error" not in str(exc.value)
    assert len(requests) == 1
    wrong = tmp_path / "wrong.wav"
    with wave.open(str(wrong), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0" * 400)
    with pytest.raises(ModelError) as exc:
        service.transcribe(snapshot, wrong)
    assert exc.value.code == "invalid_audio" and len(requests) == 1


def test_native_audio_endpoint_not_inferred_for_untrusted_host(service):
    profile = add(
        service,
        audio_api_style="dashscope",
        base_url="https://other.example/v1",
        api_key="synthetic-key",
    )
    service.save_config({"capability_profiles": {"asr": profile["id"]}})
    with pytest.raises(ModelError) as exc:
        service.snapshot("asr")
    assert exc.value.code == "invalid_audio_endpoint"


def test_capability_tests_send_media_and_do_not_mark_text_passed(service):
    profile = add(service)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/audio/transcriptions"):
            assert b"RIFF" in request.content
            return httpx.Response(200, json={"text": ""})
        body = json.loads(request.content)
        assert body["messages"][0]["content"][1]["type"] == "image_url"
        return success(request)

    mock(service, handler)
    for capability in ("vision", "asr"):
        result = service.test_connection(profile["id"], capability=capability)
        assert result["success"] and result["capability"] == capability
    current = service.public_config()["profiles"][0]
    assert current["test_status"] == "untested"
    assert current["capability_test_status"]["vision"]["status"] == "passed"
    assert current["capability_test_status"]["asr"]["status"] == "passed"
    assert len(requests) == 2
    current = service.save_config({"profile": {"id": profile["id"], "name": "配置变化"}})[
        "profiles"
    ][0]
    assert all(
        value["status"] == "untested" for value in current["capability_test_status"].values()
    )


def test_capability_thinking_is_default_even_if_text_thinks(service):
    profile = add(
        service,
        provider="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_id="qwen-plus",
        thinking="enabled",
        api_key="synthetic-key",
    )
    assert service.profile_snapshot(profile["id"])["thinking"] == "enabled"
    assert route(service, profile, "vision")["thinking"] == "default"
    assert route(service, profile, "asr")["thinking"] == "default"


def test_native_silence_is_empty_but_other_400_is_not_success(service):
    profile = add(
        service,
        provider="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="synthetic-key",
    )
    snapshot = route(service, profile, "asr")
    mock(service, lambda request: httpx.Response(400, json={"code": "ASR_RESPONSE_HAVE_NO_WORDS"}))
    with sample_wav() as wav:
        assert service.transcribe(snapshot, wav) == ""
        mock(
            service,
            lambda request: httpx.Response(
                400, json={"code": "synthetic-secret", "message": "private"}
            ),
        )
        with pytest.raises(ModelError) as exc:
            service.transcribe(snapshot, wav)
        assert exc.value.code == "request_rejected"
        assert "private" not in str(exc.value) and "synthetic-secret" not in str(exc.value)


def test_truncated_and_long_audio_are_not_sent(service, tmp_path):
    snapshot = route(service, add(service), "asr")
    mock(service, lambda request: pytest.fail("invalid audio must not reach HTTP"))
    with sample_wav() as wav:
        truncated = tmp_path / "truncated.wav"
        truncated.write_bytes(wav.read_bytes()[:-4])
        with pytest.raises(ModelError) as exc:
            service.transcribe(snapshot, truncated)
        assert exc.value.code == "invalid_audio"
    long_audio = tmp_path / "long.wav"
    with wave.open(str(long_audio), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000 * 181)
    with pytest.raises(ModelError) as exc:
        service.transcribe(snapshot, long_audio)
    assert exc.value.code == "invalid_audio"


@pytest.mark.parametrize(
    "body,code",
    [
        (b"not json private", "invalid_response"),
        (b"x" * (2 * 1024 * 1024 + 1), "response_too_large"),
        (b'{"error":"synthetic-sensitive"}', "provider_error"),
    ],
)
def test_bad_asr_responses_are_bounded_and_redacted(service, body, code):
    snapshot = route(service, add(service), "asr")
    mock(service, lambda request: httpx.Response(200, content=body))
    with sample_wav() as wav, pytest.raises(ModelError) as exc:
        service.transcribe(snapshot, wav)
    assert exc.value.code == code
    assert "private" not in str(exc.value) and "synthetic-sensitive" not in str(exc.value)
