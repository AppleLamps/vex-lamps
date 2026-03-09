from __future__ import annotations

from pathlib import Path

import config
from state import ProjectState


def _format_srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def execute(params: dict, state: ProjectState) -> dict:
    try:
        import whisper  # type: ignore
    except ImportError:
        return {
            "success": False,
            "message": "Whisper is not installed. Install it with `pip install openai-whisper` to enable transcription.",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "transcribe_video",
        }

    model = whisper.load_model(config.WHISPER_MODEL)
    result = model.transcribe(state.working_file)
    txt_path = Path(state.working_dir) / "transcript.txt"
    srt_path = Path(state.working_dir) / "transcript.srt"
    txt_path.write_text(result["text"].strip() + "\n", encoding="utf-8")
    segments = result.get("segments", [])
    srt_lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        srt_lines.extend(
            [
                str(index),
                f"{_format_srt_timestamp(segment['start'])} --> {_format_srt_timestamp(segment['end'])}",
                segment["text"].strip(),
                "",
            ]
        )
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    preview = "\n".join(
        f"{_format_srt_timestamp(segment['start'])} {segment['text'].strip()}" for segment in segments[:10]
    )
    return {
        "success": True,
        "message": f"Transcript saved to {txt_path} and {srt_path}.\n{preview}",
        "suggestion": "[SUGGESTION]: Captions are ready. I can help turn them into timed overlays - reply 'yes' to apply or continue.",
        "updated_state": state,
        "tool_name": "transcribe_video",
    }
