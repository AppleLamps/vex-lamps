from __future__ import annotations

from prompts import TOOL_SCHEMAS
from tools import audio, export, info, merge, overlay, speed, transcript, transitions, trim, undo

TOOL_EXECUTORS = {
    "get_video_info": info.execute,
    "trim_clip": trim.execute,
    "merge_clips": merge.execute,
    "adjust_speed": speed.execute,
    "add_transition": transitions.execute,
    "add_text_overlay": overlay.execute,
    "extract_audio": audio.execute_extract,
    "replace_audio": audio.execute_replace,
    "mute_segment": audio.execute_mute,
    "export_video": export.execute,
    "undo": undo.execute_undo,
    "redo": undo.execute_redo,
    "transcribe_video": transcript.execute,
}
