from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from engine import VideoEngineError, burn_subtitles, probe_video
from state import ProjectState


def execute(params: dict, state: ProjectState) -> dict:
    srt_path = Path(params["srt_path"]).expanduser().resolve() if params.get("srt_path") else Path(state.working_dir) / "transcript.srt"
    if not srt_path.is_file():
        return {
            "success": False,
            "message": "No SRT file found. Run transcribe_video first.",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "burn_subtitles",
        }

    font_size = int(params.get("font_size", 24))
    font_color = str(params.get("font_color", "white"))
    outline_color = str(params.get("outline_color", "black"))
    position = str(params.get("position", "bottom"))
    if position not in {"bottom", "center", "top"}:
        return {
            "success": False,
            "message": f"Unsupported subtitle position: {position}",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "burn_subtitles",
        }

    try:
        output_path = burn_subtitles(
            state.working_file,
            state.working_dir,
            srt_path=str(srt_path),
            font_size=font_size,
            font_color=font_color,
            outline_color=outline_color,
            position=position,
        )
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        description = f"Burned subtitles from {srt_path.name} at {position}"
        op = {
            "op": "burn_subtitles",
            "params": {
                "srt_path": str(srt_path),
                "font_size": font_size,
                "font_color": font_color,
                "outline_color": outline_color,
                "position": position,
            },
            "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "result_file": output_path,
            "description": description,
        }
        state.apply_operation(op)
        return {
            "success": True,
            "message": description + ".",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "burn_subtitles",
        }
    except (ValueError, VideoEngineError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "burn_subtitles",
        }
