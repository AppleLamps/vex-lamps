from __future__ import annotations

import os
from datetime import UTC, datetime

from engine import VideoEngineError, merge, probe_video
from state import ProjectState


def execute(params: dict, state: ProjectState) -> dict:
    paths = params.get("file_paths") or []
    resolved = [os.path.abspath(path) for path in paths]
    missing = [path for path in resolved if not os.path.isfile(path)]
    if missing:
        return {
            "success": False,
            "message": f"Missing clip(s): {', '.join(missing)}",
            "suggestion": None,
            "updated_state": state,
            "tool_name": "merge_clips",
        }
    all_paths = [state.working_file, *resolved]
    try:
        metadata = [probe_video(path) for path in all_paths]
        mismatched = len({(item["width"], item["height"]) for item in metadata}) > 1
        metadata_by_path = {path: item for path, item in zip(all_paths, metadata, strict=False)}
        output_path = merge(all_paths, state.working_dir, metadata_by_path=metadata_by_path)
        state.working_file = output_path
        state.metadata = probe_video(output_path)
        op = {
            "op": "merge_clips",
            "params": {"file_paths": ["__CURRENT__", *resolved]},
            "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "result_file": output_path,
            "description": f"Merged {len(all_paths)} clips",
        }
        state.apply_operation(op)
        suggestion = None
        if mismatched:
            suggestion = "[SUGGESTION]: The merged clips had mismatched resolutions, so auto-scaling was applied - reply 'yes' to apply or continue."
        return {
            "success": True,
            "message": f"Merged {len(all_paths)} clips successfully.",
            "suggestion": suggestion,
            "updated_state": state,
            "tool_name": "merge_clips",
        }
    except VideoEngineError as exc:
        return {
            "success": False,
            "message": str(exc),
            "suggestion": None,
            "updated_state": state,
            "tool_name": "merge_clips",
        }
