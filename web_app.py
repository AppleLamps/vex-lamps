from __future__ import annotations

import json
import mimetypes
import os
import queue
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import config
from agent import AgentLoopError, VideoAgent
from engine import probe_video
from repl import (
    detect_video_path,
    find_project_for_source,
    find_project_for_source_url,
    format_loaded_state_message,
    is_loaded_source,
    is_loaded_source_url,
    parse_load_source_command,
)
from sources import extract_youtube_url
from state import ProjectState, utc_now_iso

CreateProject = Callable[[str, str | None, str, str], ProjectState]
CreateProjectFromYoutube = Callable[[str, str | None, str, str], ProjectState]

STATIC_DIR = Path(__file__).resolve().parent / "web_static"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv"}
DEFAULT_MAX_UPLOAD_MB = 4096
UPLOAD_CHUNK_SIZE = 1024 * 1024


class WebAppError(RuntimeError):
    status = HTTPStatus.BAD_REQUEST


class JobConflictError(WebAppError):
    status = HTTPStatus.CONFLICT


def max_upload_bytes() -> int:
    raw = str(os.getenv("VEX_WEB_MAX_UPLOAD_MB") or DEFAULT_MAX_UPLOAD_MB).strip()
    try:
        mb = max(1, int(raw))
    except ValueError:
        mb = DEFAULT_MAX_UPLOAD_MB
    return mb * 1024 * 1024


def load_index_html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def _artifact(state: ProjectState, key: str) -> dict[str, Any] | None:
    value = (state.artifacts or {}).get(key)
    return value if isinstance(value, dict) else None


def _safe_upload_name(filename: str) -> str:
    name = Path(filename or "").name.strip().replace("\x00", "")
    if not name:
        raise ValueError("Missing upload filename.")
    stem = "".join(ch for ch in Path(name).stem if ch.isalnum() or ch in {"_", "-", " "}).strip()
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError(f"Unsupported video extension: {suffix or 'none'}.")
    return f"{stem or 'upload'}{suffix}"


def _project_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("project_id", ""),
        "short_id": str(item.get("project_id", ""))[:8],
        "name": item.get("project_name", ""),
        "updated_at": item.get("updated_at", ""),
        "source_file": item.get("source_file", ""),
        "timeline_ops": item.get("timeline_ops", 0),
    }


def _conversation_items(state: ProjectState) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for message in state.session_log or []:
        role = str(message.get("role") or "")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            items.append({"role": role, "content": content})
    return items[-40:]


def serialize_state(state: ProjectState | None, provider_name: str, model_name: str) -> dict[str, Any]:
    projects = [_project_item(item) for item in ProjectState.list_projects()]
    if state is None:
        return {
            "provider": provider_name,
            "model": model_name,
            "project": None,
            "projects": projects,
        }
    meta = state.metadata or {}
    latest_export = _artifact(state, "latest_export")
    return {
        "provider": state.provider or provider_name,
        "model": state.model or model_name,
        "project": {
            "id": state.project_id,
            "short_id": state.project_id[:8],
            "name": state.project_name,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "source_files": state.source_files,
            "working_file": state.working_file,
            "output_dir": state.output_dir,
            "timeline": list(state.timeline or []),
            "redo_count": len(state.redo_stack or []),
            "session_count": len(state.session_log or []),
            "conversation": _conversation_items(state),
            "metadata": {
                "duration_sec": meta.get("duration_sec", 0),
                "width": meta.get("width", 0),
                "height": meta.get("height", 0),
                "fps": meta.get("fps", 0),
                "size_bytes": meta.get("size_bytes", 0),
            },
            "artifacts": {
                "source_url": str((state.artifacts or {}).get("source_url") or ""),
                "upload_filename": str((state.artifacts or {}).get("upload_filename") or ""),
                "latest_agent_trace": _artifact(state, "latest_agent_trace"),
                "latest_auto_shorts": _artifact(state, "latest_auto_shorts"),
                "latest_auto_broll": _artifact(state, "latest_auto_broll"),
                "latest_auto_visuals": _artifact(state, "latest_auto_visuals"),
                "latest_transcript": _artifact(state, "latest_transcript"),
                "latest_export": latest_export,
                "export_history": list((state.artifacts or {}).get("export_history") or [])[-20:],
            },
            "links": {
                "media_current": f"/api/projects/{state.project_id}/media/current",
                "download_current": f"/api/projects/{state.project_id}/download/current",
                "download_latest_export": f"/api/projects/{state.project_id}/download/latest-export" if latest_export else "",
            },
        },
        "projects": projects,
    }


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    return payload


def _load_source(
    source: str,
    *,
    current_state: ProjectState | None,
    provider_name: str,
    model_name: str,
    create_project: CreateProject,
    create_project_from_youtube: CreateProjectFromYoutube,
) -> tuple[ProjectState, str]:
    command = str(source or "").strip()
    if not command:
        raise ValueError("Enter a video path or YouTube URL.")

    load_request = parse_load_source_command(command)
    detected_path = detect_video_path(command)
    detected_url = extract_youtube_url(command)
    if load_request is not None:
        load_kind, load_target = load_request
    elif detected_path:
        load_kind, load_target = "path", detected_path
    elif detected_url:
        load_kind, load_target = "url", detected_url
    else:
        raise ValueError("Enter a valid local video path or YouTube URL.")

    if load_kind == "path":
        if current_state is not None and is_loaded_source(current_state, load_target):
            return current_state, format_loaded_state_message(current_state, already_loaded=True)
        state = find_project_for_source(load_target)
        if state is None:
            state = create_project(load_target, None, provider_name, model_name)
        return state, format_loaded_state_message(state, already_loaded=False)

    if current_state is not None and is_loaded_source_url(current_state, load_target):
        return current_state, format_loaded_state_message(current_state, already_loaded=True)
    state = find_project_for_source_url(load_target)
    if state is None:
        state = create_project_from_youtube(load_target, None, provider_name, model_name)
    return state, format_loaded_state_message(state, already_loaded=False)


@dataclass
class Job:
    job_id: str
    project_id: str
    events: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue)
    done: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None

    def emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        self.events.put(
            {
                "event": event,
                "data": data or {},
                "created_at": time.time(),
            }
        )


class WebApp:
    def __init__(
        self,
        *,
        provider: Any,
        initial_state: ProjectState | None,
        create_project: CreateProject,
        create_project_from_youtube: CreateProjectFromYoutube,
    ) -> None:
        self.provider = provider
        self.state = initial_state
        self.agent = VideoAgent(initial_state, provider) if initial_state is not None else None
        self.create_project = create_project
        self.create_project_from_youtube = create_project_from_youtube
        self.lock = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self.active_jobs_by_project: dict[str, str] = {}

    @property
    def provider_name(self) -> str:
        return self.state.provider if self.state is not None else config.PROVIDER

    @property
    def model_name(self) -> str:
        return self.provider.model_name

    def response_state(self, state: ProjectState | None = None) -> dict[str, Any]:
        return serialize_state(self.state if state is None else state, self.provider_name, self.model_name)

    def select_project(self, project_id: str) -> dict[str, Any]:
        with self.lock:
            self.state = ProjectState.load(project_id)
            self.agent = VideoAgent(self.state, self.provider)
            return self.response_state()

    def load_source(self, source: str) -> dict[str, Any]:
        with self.lock:
            loaded, message = _load_source(
                source,
                current_state=self.state,
                provider_name=config.PROVIDER,
                model_name=self.model_name,
                create_project=self.create_project,
                create_project_from_youtube=self.create_project_from_youtube,
            )
            self.state = loaded
            self.agent = VideoAgent(self.state, self.provider)
            payload = self.response_state()
            payload["message"] = message
            return payload

    def new_session(self) -> dict[str, Any]:
        with self.lock:
            if self.state is not None:
                active_job_id = self.active_jobs_by_project.get(self.state.project_id)
                active = self.jobs.get(active_job_id or "")
                if active is not None and not active.done.is_set():
                    raise JobConflictError("An agent job is already running for this project.")
            self.state = None
            self.agent = None
            return self.response_state()

    def create_uploaded_project(self, filename: str, source_path: Path) -> dict[str, Any]:
        safe_name = _safe_upload_name(filename)
        project_id = str(uuid.uuid4())
        working_dir = Path(config.AGENT_PROJECTS_DIR) / project_id
        output_dir = working_dir / "outputs"
        working_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        working_file = working_dir / f"source_{safe_name}"
        source_path.replace(working_file)
        metadata = probe_video(str(working_file))
        now = utc_now_iso()
        state = ProjectState(
            project_id=project_id,
            project_name=Path(safe_name).stem,
            created_at=now,
            updated_at=now,
            source_files=[str(working_file)],
            working_file=str(working_file),
            working_dir=str(working_dir),
            output_dir=str(output_dir),
            timeline=[],
            redo_stack=[],
            session_log=[],
            metadata=metadata,
            artifacts={"upload_filename": safe_name},
            provider=config.PROVIDER,
            model=self.model_name,
        )
        state.save()
        with self.lock:
            self.state = state
            self.agent = VideoAgent(self.state, self.provider)
            return self.response_state()

    def start_job(self, message: str) -> dict[str, Any]:
        command = str(message or "").strip()
        if not command:
            raise ValueError("Enter an instruction.")
        with self.lock:
            if self.state is None or self.agent is None:
                raise ValueError("Load a video before running the agent.")
            project_id = self.state.project_id
            active_job_id = self.active_jobs_by_project.get(project_id)
            if active_job_id:
                active = self.jobs.get(active_job_id)
                if active is not None and not active.done.is_set():
                    raise JobConflictError("An agent job is already running for this project.")
            job = Job(job_id=uuid.uuid4().hex, project_id=project_id)
            self.jobs[job.job_id] = job
            self.active_jobs_by_project[project_id] = job.job_id
            agent = self.agent
        thread = threading.Thread(target=self._run_job, args=(job, agent, command), daemon=True)
        thread.start()
        return {"job_id": job.job_id, "project_id": project_id}

    def _run_job(self, job: Job, agent: VideoAgent, command: str) -> None:
        job.status = "running"
        job.emit("started", {"job_id": job.job_id, "project_id": job.project_id, "message": command})

        def stream_callback(chunk: str) -> None:
            job.emit("assistant_delta", {"text": chunk})

        def trace_callback(event) -> None:
            job.emit("trace", event.to_dict())

        def tool_callback(phase: str, tool_name: str, ok: bool) -> None:
            job.emit(
                "tool_start" if phase == "start" else "tool_finish",
                {"tool_name": tool_name, "ok": bool(ok)},
            )

        try:
            response = agent.run(
                command,
                stream_callback=stream_callback,
                tool_callback=tool_callback,
                trace_callback=trace_callback,
            )
            state = agent.state
            job.status = "complete"
            job.result = {
                "message": response.message,
                "tools_called": response.tools_called,
                "suggestions": response.suggestions,
                "success": response.success,
            }
            with self.lock:
                if self.state is not None and self.state.project_id == job.project_id:
                    self.state = state
                    self.agent = agent
            state_payload = self.response_state(state)
            job.emit("state", state_payload)
            job.emit("result", {"response": job.result, "state": state_payload})
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
            with self.lock:
                if self.state is not None and self.state.project_id == job.project_id:
                    self.state = agent.state
                    self.agent = agent
            job.emit("error", {"message": str(exc), "state": self.response_state(agent.state)})
        finally:
            with self.lock:
                if self.active_jobs_by_project.get(job.project_id) == job.job_id:
                    self.active_jobs_by_project.pop(job.project_id, None)
            job.emit("done", {"status": job.status})
            job.done.set()

    def get_job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise FileNotFoundError(f"No job found for id {job_id!r}.")
        return job

    def project_file(self, project_id: str, kind: str) -> tuple[Path, ProjectState]:
        state = ProjectState.load(project_id)
        if kind in {"current", "download-current"}:
            candidate = Path(state.working_file)
        elif kind == "latest-export":
            latest = _artifact(state, "latest_export")
            if not latest or not latest.get("path"):
                raise FileNotFoundError("No latest export exists for this project.")
            candidate = Path(str(latest["path"]))
        else:
            raise FileNotFoundError("Unknown project file.")
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Project file does not exist: {candidate}")
        allowed_roots = [Path(state.working_dir).resolve(), Path(state.output_dir).resolve()]
        allowed_files = {Path(path).resolve() for path in state.source_files}
        if not any(candidate == root or candidate.is_relative_to(root) for root in allowed_roots):
            if candidate not in allowed_files:
                raise FileNotFoundError("Requested file is outside this project.")
        return candidate, state


def _send_sse(handler: BaseHTTPRequestHandler, job: Job) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("content-type", "text/event-stream; charset=utf-8")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("connection", "keep-alive")
    handler.end_headers()
    while True:
        try:
            item = job.events.get(timeout=0.5)
        except queue.Empty:
            if job.done.is_set() and job.events.empty():
                break
            continue
        payload = (
            f"event: {item['event']}\n"
            f"data: {json.dumps(item['data'])}\n\n"
        ).encode("utf-8")
        try:
            handler.wfile.write(payload)
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            break


def _content_disposition(path: Path, *, attachment: bool) -> str:
    disposition = "attachment" if attachment else "inline"
    filename = path.name.replace('"', "")
    return f'{disposition}; filename="{filename}"'


def _send_file(handler: BaseHTTPRequestHandler, path: Path, *, attachment: bool, allow_range: bool) -> None:
    file_size = path.stat().st_size
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    range_header = handler.headers.get("range") if allow_range else None
    start = 0
    end = file_size - 1
    status = HTTPStatus.OK
    if range_header:
        try:
            units, raw_range = range_header.split("=", 1)
            if units.strip().lower() != "bytes":
                raise ValueError
            raw_start, raw_end = raw_range.split("-", 1)
            start = int(raw_start) if raw_start else 0
            end = int(raw_end) if raw_end else file_size - 1
            if start < 0 or end < start or start >= file_size:
                raise ValueError
            end = min(end, file_size - 1)
            status = HTTPStatus.PARTIAL_CONTENT
        except ValueError:
            handler.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            handler.send_header("content-range", f"bytes */{file_size}")
            handler.end_headers()
            return
    length = end - start + 1
    handler.send_response(status)
    handler.send_header("content-type", content_type)
    handler.send_header("content-length", str(length))
    handler.send_header("accept-ranges", "bytes")
    handler.send_header("content-disposition", _content_disposition(path, attachment=attachment))
    if status == HTTPStatus.PARTIAL_CONTENT:
        handler.send_header("content-range", f"bytes {start}-{end}/{file_size}")
    handler.end_headers()
    with path.open("rb") as file:
        file.seek(start)
        remaining = length
        while remaining > 0:
            chunk = file.read(min(UPLOAD_CHUNK_SIZE, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)


def _write_upload_to_temp(handler: BaseHTTPRequestHandler, filename: str) -> Path:
    content_length = int(handler.headers.get("content-length") or "0")
    if content_length <= 0:
        raise ValueError("Upload is empty.")
    if content_length > max_upload_bytes():
        raise ValueError("Upload exceeds Vex web upload limit.")
    upload_dir = Path(config.AGENT_PROJECTS_DIR) / ".uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"{uuid.uuid4().hex}.upload"
    remaining = content_length
    with temp_path.open("wb") as file:
        while remaining > 0:
            chunk = handler.rfile.read(min(UPLOAD_CHUNK_SIZE, remaining))
            if not chunk:
                break
            file.write(chunk)
            remaining -= len(chunk)
    if remaining:
        temp_path.unlink(missing_ok=True)
        raise ValueError("Upload ended before all bytes were received.")
    safe_name = _safe_upload_name(filename)
    final_path = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    temp_path.replace(final_path)
    return final_path


def make_handler(web_app: WebApp):
    class VexWebHandler(BaseHTTPRequestHandler):
        server_version = "VexWeb/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: HTTPStatus, payload: Any) -> None:
            self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json(status, {"ok": False, "error": message})

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path in {"/", "/index.html"}:
                    self._send(HTTPStatus.OK, load_index_html().encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path == "/api/state":
                    self._send_json(HTTPStatus.OK, {"ok": True, **web_app.response_state()})
                    return
                if path.startswith("/api/jobs/") and path.endswith("/events"):
                    job_id = path.removeprefix("/api/jobs/").removesuffix("/events").strip("/")
                    _send_sse(self, web_app.get_job(job_id))
                    return
                if path.startswith("/api/projects/"):
                    parts = [part for part in path.split("/") if part]
                    if len(parts) == 5 and parts[0] == "api" and parts[1] == "projects":
                        project_id = parts[2]
                        action = parts[3]
                        kind = parts[4]
                        if action == "media" and kind == "current":
                            file_path, _state = web_app.project_file(project_id, "current")
                            _send_file(self, file_path, attachment=False, allow_range=True)
                            return
                        if action == "download" and kind == "current":
                            file_path, _state = web_app.project_file(project_id, "download-current")
                            _send_file(self, file_path, attachment=True, allow_range=False)
                            return
                        if action == "download" and kind == "latest-export":
                            file_path, _state = web_app.project_file(project_id, "latest-export")
                            _send_file(self, file_path, attachment=True, allow_range=False)
                            return
                self._send_error(HTTPStatus.NOT_FOUND, "Not found.")
            except FileNotFoundError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:  # noqa: BLE001
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/api/upload":
                    filename = unquote(str(self.headers.get("x-vex-filename") or ""))
                    temp_path = _write_upload_to_temp(self, filename)
                    self._send_json(HTTPStatus.OK, {"ok": True, **web_app.create_uploaded_project(filename, temp_path)})
                    return
                payload = _read_json_body(self)
                if path == "/api/select":
                    project_id = str(payload.get("project_id") or "").strip()
                    if not project_id:
                        raise ValueError("Missing project id.")
                    self._send_json(HTTPStatus.OK, {"ok": True, **web_app.select_project(project_id)})
                    return
                if path == "/api/load":
                    source = str(payload.get("source") or "").strip()
                    self._send_json(HTTPStatus.OK, {"ok": True, **web_app.load_source(source)})
                    return
                if path == "/api/new-session":
                    self._send_json(HTTPStatus.OK, {"ok": True, **web_app.new_session()})
                    return
                if path == "/api/jobs":
                    message = str(payload.get("message") or "").strip()
                    self._send_json(HTTPStatus.ACCEPTED, {"ok": True, **web_app.start_job(message)})
                    return
                self._send_error(HTTPStatus.NOT_FOUND, "Not found.")
            except WebAppError as exc:
                self._send_error(exc.status, str(exc))
            except FileNotFoundError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
            except (AgentLoopError, ValueError, json.JSONDecodeError) as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:  # noqa: BLE001
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unexpected server error: {exc}")

    return VexWebHandler


def run_web_app(
    *,
    provider: Any,
    state: ProjectState | None,
    create_project: CreateProject,
    create_project_from_youtube: CreateProjectFromYoutube,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    web_state = WebApp(
        provider=provider,
        initial_state=state,
        create_project=create_project,
        create_project_from_youtube=create_project_from_youtube,
    )
    server = ThreadingHTTPServer((host, port), make_handler(web_state))
    url = f"http://{host}:{port}"
    if open_browser:
        webbrowser.open(url)
    print(f"Vex web running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Vex web.")
    finally:
        server.server_close()
