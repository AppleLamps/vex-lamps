from __future__ import annotations

import http.client
import json
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import config
import web_app
from agent import AgentResponse
from state import ProjectState


class FakeProvider:
    model_name = "test-model"


class FastAgent:
    def __init__(self, state: ProjectState, provider: FakeProvider) -> None:
        self.state = state
        self.provider = provider

    def run(self, command: str, *, stream_callback, tool_callback, trace_callback) -> AgentResponse:
        stream_callback("Done")
        self.state.session_log.append({"role": "user", "content": command})
        self.state.session_log.append({"role": "assistant", "content": "Done"})
        self.state.save()
        return AgentResponse(message="Done", tools_called=[], suggestions=[], success=True)


class SlowAgent(FastAgent):
    release = threading.Event()

    def run(self, command: str, *, stream_callback, tool_callback, trace_callback) -> AgentResponse:
        self.release.wait(timeout=5)
        return super().run(
            command,
            stream_callback=stream_callback,
            tool_callback=tool_callback,
            trace_callback=trace_callback,
        )


@pytest.fixture
def web_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "AGENT_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(
        web_app,
        "probe_video",
        lambda _path: {"duration_sec": 1.0, "width": 16, "height": 16, "fps": 24.0},
    )
    monkeypatch.setattr(web_app, "VideoAgent", FastAgent)

    app = web_app.WebApp(
        provider=FakeProvider(),
        initial_state=None,
        create_project=lambda *_args: None,
        create_project_from_youtube=lambda *_args: None,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_app.make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield app, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    server: ThreadingHTTPServer,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(server.server_address[0], server.server_address[1], timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    headers_out = {key.lower(): value for key, value in response.getheaders()}
    conn.close()
    return response.status, headers_out, data


def _json(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))


def _read_sse_until_done(server: ThreadingHTTPServer, path: str) -> tuple[int, dict[str, str], str]:
    conn = http.client.HTTPConnection(server.server_address[0], server.server_address[1], timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    lines: list[str] = []
    while True:
        line = response.fp.readline().decode("utf-8")
        if not line:
            break
        lines.append(line)
        if line.strip() == "event: done":
            break
    headers_out = {key.lower(): value for key, value in response.getheaders()}
    conn.close()
    return response.status, headers_out, "".join(lines)


def _upload(server: ThreadingHTTPServer, filename: str = "clip.mp4") -> dict:
    body = b"fake-video-bytes"
    status, _headers, data = _request(
        server,
        "POST",
        "/api/upload",
        body,
        {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
            "X-Vex-Filename": filename,
        },
    )
    assert status == HTTPStatus.OK
    return _json(data)


def test_upload_creates_project_workspace(web_server) -> None:
    _app, server = web_server

    payload = _upload(server, "sample.mp4")

    project = payload["project"]
    state = ProjectState.load(project["id"])
    working_file = Path(state.working_file)
    assert state.metadata["duration_sec"] == 1.0
    assert state.output_dir == str(Path(state.working_dir) / "outputs")
    assert working_file.name == "source_sample.mp4"
    assert working_file.read_bytes() == b"fake-video-bytes"


def test_upload_rejects_unsupported_extension(web_server) -> None:
    _app, server = web_server

    status, _headers, data = _request(
        server,
        "POST",
        "/api/upload",
        b"bad",
        {
            "Content-Type": "application/octet-stream",
            "Content-Length": "3",
            "X-Vex-Filename": "notes.txt",
        },
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert "Unsupported video extension" in _json(data)["error"]


def test_new_session_clears_active_project(web_server) -> None:
    _app, server = web_server
    _upload(server)

    status, _headers, data = _request(
        server,
        "POST",
        "/api/new-session",
        b"{}",
        {"Content-Type": "application/json", "Content-Length": "2"},
    )

    payload = _json(data)
    assert status == HTTPStatus.OK
    assert payload["project"] is None
    assert len(payload["projects"]) == 1


def test_media_and_download_endpoints_serve_project_files_only(web_server, tmp_path: Path) -> None:
    _app, server = web_server
    payload = _upload(server)
    project_id = payload["project"]["id"]

    status, headers, data = _request(server, "GET", f"/api/projects/{project_id}/media/current")
    assert status == HTTPStatus.OK
    assert headers["content-type"] == "video/mp4"
    assert data == b"fake-video-bytes"

    status, headers, data = _request(server, "GET", f"/api/projects/{project_id}/download/current")
    assert status == HTTPStatus.OK
    assert "attachment" in headers["content-disposition"]
    assert data == b"fake-video-bytes"

    state = ProjectState.load(project_id)
    exported = Path(state.output_dir) / "exported.mp4"
    exported.write_bytes(b"exported-video")
    state.artifacts["latest_export"] = {"path": str(exported)}
    state.save()

    status, headers, data = _request(
        server,
        "GET",
        f"/api/projects/{project_id}/download/latest-export",
    )
    assert status == HTTPStatus.OK
    assert "attachment" in headers["content-disposition"]
    assert data == b"exported-video"

    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not-project-owned")
    state.artifacts["latest_export"] = {"path": str(outside)}
    state.save()

    status, _headers, data = _request(
        server,
        "GET",
        f"/api/projects/{project_id}/download/latest-export",
    )
    assert status == HTTPStatus.NOT_FOUND
    assert "outside this project" in _json(data)["error"]


def test_jobs_return_immediately_and_sse_emits_result(web_server) -> None:
    _app, server = web_server
    _upload(server)

    body = json.dumps({"message": "trim the first second"}).encode("utf-8")
    status, _headers, data = _request(
        server,
        "POST",
        "/api/jobs",
        body,
        {"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    assert status == HTTPStatus.ACCEPTED
    job_id = _json(data)["job_id"]

    status, headers, events = _read_sse_until_done(server, f"/api/jobs/{job_id}/events")
    assert status == HTTPStatus.OK
    assert headers["content-type"].startswith("text/event-stream")
    assert "event: started" in events
    assert "event: result" in events
    assert "event: done" in events


def test_concurrent_jobs_on_same_project_return_conflict(web_server, monkeypatch) -> None:
    app, server = web_server
    _upload(server)
    SlowAgent.release.clear()
    monkeypatch.setattr(web_app, "VideoAgent", SlowAgent)
    app.agent = SlowAgent(app.state, app.provider)

    body = json.dumps({"message": "make a rough cut"}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    first_status, _first_headers, _first_data = _request(server, "POST", "/api/jobs", body, headers)
    second_status, _second_headers, second_data = _request(server, "POST", "/api/jobs", body, headers)
    SlowAgent.release.set()

    assert first_status == HTTPStatus.ACCEPTED
    assert second_status == HTTPStatus.CONFLICT
    assert "already running" in _json(second_data)["error"]
