from __future__ import annotations

from engine import probe_video
from state import ProjectState


def execute(params: dict, state: ProjectState) -> dict:
    metadata = probe_video(state.working_file)
    state.metadata = metadata
    state.save()
    message = (
        f"Video info: duration {metadata['duration_sec']:.2f}s, "
        f"{metadata['width']}x{metadata['height']} at {metadata['fps']}fps, "
        f"codec {metadata['codec']}, audio {'yes' if metadata['has_audio'] else 'no'}."
    )
    return {
        "success": True,
        "message": message,
        "suggestion": None,
        "updated_state": state,
        "tool_name": "get_video_info",
    }
