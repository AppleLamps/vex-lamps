from __future__ import annotations

from datetime import datetime, timezone

from engine import VideoEngineError, probe_video, trim_silence
from state import ProjectState


def execute(params: dict, state: ProjectState) -> dict:
    min_silence_duration = float(params.get("min_silence_duration", 0.5))
    silence_threshold_db = float(params.get("silence_threshold_db", -35.0))
    try:
        output_path = trim_silence(
            state.working_file,
            state.working_dir,
            min_silence_duration=min_silence_duration,
            silence_threshold_db=silence_threshold_db,
        )
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        description = (
            f"Trimmed silent gaps longer than {min_silence_duration:.2f}s below {silence_threshold_db:.1f} dB"
        )
        op = {
            "op": "trim_silence",
            "params": {
                "min_silence_duration": min_silence_duration,
                "silence_threshold_db": silence_threshold_db,
            },
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "result_file": output_path,
            "description": description,
        }
        state.apply_operation(op)
        return {
            "success": True,
            "message": description + ".",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "trim_silence",
        }
    except (ValueError, VideoEngineError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "trim_silence",
        }
