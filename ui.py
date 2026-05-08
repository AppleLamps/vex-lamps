from __future__ import annotations

import contextlib
import re
import shutil
import sys
import threading
import time
from collections import deque

from agent import AgentLoopError, VideoAgent
from agent_trace import TraceEvent, trace_status_style, truncate_trace_text
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
PROGRESS_HINT_RE = re.compile(r"(%\||frames/s|it/s|\bETA\b|\b\d+/\d+\b)", re.IGNORECASE)


class LiveLogBuffer:
    def __init__(
        self,
        *,
        max_lines: int = 6,
        max_line_length: int = 160,
        on_update=None,
    ) -> None:
        self.max_lines = max_lines
        self.max_line_length = max_line_length
        self.on_update = on_update
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._current = ""

    def _normalize(self, value: str) -> str:
        cleaned = ANSI_ESCAPE_RE.sub("", str(value or ""))
        cleaned = " ".join(cleaned.replace("\t", " ").split()).strip()
        if len(cleaned) > self.max_line_length:
            cleaned = cleaned[: self.max_line_length - 3].rstrip() + "..."
        return cleaned

    def _push_line(self, value: str, *, replace_last: bool) -> bool:
        line = self._normalize(value)
        if not line:
            return False
        if replace_last and self._lines:
            if self._lines[-1] != line:
                self._lines[-1] = line
                return True
            return False
        elif not self._lines or self._lines[-1] != line:
            self._lines.append(line)
            return True
        return False

    def write(self, text: str) -> int:
        if not text:
            return 0
        changed = False
        cleaned = ANSI_ESCAPE_RE.sub("", str(text)).replace("\r\n", "\n")
        for part in re.split(r"(\r|\n)", cleaned):
            if not part:
                continue
            if part == "\r":
                if self._current.strip():
                    changed = self._push_line(self._current, replace_last=True) or changed
                self._current = ""
                continue
            if part == "\n":
                if self._current.strip():
                    changed = (
                        self._push_line(self._current, replace_last=bool(PROGRESS_HINT_RE.search(self._current)))
                        or changed
                    )
                self._current = ""
                continue
            self._current += part
            if PROGRESS_HINT_RE.search(self._current):
                changed = self._push_line(self._current, replace_last=True) or changed
                self._current = ""
        if changed and self.on_update is not None:
            self.on_update()
        return len(text)

    def flush(self, *, notify: bool = True) -> None:
        if self._current.strip():
            changed = self._push_line(self._current, replace_last=bool(PROGRESS_HINT_RE.search(self._current)))
            self._current = ""
            if notify and changed and self.on_update is not None:
                self.on_update()

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"

    def snapshot(self) -> list[str]:
        self.flush(notify=False)
        return list(self._lines)

    def has_content(self) -> bool:
        return bool(self.snapshot())


def clip_live_text(output: Text, *, max_lines: int = 10, max_chars: int = 1600) -> Text:
    plain = output.plain.strip()
    if not plain:
        return Text("")
    if len(plain) > max_chars:
        plain = plain[-max_chars:]
    lines = plain.splitlines()
    if len(lines) > max_lines:
        lines = ["..."] + lines[-max_lines:]
    return Text("\n".join(lines))


def clip_tool_lines(lines: list[str], *, max_lines: int = 12, max_chars: int = 1800) -> Text:
    if not lines:
        return Text("")
    clipped = list(lines[-max_lines:])
    joined = "\n".join(clipped)
    if len(joined) > max_chars:
        joined = "...\n" + joined[-max_chars:]
    return Text(joined, style="dim")


def _status_from_trace_events(trace_events: list[TraceEvent], active_tool_name: str | None) -> tuple[str, str, str, bool]:
    if active_tool_name:
        return ("Running tool", active_tool_name, "yellow", True)
    if not trace_events:
        return ("Thinking", "Waiting for the first agent update.", "cyan", True)

    last_event = trace_events[-1]
    title = str(last_event.title or "Working")
    detail = str(last_event.detail or "").strip()
    status = str(last_event.status or "info").strip().lower()
    running = status == "running"

    if title.startswith("Planning pass"):
        return ("Thinking", "Reviewing the project and deciding the next step.", "yellow", True)
    if title == "Sending request to Gemini":
        return ("Thinking", detail or "Calling the Gemini model.", "yellow", True)
    if title == "Streaming assistant response":
        return ("Writing response", detail or "Receiving model output.", "yellow", True)
    if title == "Model requested tools":
        return ("Preparing tools", detail or "The model picked tools to run.", "cyan", True)
    if title.startswith("Running "):
        return ("Running tool", title.replace("Running ", "", 1), "yellow", True)
    if title.endswith(" completed"):
        return ("Tool finished", title.replace(" completed", "", 1), "green", False)
    if title.endswith(" failed"):
        return ("Tool failed", title.replace(" failed", "", 1), "red", False)
    if title == "Final response ready":
        return ("Done", detail or "Turn complete.", "green" if status != "error" else "red", False)
    if status == "error":
        return ("Error", f"{title}: {detail}".strip(": "), "red", False)
    if status == "success":
        return ("Done", f"{title}: {detail}".strip(": "), "green", False)
    return (title, detail, trace_status_style(status), running)


def _one_line_status(
    trace_events: list[TraceEvent],
    active_tool_name: str | None,
    tool_logs: LiveLogBuffer,
) -> str:
    status_label, status_detail, _status_style, _show_spinner = _status_from_trace_events(trace_events, active_tool_name)
    parts: list[str] = []
    if status_label:
        parts.append(status_label)
    if status_detail:
        parts.append(status_detail)
    if active_tool_name:
        parts.append(f"tool={active_tool_name}")
    tool_lines = tool_logs.snapshot()
    if tool_lines:
        latest_log = str(tool_lines[-1]).strip()
        if latest_log:
            parts.append(latest_log)
    collapsed = " | ".join(part for part in parts if part).strip()
    return truncate_trace_text(collapsed or "Working...", 220)


def _clean_live_status_line(line: str) -> str:
    cleaned = str(line or "").strip()
    cleaned = re.sub(r"^\[[^\]]+\]\s*", "", cleaned)
    return truncate_trace_text(cleaned, 180)


def _compact_live_status(
    command: str,
    trace_events: list[TraceEvent],
    active_tool_name: str | None,
    tool_logs: LiveLogBuffer,
    *,
    elapsed_sec: int,
) -> str:
    if active_tool_name:
        label = f"Running {active_tool_name}"
        detail = ""
    else:
        label, detail, _status_style, _show_spinner = _status_from_trace_events(trace_events, active_tool_name)
    latest_log = ""
    tool_lines = tool_logs.snapshot()
    if tool_lines:
        latest_log = _clean_live_status_line(tool_lines[-1])
    if detail == "Waiting for the first agent update.":
        detail = ""
    if label == "Thinking" and not detail:
        detail = truncate_trace_text(command, 80)
    parts = [label or "Working"]
    if latest_log:
        parts.append(latest_log)
    elif detail:
        parts.append(truncate_trace_text(detail, 120))
    parts.append(f"{max(elapsed_sec, 0)}s")
    return " | ".join(part for part in parts if part)


def _spinner_status_text(
    command: str,
    trace_events: list[TraceEvent],
    active_tool_name: str | None,
    tool_logs: LiveLogBuffer,
    *,
    elapsed_sec: int,
) -> str:
    latest_log = ""
    tool_lines = tool_logs.snapshot()
    if tool_lines:
        latest_log = _clean_live_status_line(tool_lines[-1])

    if active_tool_name:
        parts = [f"Running tool: {active_tool_name}"]
        if latest_log:
            parts.append(latest_log)
        parts.append(f"{max(elapsed_sec, 0)}s")
        return " | ".join(part for part in parts if part)

    if not trace_events:
        return f"Thinking... | {truncate_trace_text(command, 80)} | {max(elapsed_sec, 0)}s"

    last_event = trace_events[-1]
    title = str(last_event.title or "").strip()
    detail = str(last_event.detail or "").strip()
    status = str(last_event.status or "info").strip().lower()

    if title.startswith("Planning pass"):
        label = "Thinking..."
        detail = "Reviewing the project"
    elif title.startswith("Sending request to "):
        label = "Calling model..."
    elif title == "Streaming assistant response":
        label = "Writing response..."
    elif title == "Model requested tools":
        label = "Preparing tools..."
    elif title.startswith("Running "):
        label = f"Running tool: {title.replace('Running ', '', 1)}"
        detail = latest_log or detail
    elif title.endswith(" completed"):
        label = f"Finished tool: {title.replace(' completed', '', 1)}"
    elif title.endswith(" failed"):
        label = f"Tool failed: {title.replace(' failed', '', 1)}"
    elif title == "Final response ready":
        label = "Finalizing response..."
    elif status == "error":
        label = "Handling error..."
    else:
        label = title or "Working..."

    parts = [label]
    if latest_log and not active_tool_name and not title.startswith("Running "):
        parts.append(latest_log)
    elif detail:
        parts.append(truncate_trace_text(detail, 120))
    parts.append(f"{max(elapsed_sec, 0)}s")
    return " | ".join(part for part in parts if part)


class TerminalSpinnerLine:
    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.__stdout__
        self.frames = ("|", "/", "-", "\\")
        self.enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self._lock = threading.Lock()
        self._last_rendered_width = 0

    def render(self, text: str, *, frame_index: int) -> None:
        if not self.enabled:
            return
        width = max(shutil.get_terminal_size((120, 20)).columns - 1, 24)
        line = f"{self.frames[frame_index % len(self.frames)]} {truncate_trace_text(text, width - 2)}"
        with self._lock:
            padding = max(self._last_rendered_width - len(line), 0)
            self.stream.write("\r" + line + (" " * padding))
            self.stream.flush()
            self._last_rendered_width = len(line)

    def clear(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._last_rendered_width > 0:
                self.stream.write("\r" + (" " * self._last_rendered_width) + "\r")
                self.stream.flush()
                self._last_rendered_width = 0


def render_live_agent_view(
    output: Text,
    trace_events: list[TraceEvent],
    tool_logs: LiveLogBuffer,
    *,
    active_tool_name: str | None,
):
    tool_lines = tool_logs.snapshot()
    status_label, status_detail, status_style, show_spinner = _status_from_trace_events(trace_events, active_tool_name)
    sections: list[object] = []

    header_grid = Table.grid(expand=True)
    header_grid.add_column(width=2)
    header_grid.add_column(ratio=1)
    if show_spinner:
        header_grid.add_row(Spinner("dots", style=status_style), Text(f"{status_label}: {status_detail}", style=f"bold {status_style}"))
    else:
        header_grid.add_row(Text(""), Text(f"{status_label}: {status_detail}", style=f"bold {status_style}"))
    sections.append(header_grid)

    if active_tool_name:
        sections.extend(
            [
                Text(""),
                Text(f"Tool: {active_tool_name}", style="bold cyan"),
            ]
        )
    if tool_lines:
        sections.extend(
            [
                Text(""),
                Text("Logs", style="bold blue"),
                clip_tool_lines(tool_lines),
            ]
        )
    elif output.plain.strip():
        sections.extend(
            [
                Text(""),
                Text("Assistant", style="bold green"),
                clip_live_text(output),
            ]
        )
    return Panel(
        Group(*sections),
        title="Working",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def run_agent_with_live_trace(agent: VideoAgent, command: str):
    output = Text()
    trace_events: list[TraceEvent] = []
    tool_logs = LiveLogBuffer()
    active_tool_name: str | None = None
    started_at = time.monotonic()
    stop_event = threading.Event()
    status_text = {"value": f"Thinking... | {truncate_trace_text(command, 80)} | 0s"}
    spinner_line = TerminalSpinnerLine()

    def refresh_status() -> None:
        status_text["value"] = _spinner_status_text(
            command,
            trace_events,
            active_tool_name,
            tool_logs,
            elapsed_sec=int(time.monotonic() - started_at),
        )

    tool_logs.on_update = refresh_status

    def stream_callback(chunk: str) -> None:
        output.append(chunk)
        refresh_status()

    def trace_callback(event: TraceEvent) -> None:
        trace_events.append(event)
        refresh_status()

    def tool_callback(phase: str, tool_name: str, _ok: bool) -> None:
        nonlocal active_tool_name
        if phase == "start":
            active_tool_name = tool_name
        elif phase == "finish" and active_tool_name == tool_name:
            active_tool_name = None
        refresh_status()

    response = None
    frame_index = {"value": 0}

    def heartbeat() -> None:
        while not stop_event.is_set():
            refresh_status()
            spinner_line.render(status_text["value"], frame_index=frame_index["value"])
            frame_index["value"] += 1
            stop_event.wait(0.12)

    heartbeat_thread = threading.Thread(target=heartbeat, name="vex-live-status", daemon=True)
    heartbeat_thread.start()
    try:
        with contextlib.redirect_stdout(tool_logs), contextlib.redirect_stderr(tool_logs):
            response = agent.run(
                command,
                stream_callback=stream_callback,
                tool_callback=tool_callback,
                trace_callback=trace_callback,
            )
    finally:
        tool_logs.flush()
        stop_event.set()
        heartbeat_thread.join(timeout=1.5)
        spinner_line.clear()
    if response is None:
        raise AgentLoopError("The agent run did not return a response.")
    return response, trace_events
