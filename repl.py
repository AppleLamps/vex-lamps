from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

import config
from agent import AgentLoopError, VideoAgent
from engine import check_disk_space, estimate_output_size
from engine import export as export_media
from sources import extract_youtube_url, normalize_source_url
from state import ProjectState
from tools import TOOL_EXECUTORS
from tools.export import load_presets
from ui import run_agent_with_live_trace

console = Console()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv"}
LOAD_COMMAND_RE = re.compile(r"^(?:load|open|use|switch(?:\s+to)?)\s+(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class ReplHandlers:
    create_project: Callable[[str, str | None, str, str], ProjectState]
    create_project_from_youtube: Callable[[str, str | None, str, str], ProjectState]
    render_timeline: Callable[[ProjectState], None]
    render_trace_history: Callable[[ProjectState], None]
    render_projects: Callable[[], None]


def format_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


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


def direct_export(state: ProjectState, preset_name: str, output: str | None = None) -> None:
    presets = load_presets()
    if preset_name not in presets:
        raise typer.BadParameter(f"Unknown preset {preset_name!r}.")
    preset = presets[preset_name]
    if output:
        output_path = os.path.abspath(output)
    else:
        suffix = preset.get("format") or "mp4"
        stem = "".join(ch for ch in state.project_name.replace(" ", "_") if ch.isalnum() or ch in {"_", "-"})
        output_path = os.path.join(state.output_dir, f"{stem}_{preset_name}.{suffix}")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    estimated = estimate_output_size(state.working_file, preset)
    if not check_disk_space(output_path, estimated):
        raise typer.BadParameter("Not enough free disk space for the requested export.")
    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        console=console,
    )
    with progress:
        task = progress.add_task("Exporting...", total=100)

        def on_progress(value: float) -> None:
            progress.update(task, completed=value * 100)

        export_media(state.working_file, output_path, preset, progress_callback=on_progress)
    console.print(f"Saved: {output_path} ({format_bytes(os.path.getsize(output_path))})")


def direct_auto_shorts(
    state: ProjectState,
    count: int,
    min_duration_sec: float,
    max_duration_sec: float,
    target_platform: str,
    include_compilation: bool,
) -> None:
    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    )
    with progress:
        progress.add_task("Creating auto shorts...", total=None)
        result = TOOL_EXECUTORS["create_auto_shorts"](
            {
                "count": count,
                "min_duration_sec": min_duration_sec,
                "max_duration_sec": max_duration_sec,
                "target_platform": target_platform,
                "include_compilation": include_compilation,
            },
            state,
        )
    if not result["success"]:
        console.print(result["message"], style="red")
        raise typer.Exit(code=1)
    console.print(result["message"])


def direct_auto_broll(
    state: ProjectState,
    max_overlays: int,
    min_overlay_sec: float,
    max_overlay_sec: float,
) -> None:
    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    )
    with progress:
        progress.add_task("Adding auto B-roll...", total=None)
        result = TOOL_EXECUTORS["add_auto_broll"](
            {
                "max_overlays": max_overlays,
                "min_overlay_sec": min_overlay_sec,
                "max_overlay_sec": max_overlay_sec,
            },
            state,
        )
    if not result["success"]:
        console.print(result["message"], style="red")
        raise typer.Exit(code=1)
    console.print(result["message"])


def direct_auto_visuals(
    state: ProjectState,
    mode: str,
    renderer: str,
    style_pack: str,
    max_visuals: int,
    min_visual_sec: float,
    max_visual_sec: float,
) -> None:
    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    )
    with progress:
        progress.add_task("Adding auto visuals...", total=None)
        result = TOOL_EXECUTORS["add_auto_visuals"](
            {
                "mode": mode,
                "renderer": renderer,
                "style_pack": style_pack,
                "max_visuals": max_visuals,
                "min_visual_sec": min_visual_sec,
                "max_visual_sec": max_visual_sec,
            },
            state,
        )
    if not result["success"]:
        console.print(result["message"], style="red")
        raise typer.Exit(code=1)
    console.print(result["message"])


def run_repl(state: ProjectState | None, provider, handlers: ReplHandlers) -> None:
    agent = VideoAgent(state, provider) if state is not None else None
    while True:
        try:
            user_input = console.input("[bold cyan]Vex > [/]")
        except KeyboardInterrupt:
            answer = console.input("\nSave and exit? [y/n] ").strip().lower()
            if answer.startswith("y"):
                if state is not None:
                    state.save()
                console.print("Project saved. Goodbye.")
                return
            continue
        command = user_input.strip()
        if not command:
            continue
        if command in {"/quit", "/exit"}:
            if state is not None:
                state.save()
            console.print("Project saved. Goodbye.")
            return
        if command == "/help":
            console.print(
                "/status, /timeline, /trace, /undo, /redo, /export <preset>, /provider, /projects, /help, /quit"
            )
            continue
        if command == "/status":
            if state is None:
                console.print("No video loaded. Drop a file path or YouTube link in your message to get started.")
            else:
                console.print(state.get_summary())
            continue
        if command == "/timeline":
            if state is None:
                console.print("No video loaded. Drop a file path or YouTube link in your message to get started.")
            else:
                handlers.render_timeline(state)
            continue
        if command == "/trace":
            if state is None:
                console.print("No video loaded. Drop a file path or YouTube link in your message to get started.")
            else:
                handlers.render_trace_history(state)
            continue
        if command == "/provider":
            if state is None:
                console.print(f"Active: {config.PROVIDER} / {provider.model_name}")
            else:
                console.print(f"Active: {state.provider} / {state.model}")
            continue
        if command == "/projects":
            handlers.render_projects()
            continue
        if command == "/undo":
            if state is None:
                console.print("No video loaded. Drop a file path or YouTube link in your message to get started.")
                continue
            result = TOOL_EXECUTORS["undo"]({}, state)
            state = result["updated_state"]
            if agent is not None:
                agent.state = state
            console.print(result["message"])
            continue
        if command == "/redo":
            if state is None:
                console.print("No video loaded. Drop a file path or YouTube link in your message to get started.")
                continue
            result = TOOL_EXECUTORS["redo"]({}, state)
            state = result["updated_state"]
            if agent is not None:
                agent.state = state
            console.print(result["message"])
            continue
        if command.startswith("/export"):
            if state is None:
                console.print("No video loaded. Drop a file path or YouTube link in your message to get started.")
                continue
            parts = command.split(maxsplit=1)
            if len(parts) != 2:
                console.print("Usage: /export <preset>")
                continue
            direct_export(state, parts[1].strip())
            continue

        load_request = parse_load_source_command(command)
        if load_request is not None:
            load_kind, load_target = load_request
            if load_kind == "path":
                already_loaded = is_loaded_source(state, load_target)
                if already_loaded and state is not None:
                    console.print(format_loaded_state_message(state, already_loaded=True))
                    continue
                console.print(f"Loading: {Path(load_target).name}...")
                state = find_project_for_source(load_target)
                if state is None:
                    state = handlers.create_project(load_target, None, config.PROVIDER, provider.model_name)
                agent = VideoAgent(state, provider)
                console.print(format_loaded_state_message(state, already_loaded=False))
                continue
            already_loaded = is_loaded_source_url(state, load_target)
            if already_loaded and state is not None:
                console.print(format_loaded_state_message(state, already_loaded=True))
                continue
            console.print("Fetching video from YouTube...")
            state = find_project_for_source_url(load_target)
            if state is None:
                try:
                    state = handlers.create_project_from_youtube(load_target, None, config.PROVIDER, provider.model_name)
                except Exception as exc:
                    console.print(f"Failed to download YouTube video: {exc}", style="red")
                    continue
            agent = VideoAgent(state, provider)
            console.print(format_loaded_state_message(state, already_loaded=False))
            continue

        detected_path = detect_video_path(command)
        detected_url = extract_youtube_url(command)
        if detected_path and not is_loaded_source(state, detected_path):
            console.print(f"Loading: {Path(detected_path).name}...")
            state = find_project_for_source(detected_path)
            if state is None:
                state = handlers.create_project(detected_path, None, config.PROVIDER, provider.model_name)
            agent = VideoAgent(state, provider)
        elif detected_url and not is_loaded_source_url(state, detected_url):
            console.print("Fetching video from YouTube...")
            state = find_project_for_source_url(detected_url)
            if state is None:
                try:
                    state = handlers.create_project_from_youtube(detected_url, None, config.PROVIDER, provider.model_name)
                except Exception as exc:
                    console.print(f"Failed to download YouTube video: {exc}", style="red")
                    continue
            agent = VideoAgent(state, provider)
        elif state is None:
            console.print("No video loaded. Drop a file path or YouTube link in your message to get started.")
            continue

        try:
            response, _trace_events = run_agent_with_live_trace(agent, command)
        except AgentLoopError as exc:
            console.print(f"Agent error: {exc}", style="red")
            continue
        except Exception:
            console.print_exception()
            continue

        state = agent.state
        if response.message:
            console.print(response.message)
        for suggestion in response.suggestions:
            console.print(Panel(suggestion, title="Suggestion", border_style="yellow"))
