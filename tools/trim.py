from __future__ import annotations

from datetime import datetime, timezone

from engine import VideoEngineError, parse_timestamp, probe_video, trim
from state import ProjectState


def execute(params: dict, state: ProjectState) -> dict:
    try:
        start_sec = parse_timestamp(params["start"])
        end_sec = parse_timestamp(params["end"]) if params.get("end") else None
        output_path = trim(state.working_file, state.working_dir, start_sec, end_sec)
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        description = (
            f"Trimmed from {params['start']} to {params.get('end', 'end')}"
            if params.get("end")
            else f"Trimmed from {params['start']} to end"
        )
        op = {
            "op": "trim_clip",
            "params": {"start": start_sec, "end": end_sec, "start_label": params["start"], "end_label": params.get("end")},
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "result_file": output_path,
            "description": description,
        }
        state.apply_operation(op)
        suggestion = None
        if state.metadata.get("duration_sec", 0.0) < 2.0:
            suggestion = "[SUGGESTION]: The resulting clip is under 2 seconds and may be too short for transitions - reply 'yes' to apply or continue."
        return {
            "success": True,
            "message": description + ".",
            "suggestion": suggestion,
            "updated_state": state,
            "tool_name": "trim_clip",
        }
    except (ValueError, VideoEngineError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "trim_clip",
        }
