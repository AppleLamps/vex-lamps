from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ProjectState:
    project_id: str
    project_name: str
    created_at: str
    updated_at: str
    source_files: list[str]
    working_file: str
    working_dir: str
    output_dir: str
    timeline: list[dict[str, Any]] = field(default_factory=list)
    redo_stack: list[dict[str, Any]] = field(default_factory=list)
    session_log: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    provider: str = "gemini"
    model: str = ""

    @property
    def state_path(self) -> Path:
        return Path(self.working_dir) / f"{self.project_id}.json"

    def save(self) -> None:
        self.updated_at = utc_now_iso()
        Path(self.working_dir).mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectState":
        valid_fields = {field_.name for field_ in fields(cls)}
        filtered = {key: value for key, value in payload.items() if key in valid_fields}
        return cls(**filtered)

    @classmethod
    def _coerce_project_payload(cls, payload: object) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        required = {
            "project_id",
            "project_name",
            "created_at",
            "updated_at",
            "source_files",
            "working_file",
            "working_dir",
            "output_dir",
        }
        if not required.issubset(payload.keys()):
            return None
        if not isinstance(payload.get("project_id"), str) or not payload.get("project_id"):
            return None
        if not isinstance(payload.get("project_name"), str):
            return None
        if not isinstance(payload.get("source_files"), list):
            return None
        if not isinstance(payload.get("working_file"), str):
            return None
        if not isinstance(payload.get("working_dir"), str):
            return None
        if not isinstance(payload.get("output_dir"), str):
            return None
        return payload

    @classmethod
    def _load_project_payload(cls, path: Path) -> dict[str, Any] | None:
        try:
            raw_payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        payload = cls._coerce_project_payload(raw_payload)
        if payload is None:
            return None
        expected_name = f"{payload['project_id']}.json"
        if path.name != expected_name:
            return None
        return payload

    @classmethod
    def load(cls, project_id: str) -> "ProjectState":
        base = Path(config.AGENT_PROJECTS_DIR)
        candidates = list(base.glob(f"*/{project_id}.json"))
        if not candidates:
            candidates = list(base.glob(f"*/{project_id}*.json"))
        if not candidates:
            raise FileNotFoundError(f"No project found for id {project_id!r}.")
        if len(candidates) > 1:
            def sort_key(path: Path) -> str:
                payload = cls._load_project_payload(path)
                return str(payload.get("updated_at", "")) if payload else ""

            candidates.sort(key=sort_key, reverse=True)
            warnings.warn(
                f"Multiple projects matched partial id {project_id!r}; using the most recently updated match.",
                stacklevel=2,
            )
        payload = cls._load_project_payload(candidates[0])
        if payload is None:
            raise FileNotFoundError(f"Found a matching file for project id {project_id!r}, but it is not a valid project state.")
        return cls.from_dict(payload)

    @classmethod
    def list_projects(cls) -> list[dict[str, Any]]:
        base = Path(config.AGENT_PROJECTS_DIR)
        base.mkdir(parents=True, exist_ok=True)
        items: list[dict[str, Any]] = []
        for path in base.glob("*/*.json"):
            payload = cls._load_project_payload(path)
            if payload is None:
                continue
            items.append(
                {
                    "project_id": payload.get("project_id", ""),
                    "project_name": payload.get("project_name", ""),
                    "created_at": payload.get("created_at", ""),
                    "updated_at": payload.get("updated_at", ""),
                    "source_file": (payload.get("source_files") or [""])[0],
                    "timeline_ops": len(payload.get("timeline") or []),
                    "working_dir": payload.get("working_dir", ""),
                }
            )
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items

    def apply_operation(self, op: dict[str, Any]) -> None:
        self.timeline.append(op)
        self.redo_stack.clear()
        self.updated_at = utc_now_iso()
        self.save()

    def undo(self) -> dict[str, Any] | None:
        if not self.timeline:
            return None
        op = self.timeline.pop()
        self.redo_stack.append(op)
        self.updated_at = utc_now_iso()
        self.save()
        return op

    def redo(self) -> dict[str, Any] | None:
        if not self.redo_stack:
            return None
        op = self.redo_stack.pop()
        self.timeline.append(op)
        self.updated_at = utc_now_iso()
        self.save()
        return op

    def get_summary(self) -> str:
        meta = self.metadata or {}
        lines = [
            f"Project: {self.project_name}",
            f"Project ID: {self.project_id}",
            f"Created: {self.created_at}",
            f"Updated: {self.updated_at}",
            f"Provider: {self.provider} / {self.model}",
            f"Working file: {self.working_file}",
            f"Output dir: {self.output_dir}",
            f"Source files: {', '.join(self.source_files) if self.source_files else 'none'}",
            (
                "Metadata: "
                f"{meta.get('duration_sec', 'unknown')}s, "
                f"{meta.get('width', '?')}x{meta.get('height', '?')}, "
                f"{meta.get('fps', '?')}fps"
            ),
            f"Timeline operations: {len(self.timeline)}",
            f"Redo available: {len(self.redo_stack)}",
        ]
        source_url = str((self.artifacts or {}).get("source_url") or "").strip()
        if source_url:
            lines.append(f"Source URL: {source_url}")
        latest_auto_shorts = (self.artifacts or {}).get("latest_auto_shorts")
        if latest_auto_shorts:
            lines.append(
                "Latest auto shorts: "
                f"{latest_auto_shorts.get('count', 0)} clips @ {latest_auto_shorts.get('manifest_path', 'unknown')}"
            )
        latest_auto_broll = (self.artifacts or {}).get("latest_auto_broll")
        if latest_auto_broll:
            lines.append(
                "Latest auto b-roll: "
                f"{latest_auto_broll.get('count', 0)} inserts @ {latest_auto_broll.get('manifest_path', 'unknown')}"
            )
        latest_transcript = (self.artifacts or {}).get("latest_transcript")
        if latest_transcript:
            lines.append(
                "Latest transcript: "
                f"{latest_transcript.get('segment_count', 0)} segments / "
                f"{latest_transcript.get('word_count', 0)} words @ {latest_transcript.get('srt_path', 'unknown')}"
            )
        latest_auto_visuals = (self.artifacts or {}).get("latest_auto_visuals")
        if latest_auto_visuals:
            lines.append(
                "Latest auto visuals: "
                f"{latest_auto_visuals.get('count', 0)} inserts "
                f"({latest_auto_visuals.get('renderer', 'auto')} / {latest_auto_visuals.get('style_pack', 'auto')}) "
                f"@ {latest_auto_visuals.get('manifest_path', 'unknown')}"
            )
        latest_agent_trace = (self.artifacts or {}).get("latest_agent_trace")
        if latest_agent_trace:
            lines.append(
                "Latest agent trace: "
                f"{len(latest_agent_trace.get('events') or [])} steps @ {latest_agent_trace.get('created_at', 'unknown')}"
            )
        if self.timeline:
            lines.append("Timeline:")
            for index, op in enumerate(self.timeline, start=1):
                lines.append(
                    f"  {index}. {op['op']} - {op.get('description', '')} @ {op.get('timestamp', '')}"
                )
        return "\n".join(lines)
