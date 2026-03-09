from __future__ import annotations

import os
from datetime import datetime, timezone

from engine import (
    VideoEngineError,
    extract_audio,
    mute_segment,
    parse_timestamp,
    probe_video,
    replace_audio,
)
from state import ProjectState


def execute_extract(params: dict, state: ProjectState) -> dict:
    fmt = params.get("format", "mp3")
    try:
        temp_output = extract_audio(state.working_file, state.working_dir, fmt)
        output_path = os.path.abspath(params["output_path"]) if params.get("output_path") else temp_output
        if output_path != temp_output:
            os.replace(temp_output, output_path)
        return {
            "success": True,
            "message": f"Extracted audio to {output_path}.",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "extract_audio",
        }
    except (VideoEngineError, OSError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "extract_audio",
        }


def execute_replace(params: dict, state: ProjectState) -> dict:
    audio_path = os.path.abspath(params["audio_path"])
    if not os.path.isfile(audio_path):
        return {
            "success": False,
            "message": f"Audio file not found: {audio_path}",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "replace_audio",
        }
    try:
        output_path = replace_audio(
            state.working_file,
            audio_path,
            state.working_dir,
            mix=bool(params.get("mix_with_original", False)),
            mix_ratio=float(params.get("mix_ratio", 0.5)),
        )
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        description = f"Replaced audio using {os.path.basename(audio_path)}"
        if params.get("mix_with_original", False):
            description = (
                f"Mixed audio using {os.path.basename(audio_path)} at ratio {float(params.get('mix_ratio', 0.5)):.2f}"
            )
        op = {
            "op": "replace_audio",
            "params": {
                "audio_path": audio_path,
                "mix_with_original": bool(params.get("mix_with_original", False)),
                "mix_ratio": float(params.get("mix_ratio", 0.5)),
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
            "tool_name": "replace_audio",
        }
    except VideoEngineError as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "replace_audio",
        }


def execute_mute(params: dict, state: ProjectState) -> dict:
    try:
        start_sec = parse_timestamp(params["start"])
        end_sec = parse_timestamp(params["end"])
        output_path = mute_segment(state.working_file, state.working_dir, start_sec, end_sec)
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        description = f"Muted segment from {params['start']} to {params['end']}"
        op = {
            "op": "mute_segment",
            "params": {
                "start": start_sec,
                "end": end_sec,
                "start_label": params["start"],
                "end_label": params["end"],
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
            "tool_name": "mute_segment",
        }
    except (ValueError, VideoEngineError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "mute_segment",
        }
