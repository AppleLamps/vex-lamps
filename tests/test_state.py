from __future__ import annotations

from pathlib import Path

import config
from state import ProjectState


def _project(tmp_path: Path) -> ProjectState:
    working_dir = tmp_path / "projects" / "demo"
    return ProjectState(
        project_id="abc123",
        project_name="Demo",
        created_at="2026-05-08T00:00:00+00:00",
        updated_at="2026-05-08T00:00:00+00:00",
        source_files=[str(tmp_path / "source.mp4")],
        working_file=str(working_dir / "working.mp4"),
        working_dir=str(working_dir),
        output_dir=str(working_dir / "exports"),
        timeline=[{"op": "load_source"}],
        metadata={"provider": "test"},
    )


def test_project_state_save_load_and_list_projects(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "AGENT_PROJECTS_DIR", str(tmp_path / "projects"))
    state = _project(tmp_path)

    state.save()

    loaded = ProjectState.load("abc123")
    assert loaded.project_id == "abc123"
    assert loaded.project_name == "Demo"
    assert loaded.timeline == [{"op": "load_source"}]
    projects = ProjectState.list_projects()
    assert len(projects) == 1
    assert projects[0]["project_id"] == "abc123"
    assert projects[0]["timeline_ops"] == 1


def test_project_state_load_ignores_invalid_json(tmp_path, monkeypatch) -> None:
    base = tmp_path / "projects"
    monkeypatch.setattr(config, "AGENT_PROJECTS_DIR", str(base))
    invalid_dir = base / "invalid"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "abc123.json").write_text("{bad", encoding="utf-8")

    state = _project(tmp_path)
    state.save()

    loaded = ProjectState.load("abc123")
    assert loaded.project_id == "abc123"
    assert ProjectState.list_projects()[0]["project_name"] == "Demo"
