from __future__ import annotations

from datetime import datetime, timezone

from engine import VideoEngineError, adjust_speed, parse_timestamp, probe_video
from state import ProjectState


def execute(params: dict, state: ProjectState) -> dict:
    factor = float(params["factor"])
    if factor < 0.25 or factor > 4.0:
        return {
            "success": False,
            "message": "Speed factor must be between 0.25 and 4.0.",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "adjust_speed",
        }
    try:
        start_sec = parse_timestamp(params["start"]) if params.get("start") else None
        end_sec = parse_timestamp(params["end"]) if params.get("end") else None
        output_path = adjust_speed(
            state.working_file,
            state.working_dir,
            factor,
            start_sec,
            end_sec,
            input_duration_sec=float((state.metadata or {}).get("duration_sec") or 0.0) or None,
        )
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        description = (
            f"Adjusted speed to {factor}x for segment {params['start']} to {params.get('end', 'end')}"
            if start_sec is not None or end_sec is not None
            else f"Adjusted speed to {factor}x"
        )
        op = {
            "op": "adjust_speed",
            "params": {
                "factor": factor,
                "start": start_sec,
                "end": end_sec,
                "start_label": params.get("start"),
                "end_label": params.get("end"),
            },
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "result_file": output_path,
            "description": description,
        }
        state.apply_operation(op)
        suggestion = None
        if state.metadata.get("has_audio") and factor != 1.0:
            suggestion = "[SUGGESTION]: Speed changes can affect speech naturalness and pitch perception even with audio correction - reply 'yes' to apply or continue."
        return {
            "success": True,
            "message": description + ".",
            "suggestion": suggestion,
            "updated_state": state,
            "tool_name": "adjust_speed",
        }
    except (ValueError, VideoEngineError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "adjust_speed",
        }
