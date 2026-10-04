"""Media tests use generated video/audio and temporary, synthetic notebooks only."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import math
import subprocess
import uuid
import wave
from copy import deepcopy
from pathlib import Path

import pytest

from local_app import media
from local_app.media import MediaPipeline, parse_subtitles
from local_app.models import ModelError


class Progress:
    def __init__(self):
        self.saved = {}
        self.events = []

    def __call__(self, value):
        self.events.append(value)

    def checkpoint(self, name, value=None):
        if value is not None:
            self.saved[name] = deepcopy(value)
        return deepcopy(self.saved.get(name))


def run_media(command):
    result = subprocess.run(command, capture_output=True, timeout=45, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-1000:]


@pytest.fixture(scope="module")
def ffmpeg():
    if not importlib.util.find_spec("imageio_ffmpeg"):
        pytest.skip("Optional video component is not installed")
    return media._ffmpeg()


@pytest.fixture(scope="module")
def clip(tmp_path_factory, ffmpeg):
    root = tmp_path_factory.mktemp("合成 视频")
    path = root / "流程演示.mp4"
    # All pixels and sound are synthetic; no camera, microphone or user media.
    run_media([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
               "testsrc2=size=320x240:rate=4:duration=3", "-f", "lavfi", "-i",
               "sine=frequency=440:sample_rate=16000:duration=3", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)])
    return path


def copy_clip(tmp_path, clip, *, subtitles=True):
    path = tmp_path / "源 视频.mp4"
    path.write_bytes(clip.read_bytes())
    if subtitles:
        path.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,500\n合成讲解：输入连接处理节点。\n\n"
            "2\n00:00:01,500 --> 00:00:03,000\n合成讲解：处理节点输出结果。\n",
            encoding="utf-8",
        )
    return path


def params(path, **values):
    return {"media_id": uuid.uuid4().hex, "source_ref": str(path), "source_type": "video_file",
            "video_mode": "illustrated", "frame_times": [0.5, 2.0], "asr_snapshot": None,
            **values}


def test_srt_and_vtt_keep_timing_and_multiline_text():
    parsed = parse_subtitles("1\n00:00:01,000 --> 00:00:02,100\n<b>节点甲</b>\n节点乙\n", 3)
    assert parsed == [{"start": 1.0, "end": 2.1, "text": "节点甲\n节点乙",
                       "source": "subtitle", "precision": "subtitle"}]
    parsed = parse_subtitles("WEBVTT\n\n00:01.000 --> 00:02.000 align:start\n甲 &amp; 乙\n", 3)
    assert parsed[0]["start"] == 1 and parsed[0]["text"] == "甲 & 乙"


@pytest.mark.parametrize("cue", ["00:70:00,000 --> 00:71:00,000", "00:00:02,000 --> 00:00:01,000",
                                "00:00:03,000 --> 00:00:05,000"])
def test_invalid_subtitle_times_fail(cue):
    with pytest.raises(ModelError, match="字幕时间"):
        parse_subtitles(cue + "\n合成字幕\n", 3)


def test_real_video_subtitles_and_manual_png_payload(tmp_path, clip):
    path = copy_clip(tmp_path, clip)
    pipeline = MediaPipeline(tmp_path / "private", lambda *_: pytest.fail("Subtitle must avoid ASR"))
    progress = Progress()
    result = pipeline.prepare(params(path), progress)
    assert result["duration"] == 3 and result["sampling"] == "manual"
    assert [f["time"] for f in result["frames"]] == [0.5, 2.0]
    assert len(result["timeline"]) == 2 and result["timeline"][1]["start"] == 1.5
    frame = result["frames"][0]
    decoded = base64.b64decode(pipeline.image_payload(frame)["data"], validate=True)
    assert decoded.startswith(b"\x89PNG")
    assert hashlib.sha256(decoded).hexdigest() == frame["sha256"]
    assert media._png(Path(frame["path"]))[1] == (320, 240)
    assert set(progress.saved) == {"media_source", "media_timeline", "media_frames"}


def test_completed_retry_uses_frozen_copy_and_no_extraction(tmp_path, clip, monkeypatch):
    path = copy_clip(tmp_path, clip)
    pipeline = MediaPipeline(tmp_path / "private", None)
    progress, request = Progress(), params(path)
    first = pipeline.prepare(request, progress)
    path.write_bytes(b"synthetic replacement after preparation")
    path.with_suffix(".srt").write_text("changed original subtitle", encoding="utf-8")
    monkeypatch.setattr(pipeline, "_frame", lambda *_: pytest.fail("Frames must reuse checkpoint"))
    second = pipeline.prepare(request, progress)
    assert second == first
    assert second["source_policy"] == "frozen_copy"


def test_changed_frozen_copy_is_rejected(tmp_path, clip):
    path = copy_clip(tmp_path, clip)
    pipeline = MediaPipeline(tmp_path / "private", None)
    progress, request = Progress(), params(path)
    first = pipeline.prepare(request, progress)
    Path(first["source_path"]).write_bytes(b"changed cached source")
    with pytest.raises(ModelError, match="固定视频副本已变化"):
        pipeline.prepare(request, progress)


def test_changed_image_and_outside_frame_are_rejected(tmp_path, clip):
    pipeline = MediaPipeline(tmp_path / "private", None)
    result = pipeline.prepare(params(copy_clip(tmp_path, clip)), Progress())
    frame = result["frames"][0]
    outside = tmp_path / "outside.png"
    outside.write_bytes(Path(frame["path"]).read_bytes())
    with pytest.raises(ModelError, match="不属于"):
        pipeline.image_payload({**frame, "path": str(outside)})
    Path(frame["path"]).write_bytes(Path(frame["path"]).read_bytes()[:-1] + b"!")
    with pytest.raises(ModelError):
        pipeline.validate_bundle(result)


@pytest.mark.parametrize("times", [[True], [-1], [3], [math.nan], [math.inf], [0] * 9, [1, 1], "1,2"])
def test_invalid_frame_selection_precedes_asr(tmp_path, clip, times):
    path = copy_clip(tmp_path, clip, subtitles=False)
    pipeline = MediaPipeline(tmp_path / "private", lambda *_: pytest.fail("Must validate before ASR"))
    with pytest.raises(ModelError):
        pipeline.prepare(params(path, frame_times=times, asr_snapshot={"synthetic": True}), Progress())


def test_no_subtitles_requires_explicit_asr_configuration(tmp_path, clip):
    path = copy_clip(tmp_path, clip, subtitles=False)
    pipeline = MediaPipeline(tmp_path / "private", None)
    with pytest.raises(ModelError) as caught:
        pipeline.prepare(params(path), Progress())
    assert caught.value.code == "missing_asr_route"
    assert "重新提交任务" in str(caught.value)


def test_real_wav_extraction_and_chunk_timing(tmp_path, clip):
    path = copy_clip(tmp_path, clip, subtitles=False)
    received = []

    def asr(snapshot, wav):
        with wave.open(str(wav)) as audio:
            assert audio.getnchannels() == 1 and audio.getframerate() == 16000
            assert 2.8 <= audio.getnframes() / audio.getframerate() <= 3.1
        received.append(snapshot)
        return "合成识别结果，非真实模型语义证据。"

    pipeline = MediaPipeline(tmp_path / "private", asr)
    result = pipeline.prepare(params(path, video_mode="text", frame_times=[],
                                     asr_snapshot={"model_id": "synthetic-asr"}), Progress())
    assert received == [{"model_id": "synthetic-asr"}]
    assert result["frames"] == []
    assert result["timeline"] == [{"start": 0, "end": 3, "text": "合成识别结果，非真实模型语义证据。",
                                   "source": "asr", "precision": "chunk"}]


def test_failed_asr_reuses_successful_chunks(tmp_path, ffmpeg, monkeypatch):
    path = tmp_path / "分块合成.mp4"
    run_media([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
               "color=blue:size=32x32:rate=1:duration=5", "-f", "lavfi", "-i",
               "sine=frequency=400:sample_rate=16000:duration=5", "-c:v", "libx264",
               "-c:a", "aac", "-shortest", str(path)])
    monkeypatch.setattr(media, "ASR_CHUNK_SECONDS", 2)
    called = []

    def asr(_, wav):
        called.append(wav.name)
        if len(called) == 2:
            raise ModelError("synthetic_failure", "合成第二块失败")
        return "合成结果"

    pipeline, progress = MediaPipeline(tmp_path / "private", asr), Progress()
    request = params(path, video_mode="text", frame_times=[], asr_snapshot={"model_id": "synthetic"})
    with pytest.raises(ModelError, match="合成第二块失败"):
        pipeline.prepare(request, progress)
    result = pipeline.prepare(request, progress)
    assert called == ["audio-0000.wav", "audio-0001.wav", "audio-0001.wav", "audio-0002.wav"]
    assert [(item["start"], item["end"]) for item in result["timeline"]] == [(0, 2), (2, 4), (4, 5)]
    with pytest.raises(ModelError, match="配置与原任务不一致"):
        pipeline.prepare({**request, "asr_snapshot": {"model_id": "different-synthetic"}}, progress)


def test_embedded_subtitle_is_preserved_without_sidecar(tmp_path, clip, ffmpeg):
    source = copy_clip(tmp_path, clip)
    embedded = tmp_path / "带字幕.mp4"
    run_media([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(source), "-i",
               str(source.with_suffix(".srt")), "-c:v", "copy", "-c:a", "copy",
               "-c:s", "mov_text", str(embedded)])
    pipeline = MediaPipeline(tmp_path / "private", lambda *_: pytest.fail("Embedded subtitles avoid ASR"))
    result = pipeline.prepare(params(embedded, video_mode="text", frame_times=[]), Progress())
    assert all(cue["source"] == "embedded_subtitle" for cue in result["timeline"])


def test_auto_samples_deduplicate_static_video(tmp_path, ffmpeg):
    path = tmp_path / "静态.mp4"
    run_media([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
               "color=blue:size=320x240:rate=1:duration=41", "-c:v", "libx264", str(path)])
    path.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:00:41,000\n合成静态说明\n", encoding="utf-8")
    pipeline = MediaPipeline(tmp_path / "private", None)
    result = pipeline.prepare(params(path, frame_times=[]), Progress())
    assert result["sampling"] == "uniform_nearby" and len(result["frames"]) == 1


def test_source_symlink_and_task_directory_symlink_rejected(tmp_path, clip):
    path = tmp_path / "linked.mp4"
    try:
        path.symlink_to(clip)
    except OSError:
        pytest.skip("Platform does not allow test symlinks")
    pipeline = MediaPipeline(tmp_path / "private", None)
    with pytest.raises(ModelError, match="符号链接"):
        pipeline.prepare(params(path), Progress())
    pipeline.root.mkdir(exist_ok=True)
    request = params(clip)
    (pipeline.root / request["media_id"]).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ModelError, match="符号链接"):
        pipeline.prepare(request, Progress())


@pytest.mark.parametrize("source", ["file:///etc/passwd", "http://127.0.0.1/video", "https://youtube.com.evil.invalid/x",
                                   "https://user:secret@youtube.com/x"])
def test_unsupported_urls_rejected_before_download(tmp_path, source, monkeypatch):
    pipeline = MediaPipeline(tmp_path / "private", None)
    monkeypatch.setattr(pipeline, "_download", lambda *_: pytest.fail("Unsafe URL must not download"))
    with pytest.raises(ModelError):
        pipeline.prepare(params(source, source_type="video_url"), Progress())


def test_source_limit_is_enforced(tmp_path, clip, monkeypatch):
    monkeypatch.setattr(media, "MAX_VIDEO_BYTES", 1)
    with pytest.raises(ModelError, match="大小限制"):
        MediaPipeline(tmp_path / "private", None).prepare(params(clip), Progress())


def test_source_format_cannot_follow_external_playlist(tmp_path, ffmpeg):
    source = tmp_path / "pretend-video.mp4"
    source.write_text("ffconcat version 1.0\nfile '/not-an-authorized-media-file'\n", encoding="utf-8")
    with pytest.raises(ModelError, match="可读取的视频画面"):
        MediaPipeline(tmp_path / "private", None).prepare(params(source), Progress())


def test_frame_is_downscaled_within_pixel_limit(tmp_path, ffmpeg):
    source = tmp_path / "large-frame.mp4"
    run_media([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
               "color=blue:size=3200x1800:rate=1:duration=1", "-c:v", "libx264", str(source)])
    source.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n合成大图\n", encoding="utf-8")
    result = MediaPipeline(tmp_path / "private", None).prepare(params(source, frame_times=[0]), Progress())
    assert media._png(Path(result["frames"][0]["path"]))[1] == (1600, 900)


def test_high_bit_depth_video_produces_valid_8_bit_model_image(tmp_path, ffmpeg):
    from local_app.models.multimodal import validate_images

    source = tmp_path / "合成十位视频.mkv"
    run_media([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
               "testsrc2=size=320x240:rate=1:duration=1", "-c:v", "ffv1",
               "-pix_fmt", "yuv420p10le", str(source)])
    inspected = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-i", str(source)],
                               capture_output=True, timeout=20, check=False)
    assert b"yuv420p10le" in inspected.stderr  # Confirm the fixture really is 10-bit.
    source.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n合成高位深视频字幕\n", encoding="utf-8")
    pipeline = MediaPipeline(tmp_path / "private", None)
    bundle = pipeline.prepare(params(source, frame_times=[0]), Progress())
    images = [pipeline.image_payload(bundle["frames"][0])]
    assert base64.b64decode(images[0]["data"])[24] == 8
    assert validate_images(images) == images


def sparse_clip(tmp_path, ffmpeg, rate="1"):
    source = tmp_path / "低帧率视频.mp4"
    run_media([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
               f"testsrc2=size=320x240:rate={rate}:duration=2", "-c:v", "libx264", str(source)])
    source.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n合成低帧率讲解\n", encoding="utf-8")
    return source


def test_sparse_video_auto_skips_empty_tail_candidate(tmp_path, ffmpeg):
    from local_app.models.multimodal import validate_images

    source = sparse_clip(tmp_path, ffmpeg)
    pipeline = MediaPipeline(tmp_path / "private", None)
    result = pipeline.prepare(params(source, frame_times=[]), Progress())
    assert result["sampling"] == "uniform_nearby" and result["frames"]
    assert all(frame["time"] <= 1 for frame in result["frames"])
    assert validate_images([pipeline.image_payload(frame) for frame in result["frames"]])


def test_sparse_video_auto_falls_back_to_recorded_earlier_time(tmp_path, ffmpeg):
    from local_app.models.multimodal import validate_images

    # One frame at t=0, displayed for two seconds: every central seek is empty.
    source = sparse_clip(tmp_path, ffmpeg, rate="1/2")
    pipeline = MediaPipeline(tmp_path / "private", None)
    result = pipeline.prepare(params(source, frame_times=[]), Progress())
    assert [frame["time"] for frame in result["frames"]] == [0]
    assert validate_images([pipeline.image_payload(result["frames"][0])])


def test_sparse_video_manual_tail_fails_without_time_shift(tmp_path, ffmpeg):
    source = sparse_clip(tmp_path, ffmpeg)
    pipeline = MediaPipeline(tmp_path / "private", None)
    progress = Progress()
    with pytest.raises(ModelError) as failure:
        pipeline.prepare(params(source, frame_times=[1.9]), progress)
    assert failure.value.code == "media_frame_unavailable"
    assert "所选时间" in str(failure.value)
    assert "media_frames" not in progress.saved


def test_empty_frame_cannot_reuse_an_existing_candidate_png(tmp_path, ffmpeg):
    source = sparse_clip(tmp_path, ffmpeg)
    pipeline = MediaPipeline(tmp_path / "private", None)
    candidate = tmp_path / "candidate.png"
    pipeline._frame(source, 0, candidate)
    assert candidate.is_file()
    with pytest.raises(ModelError) as failure:
        pipeline._frame(source, 1.9, candidate)
    assert failure.value.code == "media_frame_unavailable" and not candidate.exists()


def test_auto_candidates_do_not_hide_real_frame_errors(tmp_path, clip, monkeypatch):
    source = copy_clip(tmp_path, clip)
    pipeline = MediaPipeline(tmp_path / "private", None)

    def fail_frame(*_):
        raise ModelError("media_command_failed", "合成组件失败")

    monkeypatch.setattr(pipeline, "_frame", fail_frame)
    with pytest.raises(ModelError, match="合成组件失败"):
        pipeline.prepare(params(source, frame_times=[]), Progress())
