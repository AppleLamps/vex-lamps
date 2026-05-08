from __future__ import annotations

import os
import re
from pathlib import Path

from sources import extract_youtube_url, normalize_source_url
from state import ProjectState

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv"}
LOAD_COMMAND_RE = re.compile(r"^(?:load|open|use|switch(?:\s+to)?)\s+(.+)$", re.IGNORECASE)

def strip_wrapping_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def is_video_path(path: str) -> bool:
    candidate = os.path.abspath(strip_wrapping_quotes(path))
    return os.path.isfile(candidate) and Path(candidate).suffix.lower() in VIDEO_EXTENSIONS


def detect_video_path(user_input: str) -> str | None:
    full_candidate = strip_wrapping_quotes(user_input)
    if is_video_path(full_candidate):
        return os.path.abspath(full_candidate)

    for match in re.findall(r'"([^"]+)"|\'([^\']+)\'', user_input):
        candidate = next((group for group in match if group), "")
        if candidate and is_video_path(candidate):
            return os.path.abspath(strip_wrapping_quotes(candidate))

    for token in user_input.split():
        candidate = strip_wrapping_quotes(token)
        if is_video_path(candidate):
            return os.path.abspath(candidate)
    return None


def is_loaded_source(state: ProjectState | None, candidate_path: str) -> bool:
    if state is None or not state.source_files:
        return False
    current_source = os.path.abspath(state.source_files[0])
    return os.path.normcase(current_source) == os.path.normcase(os.path.abspath(candidate_path))


def find_project_for_source(video_path: str) -> ProjectState | None:
    target = os.path.normcase(os.path.abspath(video_path))
    for project in ProjectState.list_projects():
        source_file = project.get("source_file", "")
        if source_file and os.path.normcase(os.path.abspath(source_file)) == target:
            return ProjectState.load(project["project_id"])
    return None


def is_loaded_source_url(state: ProjectState | None, candidate_url: str) -> bool:
    if state is None:
        return False
    current_url = str((state.artifacts or {}).get("source_url") or "").strip()
    return bool(current_url) and current_url == normalize_source_url(candidate_url)


def find_project_for_source_url(url: str) -> ProjectState | None:
    normalized = normalize_source_url(url)
    for project in ProjectState.list_projects():
        loaded = ProjectState.load(project["project_id"])
        if str((loaded.artifacts or {}).get("source_url") or "").strip() == normalized:
            return loaded
    return None


def parse_load_source_command(command: str) -> tuple[str, str] | None:
    stripped = command.strip()
    if not stripped:
        return None

    if is_video_path(stripped):
        return ("path", os.path.abspath(strip_wrapping_quotes(stripped)))

    bare_url = extract_youtube_url(stripped)
    if bare_url and normalize_source_url(stripped) == normalize_source_url(bare_url):
        return ("url", bare_url)

    match = LOAD_COMMAND_RE.match(stripped)
    if not match:
        return None
    target = match.group(1).strip()
    if is_video_path(target):
        return ("path", os.path.abspath(strip_wrapping_quotes(target)))
    target_url = extract_youtube_url(target)
    if target_url and normalize_source_url(target) == normalize_source_url(target_url):
        return ("url", target_url)
    return None


def format_loaded_state_message(state: ProjectState, *, already_loaded: bool) -> str:
    metadata = state.metadata or {}
    duration_sec = float(metadata.get("duration_sec") or 0.0)
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    fps_value = float(metadata.get("fps") or 0.0)
    resolution = f"{height}p" if height else f"{width}x{height}" if width or height else "unknown resolution"
    if fps_value.is_integer():
        fps_text = f"{int(fps_value)}fps"
    else:
        fps_text = f"{fps_value:.2f}fps"
    prefix = "Already loaded." if already_loaded else "Loaded."
    return f"{prefix} {duration_sec:.2f}s, {resolution}, {fps_text}. Ready."
