"""Real media, worker, HTTP/MCP and attachment flow; model answers are synthetic."""

import base64
import json
import re
import subprocess
from pathlib import Path

import httpx
import pytest
from markdown_it import MarkdownIt

from local_app.jobs import JobManager
from local_app.media import _ffmpeg
from local_app.media_assets import render_frames
from local_app.models import ModelError
from local_app.video_prompts import context_window, parse_visual_evidence, validate_video_options
from tests_local.test_generation import finished
from tests_local.test_http import service as http_service


@pytest.fixture
def service(tmp_path):
    yield from http_service.__wrapped__(tmp_path)


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "lesson.mp4"
    result = subprocess.run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=2:duration=4",
            "-c:v",
            "libx264",
            str(path),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0
    path.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n先理解中心主题和分支。\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\n然后核对箭头方向，不要猜测遮挡文字。\n",
        encoding="utf-8",
    )
    return path


EVIDENCE = {
    "visible_facts": ["合成响应：图中有节点"],
    "nodes": ["A", "B"],
    "relations": [{"from": "A", "to": "B", "kind": "arrow", "label": ""}],
    "narration_context": ["合成响应：先讲中心主题，再讲箭头"],
    "explanation": "合成模型响应，仅用于验证数据传递。",
    "uncertain": ["合成响应：文字有遮挡"],
}


def configure(runtime, monkeypatch, independent=True):
    config = runtime.models.save_config(
        {
            "profile": {
                "name": "合成多模态连接",
                "provider": "custom",
                "base_url": "http://127.0.0.1:18999/v1",
                "model_id": "synthetic-text",
                "capabilities": ["text", "vision"],
                "capability_models": {"vision": "synthetic-vision", "asr": ""},
            }
        }
    )
    identity = config["profiles"][0]["id"]
    runtime.models.save_config(
        {
            "generation_mode": "independent" if independent else "host",
            "default_profile": identity,
            "capability_profiles": {"vision": identity},
        }
    )
    monkeypatch.setattr(
        runtime.features, "status", lambda: {"video": {"ready": True}, "semantic": {}}
    )
    calls = []

    def endpoint(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["model"] == "synthetic-vision":
            content = body["messages"][0]["content"]
            image = next(
                part["image_url"]["url"] for part in content if part["type"] == "image_url"
            )
            assert base64.b64decode(image.split(",", 1)[1]).startswith(b"\x89PNG")
            prompt = next(part["text"] for part in content if part["type"] == "text")
            assert "中心主题" in prompt and "箭头方向" in prompt and "uncertain" in prompt
            text = json.dumps(EVIDENCE, ensure_ascii=False)
        else:
            prompt = body["messages"][0]["content"]
            assert "合成模型响应" in prompt and "字幕时间" in prompt
            ids = list(dict.fromkeys(re.findall(r"\[\[FRAME:(f\d{3})\]\]", prompt)))
            text = (
                "# 合成图文笔记\n\n[00:00:01] 图中可见节点；讲者补充方向。文字有遮挡，待核对。\n\n"
                + "\n\n".join(f"[[FRAME:{v}]]" for v in ids)
            )
        return httpx.Response(
            200,
            text="data: "
            + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]})
            + "\n\ndata: [DONE]\n\n",
        )

    runtime.models.client.close()
    runtime.models.client = httpx.Client(transport=httpx.MockTransport(endpoint), trust_env=False)
    return calls


def submit(runtime, video, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return runtime.submit_task(
        "ingest",
        {
            "user_input": str(video),
            "vault_path": str(vault),
            "folder": "Inbox",
            "video_mode": "illustrated",
            "frame_times": [1.0, 3.0],
        },
    ), vault


def test_real_media_to_illustrated_staged_note_with_retry(service, video, tmp_path, monkeypatch):
    calls = configure(service, monkeypatch)
    finalize = service.kb.finalize
    failed = [False]

    def fail_after_publish(*args, **kwargs):
        saved = finalize(*args, **kwargs)
        if not failed[0]:
            failed[0] = True
            raise OSError("synthetic persistence interruption after note publication")
        return saved

    monkeypatch.setattr(service.kb, "finalize", fail_after_publish)
    job, vault = submit(service, video, tmp_path)
    first = finished(service, job["job_id"])
    assert first["status"] == "failed"
    assert len(calls) == 3
    before = {str(p): p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    # Restart the durable worker from disk before retrying the same task.
    service.jobs.close()
    service.jobs = JobManager(service.data)
    service.jobs.register("ingest", service.generation.ingest)
    service.jobs.start()
    service.jobs.retry(job["job_id"])
    done = finished(service, job["job_id"])
    assert done["status"] == "succeeded"
    assert len(calls) == 3  # No repeat billed calls after successful generation.
    assert before == {str(p): p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    note = Path(done["result"]["absolute_path"]).read_text()
    assert "status: staged" in note and "[[FRAME:" not in note
    assert len(re.findall(r"!\[\[Assets/PersonalKB/", note)) == 2
    for frame in done["result"]["media"]["frames"]:
        assert (vault / frame["relative_path"]).read_bytes().startswith(b"\x89PNG")
    assert done["result"]["media"]["timeline_precision"] == ["subtitle"]
    assert "data:image" not in json.dumps(done)


def test_host_finalize_rejects_unknown_frames_and_preserves_user_attachment(
    service, video, tmp_path, monkeypatch
):
    calls = configure(service, monkeypatch, independent=False)
    job, vault = submit(service, video, tmp_path)
    prepared = finished(service, job["job_id"])["result"]
    assert len(calls) == 2 and "合成模型响应" in prepared["prompt_for_host"]
    with pytest.raises(ModelError, match="未知"):
        service.kb.finalize(prepared["prepare_id"], "# 图文\n[[FRAME:unknown]]")
    assert not list(vault.rglob("*.png"))
    body = "# 合成宿主图文\n\n[[FRAME:f001]]\n\n[[FRAME:f002]]"
    result = service.kb.finalize(prepared["prepare_id"], body)
    attachment = vault / result["media"]["frames"][0]["relative_path"]
    attachment.write_bytes(b"user-modified-image")
    with pytest.raises(ModelError):
        service.kb.finalize(prepared["prepare_id"], body)
    assert attachment.read_bytes() == b"user-modified-image"


def test_visual_frame_failure_reuses_only_completed_evidence(service, video, tmp_path, monkeypatch):
    calls = configure(service, monkeypatch)
    generate = service.models.generate
    failure = [True]

    def fail_second(snapshot, prompt, *args, **kwargs):
        if snapshot["model_id"] == "synthetic-vision" and "截图编号：f002" in prompt and failure[0]:
            failure[0] = False
            raise ModelError("provider_unavailable", "合成单帧故障")
        return generate(snapshot, prompt, *args, **kwargs)

    monkeypatch.setattr(service.models, "generate", fail_second)
    job, vault = submit(service, video, tmp_path)
    assert finished(service, job["job_id"])["status"] == "failed"
    assert len(calls) == 1 and not list(vault.rglob("*.md"))
    service.jobs.retry(job["job_id"])
    assert finished(service, job["job_id"])["status"] == "succeeded"
    assert len(calls) == 3


def test_missing_vision_does_not_pretend_to_understand_images(
    service, video, tmp_path, monkeypatch
):
    monkeypatch.setattr(service.features, "status", lambda: {"video": {"ready": True}})
    with pytest.raises(ModelError) as exc:
        submit(service, video, tmp_path)
    assert exc.value.code == "missing_route"
    assert not service.jobs.list()


def test_prompt_bounds_and_visual_schema():
    segments = [{"start": 1, "end": 31}, {"start": 55, "end": 60}, {"start": 100, "end": 101}]
    assert context_window(segments, 30) == segments[:2]
    assert parse_visual_evidence(json.dumps(EVIDENCE)) == EVIDENCE
    malformed = {
        **EVIDENCE,
        "relations": [{"from": "invented", "to": "B", "kind": "arrow", "label": ""}],
    }
    with pytest.raises(ModelError):
        parse_visual_evidence(json.dumps(malformed))
    for times in ([float("nan")], [True], [-1], [float("inf")], list(range(9))):
        with pytest.raises(ValueError):
            validate_video_options("illustrated", times)


@pytest.mark.parametrize(
    "body",
    [
        "```markdown\n[[FRAME:f001]]\n```",
        "```markdown\n```text\n[[FRAME:f001]]\n```",
        "~~~~\n~~~\n[[FRAME:f001]]\n~~~~",
        "```\n~~~\n[[FRAME:f001]]\n```",
        "<!--\n[[FRAME:f001]]\n-->",
        "<pre>\n[[FRAME:f001]]\n</pre>",
        "<div>\n[[FRAME:f001]]\n</div>",
        "<script>\n[[FRAME:f001]]\n</script>",
        "![outside](file:///outside.png)\n[[FRAME:f001]]",
    ],
)
def test_frame_references_must_render_as_images(body):
    with pytest.raises(ModelError):
        render_frames(body, [{"id": "f001", "time": 0, "relative_path": "Assets/demo/f001.png"}])


@pytest.mark.parametrize(
    "body",
    [
        "# 正常正文\n\n[[FRAME:f001]]",
        "```python\nprint('示例')\n```\n[[FRAME:f001]]",
        "~~~text\n示例\n~~~~\n[[FRAME:f001]]",
        "`前文\n[[FRAME:f001]]\n后文`",
        "``前文\n[[FRAME:f001]]\n后文``",
    ],
)
def test_valid_frame_reference_is_outside_code_and_html(body):
    rendered = render_frames(
        body, [{"id": "f001", "time": 0, "relative_path": "Assets/demo/f001.png"}]
    )
    tokens = MarkdownIt("commonmark").parse(rendered)
    # Obsidian resolves the wiki embed from normal inline text; code/HTML cannot display it.
    matching = [token for token in tokens if "![[Assets/demo/f001.png]]" in token.content]
    assert len(matching) == 1 and matching[0].type == "inline"
    assert any(
        child.type == "text" and "![[Assets/demo/f001.png]]" in child.content
        for child in matching[0].children
    )


@pytest.mark.parametrize(
    "invalid_body",
    [
        "# 合成漏图正文",
        "```markdown\n```text\n[[FRAME:f001]]\n[[FRAME:f002]]\n```",
        "<pre>\n[[FRAME:f001]]\n[[FRAME:f002]]\n</pre>",
    ],
)
def test_invalid_generated_placeholders_can_be_regenerated(
    service, video, tmp_path, monkeypatch, invalid_body
):
    calls = configure(service, monkeypatch)
    generate = service.models.generate
    bad = [True]

    def wrong_reference(snapshot, prompt, *args, **kwargs):
        result = generate(snapshot, prompt, *args, **kwargs)
        if snapshot["model_id"] == "synthetic-text" and bad[0]:
            bad[0] = False
            result["text"] = invalid_body
        return result

    monkeypatch.setattr(service.models, "generate", wrong_reference)
    job, vault = submit(service, video, tmp_path)
    failed = finished(service, job["job_id"])
    assert failed["status"] == "failed" and failed["error"]["code"] == "invalid_frame_reference"
    assert service.jobs.checkpoint(job["job_id"], "generated") is None
    assert not list(vault.rglob("*.md"))
    assert not list(vault.rglob("*.png"))
    service.jobs.retry(job["job_id"])
    assert finished(service, job["job_id"])["status"] == "succeeded"
    assert len(calls) == 4  # Reuse both vision calls, regenerate only the invalid body.


def test_attachment_directory_symlink_cannot_write_outside_vault(
    service, video, tmp_path, monkeypatch
):
    configure(service, monkeypatch, independent=False)
    job, vault = submit(service, video, tmp_path)
    prepared = finished(service, job["job_id"])["result"]
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "Assets").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        service.kb.finalize(prepared["prepare_id"], "# 图文\n\n[[FRAME:f001]]\n\n[[FRAME:f002]]")
    assert not list(outside.iterdir())
