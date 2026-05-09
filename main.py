from __future__ import annotations

import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

import config
from agent import AgentLoopError, VideoAgent
from agent_trace import TraceEvent, render_trace_table
from engine import probe_video
from providers import get_provider
from repl import (
    ReplHandlers,
    direct_auto_broll,
    direct_auto_shorts,
    direct_auto_visuals,
    direct_export,
    find_project_for_source_url,
    run_repl,
)
from sources import download_youtube_video
from state import ProjectState, utc_now_iso
from ui import run_agent_with_live_trace

app = typer.Typer(help="Vex - AI-powered video editing agent.")
console = Console()


def initialize_runtime() -> None:
    config.configure_runtime_logging()
    config.validate_config()


def print_banner(model_name: str) -> None:
    banner = (
        " __      ________  __   __\n"
        " \\ \\    / /  ____| \\ \\ / /\n"
        "  \\ \\  / /| |__     \\ V /\n"
        "   \\ \\/ / |  __|     > <\n"
        "    \\  /  | |____   / . \\\n"
        "     \\/   |______| /_/ \\_\\\n\n"
        f"  v{config.VERSION}  |  {model_name}  |  multi-provider ready"
    )
    console.print(Panel.fit(banner, border_style="cyan", title="Vex"))


def create_provider(show_banner: bool = True):
    initialize_runtime()
    provider = get_provider(config.PROVIDER)
    if show_banner:
        print_banner(provider.model_name)
    return provider


def build_repl_handlers() -> ReplHandlers:
    return ReplHandlers(
        create_project=create_project,
        create_project_from_youtube=create_project_from_youtube,
        render_timeline=render_timeline,
        render_trace_history=render_trace_history,
        render_projects=render_projects,
    )


@app.callback(invoke_without_command=True)
def app_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", is_eager=True, help="Show version and exit."),
) -> None:
    if version:
        console.print(f"Vex v{config.VERSION}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        provider = create_provider()
        projects = ProjectState.list_projects()
        state = None
        if len(projects) == 1:
            state = ProjectState.load(projects[0]["project_id"])
            console.print(
                f"Resuming: [bold]{state.project_name}[/] (last edited {format_relative_time(state.updated_at)} ago)"
            )
        run_repl(state, provider, build_repl_handlers())
        raise typer.Exit()


def format_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_relative_time(iso_timestamp: str) -> str:
    try:
        timestamp = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return "unknown"
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - timestamp.astimezone(UTC)
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"




def create_project(video_path: str, name: str | None, provider_name: str, model_name: str) -> ProjectState:
    absolute_path = os.path.abspath(video_path)
    project_id = str(uuid.uuid4())
    project_name = name or Path(video_path).stem
    working_dir = Path(config.AGENT_PROJECTS_DIR) / project_id
    working_dir.mkdir(parents=True, exist_ok=True)
    working_file = str(working_dir / f"source_{Path(absolute_path).name}")
    shutil.copy2(absolute_path, working_file)
    metadata = probe_video(working_file)
    state = ProjectState(
        project_id=project_id,
        project_name=project_name,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
        source_files=[absolute_path],
        working_file=working_file,
        working_dir=str(working_dir),
        output_dir=str(Path(absolute_path).parent),
        timeline=[],
        redo_stack=[],
        session_log=[],
        metadata=metadata,
        provider=provider_name,
        model=model_name,
    )
    state.save()
    return state


def create_project_from_youtube(url: str, name: str | None, provider_name: str, model_name: str) -> ProjectState:
    project_id = str(uuid.uuid4())
    working_dir = Path(config.AGENT_PROJECTS_DIR) / project_id
    working_dir.mkdir(parents=True, exist_ok=True)
    download = download_youtube_video(url, str(working_dir))
    output_dir = working_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    working_file = os.path.abspath(download.downloaded_path)
    metadata = probe_video(working_file)
    state = ProjectState(
        project_id=project_id,
        project_name=name or download.title,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
        source_files=[working_file],
        working_file=working_file,
        working_dir=str(working_dir),
        output_dir=str(output_dir),
        timeline=[],
        redo_stack=[],
        session_log=[],
        metadata=metadata,
        artifacts={
            "source_url": download.source_url,
            "source_title": download.title,
            "source_id": download.video_id,
            "source_uploader": download.uploader,
        },
        provider=provider_name,
        model=model_name,
    )
    state.save()
    return state


def print_project_panel(state: ProjectState) -> None:
    metadata = state.metadata
    table = Table.grid(padding=(0, 2))
    table.add_row("File:", Path(state.source_files[0]).name)
    source_url = str((state.artifacts or {}).get("source_url") or "").strip()
    if source_url:
        table.add_row("Source URL:", source_url)
    table.add_row(
        "Duration:",
        f"{metadata.get('duration_sec', 0.0):.2f}s  |  {metadata.get('width', 0)}x{metadata.get('height', 0)}  |  {metadata.get('fps', 0)} fps",
    )
    table.add_row("Size:", format_bytes(metadata.get("size_bytes", 0)))
    table.add_row("Provider:", f"{state.provider} / {state.model}")
    table.add_row("Timeline:", f"{len(state.timeline)} operations")
    console.print(Panel(table, title=f"Project: {state.project_name}", border_style="green"))


def find_project(project: str | None) -> ProjectState:
    if project:
        return ProjectState.load(project)
    projects = ProjectState.list_projects()
    if not projects:
        raise typer.BadParameter("No saved projects found.")
    return ProjectState.load(projects[0]["project_id"])


def render_timeline(state: ProjectState) -> None:
    table = Table(title="Timeline", box=box.SIMPLE_HEAVY)
    table.add_column("#", justify="right")
    table.add_column("Operation")
    table.add_column("Parameters")
    table.add_column("Time")
    for index, op in enumerate(state.timeline, start=1):
        params = ", ".join(
            f"{key}={value}"
            for key, value in op.get("params", {}).items()
            if not key.endswith("_label") and key not in {"file_paths"}
        )
        table.add_row(str(index), op["op"], params or "-", op["timestamp"][11:19])
    console.print(table)


def render_projects() -> None:
    table = Table(title="Saved Projects", box=box.SIMPLE_HEAVY)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Created")
    table.add_column("Modified")
    table.add_column("Source File")
    table.add_column("Ops", justify="right")
    for item in ProjectState.list_projects():
        table.add_row(
            item["project_id"][:8],
            item["project_name"],
            item["created_at"],
            item["updated_at"],
            Path(item["source_file"]).name,
            str(item["timeline_ops"]),
        )
    console.print(table)


def render_trace_history(state: ProjectState) -> None:
    artifact = (state.artifacts or {}).get("latest_agent_trace")
    if not artifact:
        console.print("No agent trace recorded yet.")
        return
    events = [TraceEvent.from_dict(item) for item in artifact.get("events", [])]
    meta = Table.grid(padding=(0, 2))
    meta.add_row("Instruction:", str(artifact.get("instruction") or "unknown"))
    meta.add_row("Provider:", f"{artifact.get('provider', 'unknown')} / {artifact.get('model', 'unknown')}")
    meta.add_row("Success:", "yes" if artifact.get("success") else "no")
    if artifact.get("tools_called"):
        meta.add_row("Tools:", ", ".join(str(name) for name in artifact["tools_called"]))
    body = Group(meta, render_trace_table(events, max_items=16))
    console.print(Panel(body, title="Latest Agent Trace", border_style="magenta"))


@app.command()
def start(video_path: str, name: str | None = typer.Option(default=None, help="Project name.")) -> None:
    provider = create_provider()
    absolute_path = os.path.abspath(video_path)
    if not os.path.isfile(absolute_path):
        raise typer.BadParameter(f"Video file not found: {absolute_path}")
    state = create_project(absolute_path, name, config.PROVIDER, provider.model_name)
    print_project_panel(state)
    run_repl(state, provider, build_repl_handlers())


@app.command()
def repl(project: str | None = typer.Option(default=None, help="Project id.")) -> None:
    provider = create_provider()
    state = find_project(project)
    run_repl(state, provider, build_repl_handlers())


@app.command()
def web(
    project: str | None = typer.Option(default=None, help="Project id."),
    host: str = typer.Option("127.0.0.1", help="Host to bind."),
    port: int = typer.Option(8765, help="Port to bind."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the web console in your browser."),
) -> None:
    provider = create_provider()
    state = find_project(project) if project else None
    from web_app import run_web_app

    run_web_app(
        provider=provider,
        state=state,
        create_project=create_project,
        create_project_from_youtube=create_project_from_youtube,
        host=host,
        port=port,
        open_browser=open_browser,
    )


@app.command()
def run(
    instruction: str,
    project: str = typer.Option(..., help="Project id."),
) -> None:
    provider = create_provider()
    state = ProjectState.load(project)
    agent = VideoAgent(state, provider)
    try:
        response, _trace_events = run_agent_with_live_trace(agent, instruction)
    except AgentLoopError as exc:
        console.print(f"Agent error: {exc}", style="red")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print_exception()
        raise typer.Exit(code=1) from exc
    console.print(response.message)
    for suggestion in response.suggestions:
        console.print(Panel(suggestion, title="Suggestion", border_style="yellow"))


@app.command()
def projects() -> None:
    initialize_runtime()
    render_projects()


@app.command()
def export(
    preset_name: str,
    project: str = typer.Option(..., help="Project id."),
    output: str | None = typer.Option(default=None, help="Custom output path."),
) -> None:
    initialize_runtime()
    state = ProjectState.load(project)
    direct_export(state, preset_name, output)


@app.command()
def shorts(
    project: str = typer.Option(..., help="Project id."),
    count: int = typer.Option(3, help="Number of shorts to create."),
    min_duration_sec: float = typer.Option(20.0, help="Minimum duration per short."),
    max_duration_sec: float = typer.Option(45.0, help="Maximum duration per short."),
    target_platform: str = typer.Option(
        "youtube_shorts",
        help="Platform profile: youtube_shorts, tiktok, or instagram_reels.",
    ),
    include_compilation: bool = typer.Option(True, help="Also create a merged compilation."),
) -> None:
    initialize_runtime()
    if target_platform not in {"youtube_shorts", "tiktok", "instagram_reels"}:
        raise typer.BadParameter("target_platform must be one of: youtube_shorts, tiktok, instagram_reels")
    state = ProjectState.load(project)
    direct_auto_shorts(
        state,
        count=count,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
        target_platform=target_platform,
        include_compilation=include_compilation,
    )


@app.command()
def auto_broll(
    project: str = typer.Option(..., help="Project id."),
    max_overlays: int = typer.Option(5, help="Maximum number of stock inserts to add."),
    min_overlay_sec: float = typer.Option(1.2, help="Minimum duration of each insert."),
    max_overlay_sec: float = typer.Option(2.8, help="Maximum duration of each insert."),
) -> None:
    initialize_runtime()
    state = ProjectState.load(project)
    direct_auto_broll(
        state,
        max_overlays=max_overlays,
        min_overlay_sec=min_overlay_sec,
        max_overlay_sec=max_overlay_sec,
    )


@app.command()
def auto_visuals(
    project: str = typer.Option(..., help="Project id."),
    mode: str = typer.Option("generated_only", help="generated_only, hybrid, or stock_only."),
    renderer: str = typer.Option("auto", help="Renderer backend preference: auto, manim, ffmpeg, or blender."),
    style_pack: str = typer.Option(
        "auto",
        help="Preferred style pack: auto, editorial_clean, bold_tech, documentary_kinetic, product_ui, cinematic_night, signal_lab, or magazine_luxe.",
    ),
    max_visuals: int = typer.Option(3, help="Maximum number of generated visuals to add."),
    min_visual_sec: float = typer.Option(1.4, help="Minimum duration of each generated visual."),
    max_visual_sec: float = typer.Option(3.6, help="Maximum duration of each generated visual."),
) -> None:
    initialize_runtime()
    if mode not in {"generated_only", "hybrid", "stock_only"}:
        raise typer.BadParameter("mode must be one of: generated_only, hybrid, stock_only")
    if renderer not in {"auto", "manim", "ffmpeg", "blender"}:
        raise typer.BadParameter("renderer must be one of: auto, manim, ffmpeg, blender")
    if style_pack not in {"auto", "editorial_clean", "bold_tech", "documentary_kinetic", "product_ui", "cinematic_night", "signal_lab", "magazine_luxe"}:
        raise typer.BadParameter(
            "style_pack must be one of: auto, editorial_clean, bold_tech, documentary_kinetic, product_ui, cinematic_night, signal_lab, magazine_luxe"
        )
    state = ProjectState.load(project)
    direct_auto_visuals(
        state,
        mode=mode,
        renderer=renderer,
        style_pack=style_pack,
        max_visuals=max_visuals,
        min_visual_sec=min_visual_sec,
        max_visual_sec=max_visual_sec,
    )


@app.command()
def youtube_shorts(
    url: str,
    count: int = typer.Option(3, help="Number of shorts to create."),
    min_duration_sec: float = typer.Option(20.0, help="Minimum duration per short."),
    max_duration_sec: float = typer.Option(45.0, help="Maximum duration per short."),
    target_platform: str = typer.Option(
        "youtube_shorts",
        help="Platform profile: youtube_shorts, tiktok, or instagram_reels.",
    ),
    include_compilation: bool = typer.Option(True, help="Also create a merged compilation."),
    name: str | None = typer.Option(default=None, help="Optional project name override."),
) -> None:
    initialize_runtime()
    if target_platform not in {"youtube_shorts", "tiktok", "instagram_reels"}:
        raise typer.BadParameter("target_platform must be one of: youtube_shorts, tiktok, instagram_reels")
    try:
        state = find_project_for_source_url(url) or create_project_from_youtube(
            url,
            name=name,
            provider_name=config.PROVIDER,
            model_name=create_provider(show_banner=False).model_name,
        )
    except Exception as exc:
        raise typer.BadParameter(f"Failed to prepare YouTube video: {exc}") from exc
    print_project_panel(state)
    direct_auto_shorts(
        state,
        count=count,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
        target_platform=target_platform,
        include_compilation=include_compilation,
    )


if __name__ == "__main__":
    app()
