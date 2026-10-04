"""Explicit secret imports use synthetic values and an in-memory credential store."""

import json

import httpx
import pytest

from local_app.models import MemoryCredentialStore, ModelError, ModelService
from local_app.secret_setup import SecretSetup


@pytest.fixture
def setup(tmp_path):
    models = ModelService(tmp_path, MemoryCredentialStore())
    setup = SecretSetup(tmp_path, models)
    profile = models.save_config({"profile": {"provider": "qwen", "name": "合成连接"}})["profiles"][
        0
    ]
    yield setup, models, profile["id"]
    models.close()


def test_blank_template_preserves_manual_file_and_only_explicit_import(setup):
    secret, models, identity = setup
    assert "API_KEY=\n" in secret.template.read_text()
    secret.input.write_text("# synthetic only\nAPI_KEY=synthetic-import-key\n")
    SecretSetup(secret.data, models)
    assert not models.public_config()["profiles"][0]["credential_present"]
    result = secret.import_secret(identity, "template")
    assert result == {"imported": True, "source_cleared": True}
    assert models.verify_saved_key(identity, "synthetic-import-key")
    assert "synthetic-import-key" not in secret.input.read_text()
    assert "synthetic-import-key" not in models.path.read_text()
    assert "synthetic-import-key" not in json.dumps(secret.status())


@pytest.mark.parametrize("prefix,host", [
    ("sk-ws-", "maas.qianwenaiapi.com"),
    ("sk-sp-", "token-plan.maas.qianwenaiapi.com"),
])
def test_qwen_template_key_reaches_only_selected_endpoint(setup, prefix, host):
    secret, models, identity = setup
    key = prefix + "synthetic-template-no-real-access"
    endpoint = "https://" + host + "/compatible-mode/v1"
    models.save_config({"profile": {"id": identity, "base_url": endpoint}})
    secret.input.write_text("API_KEY=" + key + "\n")
    assert secret.import_secret(identity, "template")["source_cleared"]
    seen = []

    def handler(request):
        seen.append(str(request.url))
        assert str(request.url) == endpoint + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + key
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"content":"合成测试"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        ))

    models.client.close()
    models.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert models.test_connection(identity)["success"]
    assert len(seen) == 1
    assert secret.input.read_text() == "API_KEY=\n"
    assert key not in models.path.read_text() + json.dumps(models.public_config())


def test_legacy_migration_retains_unrelated_fields_and_failed_store(setup, monkeypatch):
    secret, models, identity = setup
    legacy = secret.data / "credentials.json"
    legacy.write_text(json.dumps({"dashscope_api_key": "synthetic-old-key", "keep": "field"}))
    before = legacy.read_bytes()
    real_set = models.credentials.set

    def fail(*args):
        raise OSError("synthetic-private-error")

    monkeypatch.setattr(models.credentials, "set", fail)
    with pytest.raises(ModelError) as exc:
        secret.import_secret(identity, "legacy")
    assert "synthetic" not in str(exc.value)
    assert legacy.read_bytes() == before
    monkeypatch.setattr(models.credentials, "set", real_set)
    assert secret.import_secret(identity, "legacy")["source_cleared"]
    assert json.loads(legacy.read_text()) == {"keep": "field"}
    assert models.verify_saved_key(identity, "synthetic-old-key")


def test_readback_failure_preserves_source(setup, monkeypatch):
    secret, models, identity = setup
    secret.input.write_text("API_KEY=synthetic-check-key\n")
    monkeypatch.setattr(models, "verify_saved_key", lambda *args: False)
    with pytest.raises(ModelError, match="回读校验失败"):
        secret.import_secret(identity, "template")
    assert "synthetic-check-key" in secret.input.read_text()


@pytest.mark.parametrize(
    "content",
    ["API_KEY=$(echo nope)", "OTHER=synthetic", "API_KEY=a\nDASHSCOPE_API_KEY=b", "API_KEY="],
)
def test_template_never_executes_or_imports_ambiguous_fields(setup, content):
    secret, models, identity = setup
    secret.input.write_text(content)
    with pytest.raises(ModelError):
        secret.import_secret(identity, "template")
    assert secret.input.read_text() == content
    assert not models.public_config()["profiles"][0]["credential_present"]


def test_symlink_secret_source_rejected(setup, tmp_path):
    secret, _, identity = setup
    target = tmp_path / "not-selected.env"
    target.write_text("API_KEY=synthetic-unselected")
    secret.input.symlink_to(target)
    with pytest.raises(ModelError, match="符号链接"):
        secret.import_secret(identity, "template")
    assert target.read_text() == "API_KEY=synthetic-unselected"


def test_legacy_api_writes_only_secure_store(setup):
    secret, models, _ = setup
    secret.save_legacy_key("synthetic-compat-key")
    assert not (secret.data / "credentials.json").exists()
    snapshot = models.snapshot("asr")
    assert snapshot["model_id"] == "qwen3-asr-flash"
    assert "synthetic-compat-key" not in json.dumps(snapshot)
