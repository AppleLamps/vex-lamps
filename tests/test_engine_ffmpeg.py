from __future__ import annotations

import shutil
import subprocess

import pytest

pytest.importorskip("moviepy.editor")

import config
import engine


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
