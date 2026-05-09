from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from google.genai import types

PROVIDER = "gemini"
GEMINI_API_KEY = None
GEMINI_MODEL = "gemma-4-31b-it"
ANTHROPIC_API_KEY = None
CLAUDE_MODEL = "claude-sonnet-4-5"
PEXELS_API_KEY = None
AGENT_PROJECTS_DIR = os.path.expanduser("~/.video-agent/projects/")
FFMPEG_PATH = "ffmpeg"
BLENDER_PATH = "blender"
WHISPER_MODEL = "base"
GEMINI_TRANSCRIPT_MAX_INLINE_MB = 100
GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC = 90
VERSION = "1.0.0"
GENAI_TIMEOUT_SEC = 90
ANTHROPIC_TIMEOUT_SEC = 90.0
MANIM_PREVIEW_TIMEOUT_SEC = 75
MANIM_FINAL_TIMEOUT_SEC = 240
FFMPEG_COMMAND_TIMEOUT_SEC = 900
FFMPEG_EXPORT_TIMEOUT_SEC = 3600
BLENDER_RENDER_TIMEOUT_SEC = 600
LLM_REQUEST_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY_SEC = 1.5


@dataclass(frozen=True)
class Settings:
    provider: str = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemma-4-31b-it"
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-5"
    pexels_api_key: str | None = None
    agent_projects_dir: str = os.path.expanduser("~/.video-agent/projects/")
    ffmpeg_path: str = "ffmpeg"
    blender_path: str = "blender"
    whisper_model: str = "base"
    gemini_transcript_max_inline_mb: int = 100
    gemini_transcript_max_inline_duration_sec: int = 90
    genai_timeout_sec: int = 90
    anthropic_timeout_sec: float = 90.0
    manim_preview_timeout_sec: int = 75
    manim_final_timeout_sec: int = 240
    ffmpeg_command_timeout_sec: int = 900
    ffmpeg_export_timeout_sec: int = 3600
    blender_render_timeout_sec: int = 600
    llm_request_max_retries: int = 3
    llm_retry_base_delay_sec: float = 1.5


def load_settings_from_env() -> Settings:
    load_dotenv(override=True)
    manim_preview_timeout = max(30, int(os.getenv("MANIM_PREVIEW_TIMEOUT_SEC", "75")))
    return Settings(
        provider=os.getenv("PROVIDER", "gemini").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemma-4-31b-it"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
        pexels_api_key=os.getenv("PEXELS_API_KEY"),
        agent_projects_dir=os.path.expanduser(os.getenv("AGENT_PROJECTS_DIR", "~/.video-agent/projects/")),
        ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
        blender_path=os.getenv("BLENDER_PATH", "blender"),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        gemini_transcript_max_inline_mb=max(1, int(os.getenv("GEMINI_TRANSCRIPT_MAX_INLINE_MB", "100"))),
        gemini_transcript_max_inline_duration_sec=max(
            1,
            int(os.getenv("GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC", "90")),
        ),
        genai_timeout_sec=max(15, int(os.getenv("GENAI_TIMEOUT_SEC", "90"))),
        anthropic_timeout_sec=max(15.0, float(os.getenv("ANTHROPIC_TIMEOUT_SEC", "90"))),
        manim_preview_timeout_sec=manim_preview_timeout,
        manim_final_timeout_sec=max(manim_preview_timeout, int(os.getenv("MANIM_FINAL_TIMEOUT_SEC", "240"))),
        ffmpeg_command_timeout_sec=max(1, int(os.getenv("FFMPEG_COMMAND_TIMEOUT_SEC", "900"))),
        ffmpeg_export_timeout_sec=max(1, int(os.getenv("FFMPEG_EXPORT_TIMEOUT_SEC", "3600"))),
        blender_render_timeout_sec=max(1, int(os.getenv("BLENDER_RENDER_TIMEOUT_SEC", "600"))),
        llm_request_max_retries=max(1, int(os.getenv("LLM_REQUEST_MAX_RETRIES", "3"))),
        llm_retry_base_delay_sec=max(0.5, float(os.getenv("LLM_RETRY_BASE_DELAY_SEC", "1.5"))),
    )


def gemini_supports_thinking_config(model_name: str | None = None) -> bool:
    normalized = (model_name or GEMINI_MODEL or "").strip().lower()
    return normalized.startswith("gemini")


def build_gemini_generation_config(
    system_prompt: str,
    *,
    model_name: str | None = None,
    tools: list[types.Tool] | None = None,
) -> types.GenerateContentConfig:
    automatic_function_calling = (
        types.AutomaticFunctionCallingConfig(disable=True)
        if tools
        else None
    )
    thinking_config = None
    if gemini_supports_thinking_config(model_name):
        thinking_config = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=cast(Any, tools or None),
        automatic_function_calling=automatic_function_calling,
        thinking_config=thinking_config,
    )


def google_genai_http_options() -> types.HttpOptions:
    return types.HttpOptions(timeout=GENAI_TIMEOUT_SEC * 1000)


def configure_runtime_logging() -> None:
    noisy_loggers = (
        "google",
        "google.genai",
        "google.genai.models",
        "google.genai._api_client",
        "google_genai",
        "google_genai.models",
        "google_genai._api_client",
        "httpx",
        "httpcore",
        "urllib3",
    )
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _print_and_exit(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _ffmpeg_install_instructions() -> str:
    return (
        "FFmpeg was not found in PATH.\n"
        "Install instructions:\n"
        "  macOS:   brew install ffmpeg\n"
        "  Ubuntu:  sudo apt install ffmpeg\n"
        "  Windows: install from https://ffmpeg.org/download.html and add ffmpeg/bin to PATH"
    )


def reload_settings() -> None:
    global PROVIDER
    global GEMINI_API_KEY
    global GEMINI_MODEL
    global ANTHROPIC_API_KEY
    global CLAUDE_MODEL
    global PEXELS_API_KEY
    global AGENT_PROJECTS_DIR
    global FFMPEG_PATH
    global BLENDER_PATH
    global WHISPER_MODEL
    global GEMINI_TRANSCRIPT_MAX_INLINE_MB
    global GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC
    global GENAI_TIMEOUT_SEC
    global ANTHROPIC_TIMEOUT_SEC
    global MANIM_PREVIEW_TIMEOUT_SEC
    global MANIM_FINAL_TIMEOUT_SEC
    global FFMPEG_COMMAND_TIMEOUT_SEC
    global FFMPEG_EXPORT_TIMEOUT_SEC
    global BLENDER_RENDER_TIMEOUT_SEC
    global LLM_REQUEST_MAX_RETRIES
    global LLM_RETRY_BASE_DELAY_SEC

    settings = load_settings_from_env()
    PROVIDER = settings.provider
    GEMINI_API_KEY = settings.gemini_api_key
    GEMINI_MODEL = settings.gemini_model
    ANTHROPIC_API_KEY = settings.anthropic_api_key
    CLAUDE_MODEL = settings.claude_model
    PEXELS_API_KEY = settings.pexels_api_key
    AGENT_PROJECTS_DIR = settings.agent_projects_dir
    FFMPEG_PATH = settings.ffmpeg_path
    BLENDER_PATH = settings.blender_path
    WHISPER_MODEL = settings.whisper_model
    GEMINI_TRANSCRIPT_MAX_INLINE_MB = settings.gemini_transcript_max_inline_mb
    GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC = settings.gemini_transcript_max_inline_duration_sec
    GENAI_TIMEOUT_SEC = settings.genai_timeout_sec
    ANTHROPIC_TIMEOUT_SEC = settings.anthropic_timeout_sec
    MANIM_PREVIEW_TIMEOUT_SEC = settings.manim_preview_timeout_sec
    MANIM_FINAL_TIMEOUT_SEC = settings.manim_final_timeout_sec
    FFMPEG_COMMAND_TIMEOUT_SEC = settings.ffmpeg_command_timeout_sec
    FFMPEG_EXPORT_TIMEOUT_SEC = settings.ffmpeg_export_timeout_sec
    BLENDER_RENDER_TIMEOUT_SEC = settings.blender_render_timeout_sec
    LLM_REQUEST_MAX_RETRIES = settings.llm_request_max_retries
    LLM_RETRY_BASE_DELAY_SEC = settings.llm_retry_base_delay_sec


def validate_config() -> None:
    reload_settings()

    if PROVIDER not in {"gemini", "claude"}:
        _print_and_exit(
            f"Invalid PROVIDER={PROVIDER!r}. Valid options are: 'gemini', 'claude'."
        )

    if PROVIDER == "gemini" and not GEMINI_API_KEY:
        _print_and_exit(
            "GEMINI_API_KEY is required when PROVIDER=gemini. "
            "Set it in your environment or .env file."
        )

    if PROVIDER == "claude" and not ANTHROPIC_API_KEY:
        _print_and_exit(
            "ANTHROPIC_API_KEY is required when PROVIDER=claude. "
            "Set it in your environment or .env file."
        )

    if shutil.which(FFMPEG_PATH) is None:
        _print_and_exit(_ffmpeg_install_instructions())

    Path(AGENT_PROJECTS_DIR).mkdir(parents=True, exist_ok=True)
