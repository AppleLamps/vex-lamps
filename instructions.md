# VIDEO EDITING AGENT — CODEX BUILD PROMPT (v1 FINAL)

> Paste everything below this line into Codex as your prompt.
> Do not summarise, skip, or stub any section. Generate every file completely.

---

## MISSION

Build a complete, production-quality **AI-powered video editing agent** as a Python CLI tool called **Vex**. The agent accepts natural language instructions, plans and executes video editing operations autonomously using a structured tool system, maintains a stateful project timeline across commands, offers non-blocking intelligent suggestions, and supports both an interactive REPL mode and one-shot command mode.

The AI brain is fully provider-agnostic: the user selects between **Google Gemini** (default: `gemini-3.1-flash-lite-preview`) or **Anthropic Claude** (default: `claude-sonnet-4-5`) via a single `PROVIDER=` environment variable. All provider differences are hidden behind a clean abstraction layer — the rest of the codebase never imports provider SDKs directly.

This is not a prototype. Write clean, modular, production-grade code throughout.

---

## TECH STACK — NON-NEGOTIABLE

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Default AI Provider | Google Gemini via `google-generativeai` SDK |
| Secondary AI Provider | Anthropic Claude via `anthropic` SDK |
| Provider Abstraction | `providers/` module (see below) |
| CLI Framework | `typer` + `rich` |
| Video Engine — heavy ops | FFmpeg via `ffmpeg-python` |
| Video Engine — composition | `moviepy==1.0.3` |
| State Persistence | JSON file per project (`~/.video-agent/projects/`) |
| Env Config | `python-dotenv` |
| Transcription (optional) | `openai-whisper` (local, no API) |
| Dependency Manager | `pip` + `requirements.txt` |

---

## COMPLETE PROJECT FILE STRUCTURE

Generate **every single file** listed. No TODOs. No stubs. No ellipsis.

```
video-agent/
├── main.py                        # CLI entrypoint (Typer app)
├── agent.py                       # Provider-agnostic agentic loop
├── state.py                       # ProjectState dataclass + JSON persistence
├── engine.py                      # FFmpeg + moviepy unified video interface
├── prompts.py                     # System prompt + unified tool schema definitions
├── config.py                      # Env loading, validation, constants
│
├── providers/
│   ├── __init__.py                # Exports: get_provider(name) -> BaseLLMProvider
│   ├── base.py                    # BaseLLMProvider ABC
│   ├── gemini_provider.py         # Google Gemini implementation
│   └── claude_provider.py         # Anthropic Claude implementation
│
├── tools/
│   ├── __init__.py                # Tool registry: schema list + executor map
│   ├── info.py                    # get_video_info
│   ├── trim.py                    # trim_clip
│   ├── merge.py                   # merge_clips
│   ├── speed.py                   # adjust_speed
│   ├── transitions.py             # add_transition
│   ├── overlay.py                 # add_text_overlay
│   ├── audio.py                   # extract_audio, replace_audio, mute_segment
│   ├── export.py                  # export_video (with presets)
│   ├── undo.py                    # undo / redo
│   └── transcript.py              # transcribe_video (Whisper)
│
├── presets/
│   └── export_presets.json        # All platform export presets
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## SECTION 1 — PROVIDER ABSTRACTION LAYER (`providers/`)

This is the most critical architectural piece. Every file outside `providers/` interacts exclusively with `BaseLLMProvider`. No raw SDK calls anywhere else.

### `providers/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ToolCall:
    id: str           # Unique call ID (used for result routing)
    name: str         # Tool name matching executor registry
    params: dict      # Parsed arguments

@dataclass
class LLMResponse:
    text: str                    # Final text response (empty string if only tool calls)
    tool_calls: list[ToolCall]   # Empty list if pure text response
    raw: object                  # Raw provider response (for debugging)

class BaseLLMProvider(ABC):
    """
    All provider implementations must subclass this.
    The agent loop ONLY calls methods defined here.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict],     # Unified message format (see below)
        tools: list[dict],        # Unified tool schema list
        system_prompt: str,
        stream_callback=None,     # Optional: callable(text_chunk: str) for streaming
    ) -> LLMResponse:
        """
        Send a conversation turn to the LLM.
        Returns LLMResponse with either tool_calls or text (or both).
        If stream_callback is provided, stream text chunks to it as they arrive.
        """

    @abstractmethod
    def format_tool_result(
        self,
        tool_call_id: str,
        result: dict,
        is_error: bool = False,
    ) -> dict:
        """
        Format a tool execution result into this provider's native message format.
        Returns a dict ready to append to the messages list.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the active model identifier string for display."""
```

---

### Unified Message Format

All messages passed between `agent.py` and providers use this neutral format:

```python
# User message
{"role": "user", "content": "trim the first 30 seconds"}

# Assistant text message
{"role": "assistant", "content": "Done! I trimmed the intro."}

# Tool call message (assistant)
{"role": "assistant", "tool_calls": [{"id": "tc_001", "name": "trim_clip", "params": {"start": "0:30", "end": None}}]}

# Tool result message
{"role": "tool", "tool_call_id": "tc_001", "content": "{\"success\": true, \"message\": \"Trimmed.\"}"}
```

Providers translate this neutral format to/from their native SDK format internally.

---

### Unified Tool Schema Format

Tools are defined once in `prompts.py` in a neutral JSON-schema format:

```python
{
    "name": "trim_clip",
    "description": "Trim the video to a specific time range. Omit end to trim to the end of the video.",
    "parameters": {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "Start timestamp e.g. '0:30', '30', '30s'"},
            "end":   {"type": "string", "description": "End timestamp (optional)"}
        },
        "required": ["start"]
    }
}
```

Each provider translates this into its native tool declaration format internally.

---

### `providers/gemini_provider.py`

- Import: `import google.generativeai as genai`
- Model: configured via `GEMINI_MODEL` env var, default `gemini-3.1-flash-lite-preview`
- Translate neutral tool schemas → Gemini `FunctionDeclaration` / `Tool` objects
- Translate neutral messages → Gemini `Content` / `Part` objects
- Handle `response.candidates[0].content.parts` — check each part for `function_call`
- Map `function_call.name` + `function_call.args` → `ToolCall` dataclass
- Streaming: use `generate_content(..., stream=True)` and call `stream_callback(chunk.text)` per chunk
- `format_tool_result`: return Gemini-native function_response formatted dict

---

### `providers/claude_provider.py`

- Import: `from anthropic import Anthropic`
- Model: configured via `CLAUDE_MODEL` env var, default `claude-sonnet-4-5`
- Translate neutral tool schemas → Anthropic `tools` list format
- Translate neutral messages → Anthropic messages format
- Handle `response.content` blocks — check `block.type == "tool_use"` → `ToolCall`
- Streaming: use `client.messages.stream()`, call `stream_callback(text)` per event
- `format_tool_result`: return Anthropic-native tool_result message dict

---

### `providers/__init__.py`

```python
from .base import BaseLLMProvider
from .gemini_provider import GeminiProvider
from .claude_provider import ClaudeProvider

def get_provider(name: str) -> BaseLLMProvider:
    """
    Factory. Reads PROVIDER env var.
    'gemini' -> GeminiProvider (default)
    'claude' -> ClaudeProvider
    Unknown  -> raise ValueError with helpful message listing valid options
    """
```

---

## SECTION 2 — `config.py`

Load and validate all environment configuration at import time:

```python
PROVIDER          = os.getenv("PROVIDER", "gemini")          # "gemini" | "claude"
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL      = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
AGENT_PROJECTS_DIR = os.path.expanduser(os.getenv("AGENT_PROJECTS_DIR", "~/.video-agent/projects/"))
FFMPEG_PATH       = os.getenv("FFMPEG_PATH", "ffmpeg")
WHISPER_MODEL     = os.getenv("WHISPER_MODEL", "base")
```

Validation (run at startup via `validate_config()`):
- If `PROVIDER=gemini` → require `GEMINI_API_KEY`, print clear error and `sys.exit(1)` if missing
- If `PROVIDER=claude` → require `ANTHROPIC_API_KEY`, same
- Check FFmpeg in PATH using `shutil.which()` — if missing, print install instructions for Mac/Linux/Windows and exit
- `os.makedirs(AGENT_PROJECTS_DIR, exist_ok=True)`

---

## SECTION 3 — `state.py` — ProjectState

Full JSON-serializable dataclass:

```python
@dataclass
class ProjectState:
    project_id: str           # UUID4
    project_name: str
    created_at: str           # ISO 8601
    updated_at: str           # ISO 8601, updated on every save()
    source_files: list[str]   # Absolute paths to originals (never modified)
    working_file: str         # Absolute path to current working copy
    working_dir: str          # ~/.video-agent/projects/{project_id}/
    output_dir: str           # Default: dir containing source file
    timeline: list[dict]      # Ordered list of applied operations
    undo_stack: list[dict]    # Popped operations available to redo
    redo_stack: list[dict]    # Operations available to redo
    session_log: list[dict]   # Full conversation history (neutral format)
    metadata: dict            # duration_sec, fps, width, height, codec, has_audio, size_bytes
    provider: str             # "gemini" | "claude"
    model: str                # Exact model string
```

Operation dict format:
```python
{
    "op": "trim_clip",
    "params": {"start": 30.0, "end": None},
    "timestamp": "2025-01-01T12:00:00",
    "result_file": "/abs/path/to/result_001.mp4",
    "description": "Trimmed from 0:30 to end"
}
```

Required methods:
- `save()` — write to `{working_dir}/{project_id}.json`
- `classmethod load(project_id: str) -> ProjectState`
- `classmethod list_projects() -> list[dict]` — scan projects dir, return summary dicts
- `apply_operation(op: dict)` — push to timeline, clear redo_stack, update updated_at, call save()
- `undo() -> dict | None` — pop last from timeline, push to undo_stack, return it (None if empty)
- `redo() -> dict | None` — pop from redo_stack, push to timeline, return it (None if empty)
- `get_summary() -> str` — multi-line human-readable state overview

Undo implementation note: rebuilds working file by re-applying all remaining timeline ops from original source via engine.py. Do not attempt to reverse operations.

---

## SECTION 4 — `engine.py` — Video Engine

Unified FFmpeg + moviepy interface.

Rules for all functions:
- Accept absolute input paths
- Write output to a new uniquely-named file in `working_dir` (never overwrite)
- Log every FFmpeg command at DEBUG level via Python `logging`
- Raise `VideoEngineError(message, command)` on failure

```python
class VideoEngineError(Exception):
    def __init__(self, message: str, command: str = ""): ...

def parse_timestamp(s) -> float:
    """
    Converts any timestamp format to seconds (float).
    Supports: int, float, "83", "83.5", "83s", "1:23", "1:23.5", "0:01:23", "0:01:23.5"
    Raises ValueError with the exact invalid input shown on bad input.
    """

def probe_video(path: str) -> dict: ...
    # Returns: duration_sec, fps, width, height, codec, has_audio, size_bytes, format

def trim(input_path: str, working_dir: str, start_sec: float, end_sec: float | None) -> str: ...
def merge(input_paths: list[str], working_dir: str) -> str: ...
    # Use FFmpeg concat demuxer (write temp concat list file)
def adjust_speed(input_path: str, working_dir: str, factor: float, segment_start: float | None, segment_end: float | None) -> str: ...
    # setpts + atempo; chain multiple atempo if factor > 2.0 or < 0.5
def fade_in(input_path: str, working_dir: str, duration: float) -> str: ...
def fade_out(input_path: str, working_dir: str, duration: float) -> str: ...
def crossfade(input1: str, input2: str, working_dir: str, duration: float) -> str: ...
    # Use FFmpeg xfade filter
def add_text(input_path: str, working_dir: str, text: str, position: str, font_size: int, color: str, start_sec: float, end_sec: float, bg_opacity: float) -> str: ...
    # Use moviepy for text overlay (easier font/positioning control)
def extract_audio(input_path: str, working_dir: str, fmt: str) -> str: ...
def replace_audio(video_path: str, audio_path: str, working_dir: str, mix: bool, mix_ratio: float) -> str: ...
def mute_segment(input_path: str, working_dir: str, start_sec: float, end_sec: float) -> str: ...
def export(input_path: str, output_path: str, preset: dict) -> str: ...
def extract_frame(input_path: str, working_dir: str, timestamp_sec: float) -> str: ...
def estimate_output_size(input_path: str, preset: dict) -> int: ...
    # Returns estimated bytes: (video_bitrate + audio_bitrate) * duration_sec / 8
def check_disk_space(path: str, required_bytes: int) -> bool: ...
    # Uses shutil.disk_usage()
```

---

## SECTION 5 — `tools/` — Tool Implementations

### `tools/__init__.py`

Exports two objects used exclusively by `agent.py`:

```python
TOOL_SCHEMAS: list[dict]         # All unified tool schema dicts (from prompts.py)
TOOL_EXECUTORS: dict[str, callable] = {
    "get_video_info":   info.execute,
    "trim_clip":        trim.execute,
    "merge_clips":      merge.execute,
    "adjust_speed":     speed.execute,
    "add_transition":   transitions.execute,
    "add_text_overlay": overlay.execute,
    "extract_audio":    audio.execute_extract,
    "replace_audio":    audio.execute_replace,
    "mute_segment":     audio.execute_mute,
    "export_video":     export.execute,
    "undo":             undo.execute_undo,
    "redo":             undo.execute_redo,
    "transcribe_video": transcript.execute,
}
```

### Executor contract — every executor must match:

```python
def execute(params: dict, state: ProjectState) -> dict:
    return {
        "success": bool,
        "message": str,            # Human-readable result for the LLM
        "suggestion": str | None,  # Optional tip, must start with "[SUGGESTION]: " if present
        "updated_state": ProjectState
    }
```

### Individual tool specs:

**`get_video_info`** — probe `state.working_file`, update `state.metadata`, return formatted metadata string. No params.

**`trim_clip`** — params: `start` (str), `end` (str, optional). Parse both via `parse_timestamp()`. Call `engine.trim()`. Suggestion: if resulting duration < 2s, warn it may be too short for transitions.

**`merge_clips`** — params: `file_paths: list[str]`. Validate all paths exist. Call `engine.merge()`. Suggestion: if clips have mismatched resolutions, warn and note auto-scaling was applied.

**`adjust_speed`** — params: `factor` (float 0.25–4.0), `start` (str, optional), `end` (str, optional). Validate range. Suggestion: if has_audio and factor != 1.0, warn about pitch shift.

**`add_transition`** — params: `type` (enum: fade_in | fade_out | crossfade), `duration` (float), `position` (enum: start | end | between). Route to correct engine function.

**`add_text_overlay`** — params: `text` (str), `position` (enum: top | center | bottom | top_left | top_right | bottom_left | bottom_right), `start` (str), `end` (str), `font_size` (int, default 48), `color` (str, default "white"), `background_opacity` (float 0.0–1.0, default 0.0).

**`extract_audio`** — params: `format` (enum: mp3 | wav | aac, default mp3), `output_path` (str, optional).

**`replace_audio`** — params: `audio_path` (str), `mix_with_original` (bool, default false), `mix_ratio` (float 0.0–1.0, default 0.5).

**`mute_segment`** — params: `start` (str), `end` (str).

**`export_video`** — params: `preset_name` (str), `output_path` (str, optional), `custom_settings` (dict, optional). Load preset from `presets/export_presets.json`. Call `estimate_output_size()` and `check_disk_space()` before exporting. Include size estimate in message.

**`undo`** — no params. Call `state.undo()`. If None → "Nothing to undo." Otherwise rebuild working file from remaining timeline via engine.

**`redo`** — no params. Call `state.redo()`. If None → "Nothing to redo." Otherwise re-apply the returned operation.

**`transcribe_video`** — wrap `import whisper` in `try/except ImportError`, return graceful install message if missing. Otherwise transcribe `state.working_file`, save `.srt` + `.txt` to `working_dir`, return timestamped transcript. Suggestion: offer to auto-add captions.

---

## SECTION 6 — `presets/export_presets.json`

```json
{
  "youtube_1080p": {
    "description": "YouTube — 1080p HD",
    "resolution": "1920x1080",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "8000k",
    "audio_bitrate": "192k",
    "fps": 30,
    "format": "mp4",
    "audio_only": false
  },
  "youtube_4k": {
    "description": "YouTube — 4K UHD",
    "resolution": "3840x2160",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "35000k",
    "audio_bitrate": "320k",
    "fps": 60,
    "format": "mp4",
    "audio_only": false
  },
  "instagram_reels": {
    "description": "Instagram Reels / Stories — 9:16 vertical",
    "resolution": "1080x1920",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "3500k",
    "audio_bitrate": "128k",
    "fps": 30,
    "format": "mp4",
    "audio_only": false
  },
  "instagram_square": {
    "description": "Instagram Feed — 1:1 square",
    "resolution": "1080x1080",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "3500k",
    "audio_bitrate": "128k",
    "fps": 30,
    "format": "mp4",
    "audio_only": false
  },
  "tiktok": {
    "description": "TikTok — 9:16 vertical",
    "resolution": "1080x1920",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "4000k",
    "audio_bitrate": "128k",
    "fps": 30,
    "format": "mp4",
    "audio_only": false
  },
  "twitter_x": {
    "description": "Twitter / X — landscape",
    "resolution": "1280x720",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "video_bitrate": "2000k",
    "audio_bitrate": "128k",
    "fps": 30,
    "format": "mp4",
    "audio_only": false
  },
  "podcast_audio": {
    "description": "Podcast — audio only MP3",
    "resolution": null,
    "video_codec": null,
    "audio_codec": "libmp3lame",
    "video_bitrate": null,
    "audio_bitrate": "256k",
    "fps": null,
    "format": "mp3",
    "audio_only": true
  },
  "custom": {
    "description": "Custom — pass settings via custom_settings param",
    "resolution": null,
    "video_codec": null,
    "audio_codec": null,
    "video_bitrate": null,
    "audio_bitrate": null,
    "fps": null,
    "format": null,
    "audio_only": false
  }
}
```

---

## SECTION 7 — `prompts.py`

Define the system prompt template and all unified tool schemas.

### System Prompt

Inject current project state on every call. The prompt instructs the LLM to:

1. Play the role of **Vex** — precise, efficient video editing assistant. Occasionally witty. Never verbose.
2. Call `get_video_info` first if `state.metadata` is empty.
3. Break complex instructions into multiple sequential tool calls in a single response.
4. After tool execution, reflect: did it succeed? Is a follow-up needed?
5. Format all suggestions **exactly**: `[SUGGESTION]: <text> — reply 'yes' to apply or continue.`
6. Originals are safe — always work on the working copy.
7. Reference previous timeline operations by name when relevant.
8. If instruction is ambiguous, ask exactly ONE clarifying question before acting.
9. Keep responses concise and terminal-friendly. No markdown headers. Plain text. Emoji only for status.
10. When user says "yes" after a `[SUGGESTION]`, apply it immediately.

State context injected into every system prompt call:
```
--- CURRENT PROJECT STATE ---
Project: {state.project_name}
Provider: {state.provider} / {state.model}
Working file: {state.working_file}
Duration: {metadata.duration_sec}s | {metadata.width}x{metadata.height} | {metadata.fps}fps
Timeline ops applied: {len(state.timeline)}
Last operation: {state.timeline[-1]['description'] if state.timeline else 'none'}
---
```

---

## SECTION 8 — `agent.py` — Provider-Agnostic Agentic Loop

```python
@dataclass
class AgentResponse:
    message: str
    tools_called: list[str]
    suggestions: list[str]
    success: bool

class VideoAgent:
    def __init__(self, state: ProjectState, provider: BaseLLMProvider):
        self.state = state
        self.provider = provider
        self.conversation: list[dict] = []

    def run(self, user_message: str, stream_callback=None) -> AgentResponse:
        """
        Provider-agnostic agentic loop:

        1. Append user message to self.conversation
        2. Build system prompt with current state context
        3. Call self.provider.chat(conversation, TOOL_SCHEMAS, system_prompt, stream_callback)
        4. If response.tool_calls non-empty:
             a. Append assistant tool_call message to conversation
             b. For each tool_call:
                  - Look up in TOOL_EXECUTORS[tool_call.name]
                  - Call executor(tool_call.params, self.state)
                  - Update self.state = result["updated_state"]
                  - Append self.provider.format_tool_result(...) to conversation
             c. Loop back to step 3
        5. When response.tool_calls is empty → final response reached
        6. Parse [SUGGESTION]: lines from response.text → AgentResponse.suggestions
        7. Append assistant text message to conversation
        8. Update state.session_log, call state.save()
        9. Return AgentResponse

        Safety:
        - Max 10 loop iterations (raise AgentLoopError if exceeded)
        - If executor raises → format as tool_result with is_error=True, LLM gets one retry
        - Unknown tool name → is_error=True result with helpful message
        """
```

---

## SECTION 9 — `main.py` — CLI Entrypoint

### Startup (runs before every command)
1. Load `.env` via dotenv
2. Call `config.validate_config()`
3. Instantiate provider via `providers.get_provider(config.PROVIDER)`
4. Print ASCII banner:

```
  ██╗   ██╗███████╗██╗  ██╗
  ██║   ██║██╔════╝╚██╗██╔╝
  ██║   ██║█████╗   ╚███╔╝
  ╚██╗ ██╔╝██╔══╝   ██╔██╗
   ╚████╔╝ ███████╗██╔╝ ██╗
    ╚═══╝  ╚══════╝╚═╝  ╚═╝

  v1.0.0  |  gemini-3.1-flash-lite-preview  |  multi-provider ready
```

---

### `video-agent start <video_path> [--name TEXT]`
- Validate path and format
- Create ProjectState with UUID, copy source to working dir
- Call `probe_video()`, populate `state.metadata`
- Print Rich bordered project panel
- Drop into interactive REPL

---

### `video-agent repl [--project TEXT]`

REPL prompt: `Vex ▸ `

Slash commands (intercepted before LLM):

| Command | Action |
|---|---|
| `/status` | Print `state.get_summary()` |
| `/timeline` | Rich table: #, Operation, Params, Timestamp |
| `/undo` | Execute undo tool, print result |
| `/redo` | Execute redo tool, print result |
| `/export <preset>` | Call export_video tool directly |
| `/provider` | Show active provider + model |
| `/projects` | List all saved projects in Rich table |
| `/help` | Print all slash commands |
| `/quit` or `/exit` | Save and exit |

REPL behaviour:
- All other input → `agent.run(input, stream_callback=...)`
- Stream via `rich.live.Live` token-by-token
- Show tool spinner (`rich.progress`) per tool during execution, then ✅/❌
- `AgentResponse.suggestions` → Rich yellow Panel per suggestion
- `KeyboardInterrupt` → "Save and exit? [y/n]"

---

### `video-agent run "<instruction>" --project TEXT`
One-shot: load project, run instruction, print, save, exit.

### `video-agent projects`
Rich table: short ID, Name, Created, Last Modified, Source File, Timeline Ops.

### `video-agent export <preset_name> --project TEXT [--output TEXT]`
Direct export without REPL.

---

## SECTION 10 — RICH TERMINAL UI

- Streaming: `rich.live.Live` + text deltas
- Tool execution: `rich.progress.Progress` spinner per tool
- Suggestions: `rich.panel.Panel` yellow border, title "💡 Suggestion"
- Timeline: `rich.table.Table`
- Projects list: `rich.table.Table`
- Unexpected errors: `rich.console.Console.print_exception()`
- Export progress: `rich.progress.Progress` bar via FFmpeg stderr duration parsing

---

## SECTION 11 — ERROR HANDLING & SAFETY

1. Original files are **never modified**. Structurally enforced by working copy pattern.
2. Every executor wraps engine calls in `try/except VideoEngineError` — returns `success: False`, never raises.
3. Agent loop catches unexpected executor exceptions → `is_error=True` tool result → LLM retries once.
4. `KeyboardInterrupt` in REPL → prompt save/exit.
5. `parse_timestamp()` raises `ValueError` with exact input shown — caught in executor.
6. All file paths validated with `os.path.isfile()` before engine calls.
7. Disk space checked before every export.
8. Max 10 agent loop iterations enforced with `AgentLoopError`.

---

## SECTION 12 — `requirements.txt`

```
anthropic>=0.40.0
google-generativeai>=0.8.0
typer>=0.12.0
rich>=13.7.0
ffmpeg-python>=0.2.0
moviepy==1.0.3
python-dotenv>=1.0.0
openai-whisper>=20231117
numpy>=1.24.0
```

---

## SECTION 13 — `.env.example`

```env
# ── Provider Selection ─────────────────────────────────────
# Options: "gemini" (default) | "claude"
PROVIDER=gemini

# ── Gemini (Google AI Studio) ──────────────────────────────
GEMINI_API_KEY=your_google_ai_studio_key_here
GEMINI_MODEL=gemini-3.1-flash-lite-preview

# ── Claude (Anthropic) ─────────────────────────────────────
ANTHROPIC_API_KEY=your_anthropic_key_here
CLAUDE_MODEL=claude-sonnet-4-5

# ── Shared ─────────────────────────────────────────────────
AGENT_PROJECTS_DIR=~/.video-agent/projects/
FFMPEG_PATH=ffmpeg
WHISPER_MODEL=base
```

---

## SECTION 14 — `README.md`

Include all sections:
1. What is Vex (2 sentences)
2. Prerequisites — Python 3.11+, FFmpeg install for Mac/Linux/Windows
3. Installation — clone, `pip install -r requirements.txt`
4. Configuration — copy `.env.example`, fill keys, set PROVIDER
5. Switching providers — one line: `PROVIDER=claude` vs `PROVIDER=gemini`
6. All CLI commands with real examples
7. REPL slash commands table
8. Export presets table
9. Full realistic example session transcript
10. Architecture overview — brief prose on provider abstraction, tool registry, agent loop, state

---

## SECTION 15 — VALIDATION SESSION

The finished build must handle this session without errors:

```
$ video-agent start ~/Downloads/footage.mp4 --name "My Vlog"

  [VEX ASCII BANNER]
  v1.0.0  |  gemini-3.1-flash-lite-preview  |  multi-provider ready

  ┌─ Project: My Vlog ─────────────────────────────────────┐
  │  File:      footage.mp4                                │
  │  Duration:  4:32  |  1920x1080  |  29.97 fps           │
  │  Size:      847 MB                                     │
  │  Provider:  gemini / gemini-3.1-flash-lite-preview     │
  │  Timeline:  0 operations                               │
  └────────────────────────────────────────────────────────┘

Vex ▸ cut out the first 45 seconds and the last minute

  ⠸ get_video_info...         ✅
  ⠸ trim_clip (0:45→end)...   ✅
  ⠸ trim_clip (→3:32)...      ✅

  Done. Removed intro (0:00–0:45) and outro (3:32–4:32). Runtime is now 2:47.

  ╭─ 💡 Suggestion ────────────────────────────────────────────╮
  │ The cut at 0:45 lands mid-sentence. A 0.8s crossfade would │
  │ smooth it out. Reply 'yes' to apply or continue.           │
  ╰────────────────────────────────────────────────────────────╯

Vex ▸ yes

  ⠸ add_transition (crossfade, 0.8s)... ✅
  Crossfade applied. Clean cut.

Vex ▸ add "TechWithAlex" at the bottom for the first 5 seconds

  ⠸ add_text_overlay... ✅
  Text overlay added: "TechWithAlex", bottom, 0:00–0:05.

Vex ▸ export for youtube

  ⠸ export_video (youtube_1080p)...
  Estimated size: ~312 MB  |  Disk space: ✅
  ████████████████████░░░  82%  Exporting...
  ✅ Saved: ~/Downloads/MyVlog_youtube_1080p.mp4 (301 MB)

Vex ▸ /provider
  Active: gemini / gemini-3.1-flash-lite-preview

Vex ▸ /timeline
  ┌───┬──────────────────┬──────────────────────┬──────────┐
  │ # │ Operation        │ Parameters           │ Time     │
  ├───┼──────────────────┼──────────────────────┼──────────┤
  │ 1 │ trim_clip        │ start=0:45           │ 12:01:03 │
  │ 2 │ trim_clip        │ end=3:32             │ 12:01:04 │
  │ 3 │ add_transition   │ crossfade 0.8s       │ 12:01:22 │
  │ 4 │ add_text_overlay │ "TechWithAlex" 0–5s  │ 12:01:45 │
  └───┴──────────────────┴──────────────────────┴──────────┘

Vex ▸ /quit
  Project saved. Goodbye.
```

---

## FINAL CODEX INSTRUCTIONS — READ EVERY POINT

1. **Generate every file completely.** No `# TODO`, no `pass`, no `...`, no stubs of any kind.
2. **All imports resolve** using only packages in `requirements.txt`.
3. **Provider abstraction is the spine.** `agent.py` imports zero provider SDKs. Only `providers/` files import SDKs.
4. **Tool name in `TOOL_EXECUTORS` must match exactly** the `name` field in `TOOL_SCHEMAS` and the `name` in `ToolCall.name`. One mismatch breaks the entire loop.
5. **`parse_timestamp()` is the single source of truth** for all timestamp parsing. Every tool that accepts timestamps calls it. No parsing elsewhere.
6. **Agentic loop terminates correctly**: call `provider.chat()` only while `response.tool_calls` is non-empty. Stop the loop when tool_calls is empty. Enforce max 10 iterations.
7. **Streaming wiring**: `agent.run()` accepts optional `stream_callback`. Passes it to `provider.chat()`. REPL provides a callback writing to `rich.live.Live`.
8. **Undo rebuilds from source**: re-apply all remaining timeline ops in order using engine functions. Never attempt to reverse an operation.
9. **Whisper is always optional**: `try/except ImportError` in `transcript.py`. Fails gracefully with install hint.
10. **File writes go to working_dir only**, except final exports which go to `state.output_dir` (default: dir of original source file).
11. **Gemini is the default provider** (`PROVIDER=gemini`, model `gemini-3.1-flash-lite-preview`). Claude is opt-in via `PROVIDER=claude`.
12. **`gemini-3.1-flash-lite-preview` is a recently released model** that may not be in the google-generativeai SDK's known model list. Pass the model string directly as a string identifier — do not validate it against any hardcoded list.