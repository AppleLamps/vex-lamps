from __future__ import annotations

import re
from pathlib import Path

from engine import parse_timestamp


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def parse_srt(path: Path) -> list[dict[str, float | str]]:
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    blocks = re.split(r"\r?\n\r?\n", raw_text)
    segments: list[dict[str, float | str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        timestamp_line = next((line for line in lines if "-->" in line), "")
        if not timestamp_line:
            continue
        start_raw, end_raw = [part.strip().replace(",", ".") for part in timestamp_line.split("-->", 1)]
        start_sec = parse_timestamp(start_raw)
        end_sec = parse_timestamp(end_raw)
        text_start = lines.index(timestamp_line) + 1
        text = " ".join(lines[text_start:]).strip()
        if text and end_sec > start_sec:
            segments.append({"start": start_sec, "end": end_sec, "text": text})
    return segments


def write_srt_segments(path: Path, segments: list[dict[str, float | str]]) -> None:
    srt_lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        srt_lines.extend(
            [
                str(index),
                (
                    f"{format_srt_timestamp(float(segment['start']))} --> "
                    f"{format_srt_timestamp(float(segment['end']))}"
                ),
                str(segment["text"]).strip(),
                "",
            ]
        )
    path.write_text("\n".join(srt_lines), encoding="utf-8")
