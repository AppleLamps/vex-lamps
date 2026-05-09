from __future__ import annotations

from datetime import UTC, datetime

from engine import VideoEngineError, parse_timestamp, probe_video, remove_segment
from state import ProjectState


def execute(params: dict, state: ProjectState) -> dict:
    try:
        start_sec = parse_timestamp(params["start"])
        end_sec = parse_timestamp(params["end"])
        output_path = remove_segment(
            state.working_file,
            state.working_dir,
            start_sec,
            end_sec,
            input_duration_sec=float((state.metadata or {}).get("duration_sec") or 0.0) or None,
        )
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        description = f"Removed segment from {params['start']} to {params['end']}"
        op = {
            "op": "remove_segment",
            "params": {
                "start": start_sec,
                "end": end_sec,
                "start_label": params["start"],
                "end_label": params["end"],
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
            "tool_name": "remove_segment",
        }
    except (ValueError, VideoEngineError, KeyError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "remove_segment",
        }
