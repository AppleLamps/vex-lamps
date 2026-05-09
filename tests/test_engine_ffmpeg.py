from __future__ import annotations

import shutil
import subprocess

import pytest

pytest.importorskip("moviepy")

import config
import engine
from state import ProjectState, utc_now_iso
from tools import transcript


def test_run_command_timeout_becomes_video_engine_error(monkeypatch) -> None:
    monkeypatch.setattr(config, "FFMPEG_COMMAND_TIMEOUT_SEC", 1)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    with pytest.raises(engine.VideoEngineError, match="timed out after 1s"):
        engine._run_command(["ffmpeg", "-version"], "Failed to run FFmpeg")


def test_probe_video_nonzero_exit_becomes_video_engine_error(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["ffprobe"], returncode=1, stdout="", stderr="bad probe")

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    with pytest.raises(engine.VideoEngineError, match="bad probe"):
        engine.probe_video("missing.mp4")


def test_trim_and_export_tiny_synthetic_clip(tmp_path, monkeypatch) -> None:
    ffmpeg_path = shutil.which(config.FFMPEG_PATH)
    if ffmpeg_path is None:
        pytest.skip("FFmpeg is not installed")
    monkeypatch.setattr(config, "FFMPEG_PATH", ffmpeg_path)
    monkeypatch.setattr(config, "FFMPEG_COMMAND_TIMEOUT_SEC", 30)
    monkeypatch.setattr(config, "FFMPEG_EXPORT_TIMEOUT_SEC", 30)
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "export.mp4"
    subprocess.run(
        [
            ffmpeg_path,
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(input_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    trimmed = engine.trim(str(input_path), str(tmp_path), 0, 0.5)
    saved = engine.export(
        trimmed,
        str(output_path),
        {
            "format": "mp4",
            "resolution": "64x64",
            "fps": 10,
            "video_codec": "libx264",
            "audio_codec": "aac",
        },
    )

    assert saved == str(output_path)
    assert output_path.is_file()
    assert engine.probe_video(str(output_path))["duration_sec"] > 0


def test_add_text_overlay_works_with_installed_moviepy(tmp_path, monkeypatch) -> None:
    ffmpeg_path = shutil.which(config.FFMPEG_PATH)
    if ffmpeg_path is None:
        pytest.skip("FFmpeg is not installed")
    monkeypatch.setattr(config, "FFMPEG_PATH", ffmpeg_path)
    monkeypatch.setattr(config, "FFMPEG_COMMAND_TIMEOUT_SEC", 30)
    input_path = tmp_path / "input.mp4"
    subprocess.run(
        [
            ffmpeg_path,
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x54:rate=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(input_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output_path = engine.add_text(
        str(input_path),
        str(tmp_path),
        text="HELLO",
        position="center",
        font_size=18,
        color="white",
        start_sec=0,
        end_sec=1,
        bg_opacity=0.4,
    )

    assert engine.probe_video(output_path)["duration_sec"] > 0


def test_remove_segment_keeps_remaining_clip_parts(tmp_path, monkeypatch) -> None:
    ffmpeg_path = shutil.which(config.FFMPEG_PATH)
    if ffmpeg_path is None:
        pytest.skip("FFmpeg is not installed")
    monkeypatch.setattr(config, "FFMPEG_PATH", ffmpeg_path)
    monkeypatch.setattr(config, "FFMPEG_COMMAND_TIMEOUT_SEC", 30)
    input_path = tmp_path / "input.mp4"
    subprocess.run(
        [
            ffmpeg_path,
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(input_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output_path = engine.remove_segment(str(input_path), str(tmp_path), 0.5, 1.5)
    metadata = engine.probe_video(output_path)

    assert 0.7 <= metadata["duration_sec"] <= 1.4


def test_transcribe_video_prefers_gemini_without_whisper(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"fake-video")
    now = utc_now_iso()
    state = ProjectState(
        project_id="transcript-test",
        project_name="transcript-test",
        created_at=now,
        updated_at=now,
        source_files=[str(video_path)],
        working_file=str(video_path),
        working_dir=str(tmp_path),
        output_dir=str(tmp_path / "outputs"),
        metadata={"duration_sec": 30.0, "width": 640, "height": 360, "fps": 24.0},
        provider="gemini",
        model="gemini-3.1-flash-lite",
    )

    class FakeModels:
        def generate_content(self, **_kwargs):
            return type(
                "Response",
                (),
                {
                    "text": (
                        '{"transcript":"Hello from Gemini.",'
                        '"segments":[{"start":0.0,"end":1.2,"text":"Hello from Gemini."}]}'
                    )
                },
            )()

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setattr(config, "GEMINI_TRANSCRIPT_MAX_INLINE_MB", 100)
    monkeypatch.setattr(config, "GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC", 90)
    monkeypatch.setattr(transcript.genai, "Client", FakeClient)

    result = transcript.execute({}, state)

    assert result["success"]
    assert "Gemini video" in result["message"]
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8").strip() == "Hello from Gemini."
    assert state.artifacts["latest_transcript"]["source"] == "Gemini video (gemini-3.1-flash-lite)"
