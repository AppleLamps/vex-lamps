from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path

from google import genai
from google.genai import types

import config
from engine import probe_video
from state import ProjectState
from tools.transcript_utils import (
    build_sentence_segments,
    clean_transcript_text,
    format_srt_timestamp,
    write_json,
)


def _transcript_paths(state: ProjectState) -> tuple[Path, Path, Path, Path, Path]:
    return (
        Path(state.working_dir) / "transcript.txt",
        Path(state.working_dir) / "transcript.srt",
        Path(state.working_dir) / "transcript.segments.json",
        Path(state.working_dir) / "transcript.words.json",
        Path(state.working_dir) / "transcript.sentences.json",
    )


def _normalize_whisper_segments(raw_segments: list[dict]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    normalized_segments: list[dict[str, object]] = []
    normalized_words: list[dict[str, object]] = []
    word_index = 1
    for segment_index, segment in enumerate(raw_segments, start=1):
        start_sec = float(segment.get("start") or 0.0)
        end_sec = float(segment.get("end") or 0.0)
        text = clean_transcript_text(str(segment.get("text") or ""))
        if end_sec <= start_sec or not text:
            continue
        segment_words: list[dict[str, object]] = []
        for raw_word in segment.get("words") or []:
            word_text = clean_transcript_text(str(raw_word.get("word") or raw_word.get("text") or ""))
            word_start = raw_word.get("start")
            word_end = raw_word.get("end")
            if word_start is None or word_end is None or not word_text:
                continue
            if float(word_end) <= float(word_start):
                continue
            payload = {
                "index": word_index,
                "start": round(float(word_start), 3),
                "end": round(float(word_end), 3),
                "text": word_text,
                "confidence": round(float(raw_word.get("probability", 0.0)), 4)
                if raw_word.get("probability") is not None
                else None,
            }
            segment_words.append(payload)
            normalized_words.append(payload)
            word_index += 1
        normalized_segments.append(
            {
                "index": segment_index,
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "text": text,
                "word_start_index": int(segment_words[0]["index"]) if segment_words else None,
                "word_end_index": int(segment_words[-1]["index"]) if segment_words else None,
                "words": segment_words,
            }
        )
    return normalized_segments, normalized_words


def _write_transcript_artifacts(
    state: ProjectState,
    *,
    transcript_text: str,
    segments: list[dict[str, object]],
    words: list[dict[str, object]],
    source: str,
) -> dict:
    txt_path, srt_path, segment_json_path, words_json_path, sentences_json_path = _transcript_paths(state)
    transcript_text = clean_transcript_text(transcript_text)
    txt_path.write_text(transcript_text + "\n", encoding="utf-8")
    sentences = build_sentence_segments(words, fallback_segments=segments)
    srt_lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        srt_lines.extend(
            [
                str(index),
                f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(segment['end'])}",
                str(segment["text"]).strip(),
                "",
            ]
        )
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    write_json(segment_json_path, segments)
    write_json(words_json_path, words)
    write_json(sentences_json_path, sentences)
    state.artifacts["latest_transcript"] = {
        "txt_path": str(txt_path),
        "srt_path": str(srt_path),
        "segments_path": str(segment_json_path),
        "words_path": str(words_json_path),
        "sentences_path": str(sentences_json_path),
        "segment_count": len(segments),
        "word_count": len(words),
        "sentence_count": len(sentences),
        "source": source,
    }
    history = list(state.artifacts.get("transcript_history") or [])
    history.append(state.artifacts["latest_transcript"])
    state.artifacts["transcript_history"] = history[-10:]
    state.save()
    preview = "\n".join(
        f"{format_srt_timestamp(segment['start'])} {segment['text'].strip()}" for segment in segments[:10]
    )
    return {
        "success": True,
        "message": (
            f"Transcript saved to {txt_path}, {srt_path}, {segment_json_path.name}, {words_json_path.name}, "
            f"and {sentences_json_path.name} using {source}.\n{preview}"
        ),
        "suggestion": "[SUGGESTION]: Captions are ready. I can help turn them into timed overlays - reply 'yes' to apply or continue.",
        "updated_state": state,
        "tool_name": "transcribe_video",
    }


def _extract_json_payload(raw_text: str) -> object:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start_candidates = [index for index in [cleaned.find("{"), cleaned.find("[")] if index != -1]
    if not start_candidates:
        raise ValueError("Gemini did not return JSON.")
    start = min(start_candidates)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end < start:
        raise ValueError("Gemini returned incomplete JSON.")
    return json.loads(cleaned[start : end + 1])


def _normalize_gemini_segments(payload: object, duration_sec: float) -> tuple[str, list[dict[str, object]]]:
    if isinstance(payload, dict):
        transcript_text = clean_transcript_text(str(payload.get("transcript") or ""))
        raw_segments = payload.get("segments")
    else:
        transcript_text = ""
        raw_segments = payload
    if not isinstance(raw_segments, list):
        raw_segments = []
    segments: list[dict[str, object]] = []
    for index, raw_segment in enumerate(raw_segments, start=1):
        if not isinstance(raw_segment, dict):
            continue
        text = clean_transcript_text(str(raw_segment.get("text") or ""))
        if not text:
            continue
        try:
            start_sec = max(0.0, float(raw_segment.get("start") or 0.0))
            end_sec = min(duration_sec, float(raw_segment.get("end") or duration_sec))
        except (TypeError, ValueError):
            continue
        if end_sec <= start_sec:
            continue
        segments.append(
            {
                "index": index,
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "text": text,
                "word_start_index": None,
                "word_end_index": None,
                "words": [],
            }
        )
    if not transcript_text:
        transcript_text = clean_transcript_text(" ".join(str(segment["text"]) for segment in segments))
    if transcript_text and not segments:
        segments = [
            {
                "index": 1,
                "start": 0.0,
                "end": round(max(duration_sec, 0.1), 3),
                "text": transcript_text,
                "word_start_index": None,
                "word_end_index": None,
                "words": [],
            }
        ]
    return transcript_text, segments


def _gemini_model_for_transcription(state: ProjectState) -> str | None:
    candidates = [state.model, config.GEMINI_MODEL]
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized.lower().startswith("gemini"):
            return normalized
    return None


def _transcribe_with_gemini(state: ProjectState) -> dict:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    model_name = _gemini_model_for_transcription(state)
    if not model_name:
        raise RuntimeError("The configured Gemini model name does not support video transcription.")
    video_path = Path(state.working_file)
    metadata = state.metadata or probe_video(str(video_path))
    duration_sec = float(metadata.get("duration_sec") or 0.0)
    max_duration = float(config.GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC)
    if duration_sec > max_duration:
        raise RuntimeError(
            f"Gemini inline transcription is limited to {max_duration:g}s here. "
            "Use Whisper or raise GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC for longer clips."
        )
    max_bytes = int(config.GEMINI_TRANSCRIPT_MAX_INLINE_MB) * 1024 * 1024
    size_bytes = video_path.stat().st_size
    if size_bytes > max_bytes:
        raise RuntimeError(
            f"Gemini inline transcription is limited to {config.GEMINI_TRANSCRIPT_MAX_INLINE_MB}MB here. "
            "Use Whisper or raise GEMINI_TRANSCRIPT_MAX_INLINE_MB for larger clips."
        )
    mime_type = mimetypes.guess_type(str(video_path))[0] or "video/mp4"
    prompt = (
        "Transcribe the spoken audio in this video. Return only JSON with this shape: "
        "{\"transcript\":\"full plain transcript\",\"segments\":[{\"start\":0.0,\"end\":1.2,\"text\":\"caption text\"}]}. "
        "Use seconds for start and end. Keep segments short enough for subtitles, usually one sentence or less. "
        "If no speech is present, return an empty transcript and an empty segments array."
    )
    client = genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=config.google_genai_http_options(),
    )
    response = client.models.generate_content(
        model=model_name,
        contents=types.Content(
            parts=[
                types.Part(
                    inline_data=types.Blob(
                        data=video_path.read_bytes(),
                        mime_type=mime_type,
                    )
                ),
                types.Part(text=prompt),
            ]
        ),
        config=config.build_gemini_generation_config(
            "You produce exact transcript JSON for local video editing tools.",
            model_name=model_name,
        ),
    )
    raw_text = getattr(response, "text", "") or ""
    transcript_text, segments = _normalize_gemini_segments(_extract_json_payload(raw_text), duration_sec)
    return _write_transcript_artifacts(
        state,
        transcript_text=transcript_text,
        segments=segments,
        words=[],
        source=f"Gemini video ({model_name})",
    )


def _transcribe_with_whisper(state: ProjectState) -> dict:
    try:
        import whisper  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Whisper is not installed. Install it with `pip install openai-whisper` to enable local fallback transcription.") from exc

    model = whisper.load_model(config.WHISPER_MODEL)
    try:
        result = model.transcribe(state.working_file, word_timestamps=True, verbose=False)
    except TypeError:
        result = model.transcribe(state.working_file)
    transcript_text = clean_transcript_text(str(result.get("text") or ""))
    raw_segments = result.get("segments", [])
    segments, words = _normalize_whisper_segments(raw_segments if isinstance(raw_segments, list) else [])
    return _write_transcript_artifacts(
        state,
        transcript_text=transcript_text,
        segments=segments,
        words=words,
        source=f"Whisper {config.WHISPER_MODEL}",
    )


def execute(params: dict, state: ProjectState) -> dict:
    engine = str(params.get("engine") or "auto").strip().lower()
    errors: list[str] = []
    engines = ["gemini", "whisper"] if engine == "auto" else [engine]
    for selected in engines:
        try:
            if selected == "gemini":
                return _transcribe_with_gemini(state)
            if selected == "whisper":
                return _transcribe_with_whisper(state)
            errors.append(f"Unsupported transcription engine: {selected}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{selected}: {exc}")
    return {
        "success": False,
        "message": "Transcription failed. " + " | ".join(errors),
        "suggestion": None,
        "updated_state": state,
        "tool_name": "transcribe_video",
    }
