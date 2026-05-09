# Vex

[![CI](https://github.com/AppleLamps/vex-lamps/actions/workflows/ci.yml/badge.svg)](https://github.com/AppleLamps/vex-lamps/actions/workflows/ci.yml)

Vex is a local AI video editing workspace with both a browser UI and a terminal workflow.

You load a video, talk to Vex in plain English, watch the agent run real editing tools, preview the current cut, and export a finished file. Vex keeps the original footage untouched and edits a project working copy with FFmpeg, MoviePy, and provider-backed tool calling.

## Highlights

- Local browser app with upload, preview, chat, live command status, export, and download
- CLI and REPL for fast terminal workflows
- Stateful projects stored under `AGENT_PROJECTS_DIR`
- Safe working-copy editing, timeline history, undo, and redo
- Real video operations: trim, remove middle segments, speed changes, fades, overlays, audio edits, silence cleanup, subtitles, B-roll, generated visuals, and exports
- Gemini by default, Claude when selected
- Gemini video transcription for short clips, with Whisper available as an optional local fallback
- Collapsed tool-call progress in the web chat, with full errors expandable inline
- Tips & Tricks page in the web app that lists common agent capabilities and prompt examples

## Quick Start: Web App

Install Vex, configure `.env`, then run:

```bash
vex web
```

The local app opens at:

```text
http://127.0.0.1:8765
```

Useful options:

```bash
vex web --port 8766
vex web --project <project-id>
vex web --no-open
```

Web workflow:

1. Click `Attach video` or drop a video on the empty state.
2. Preview the loaded video at the top of the chat.
3. Ask for an edit, transcript, short, visual pass, or export.
4. Watch the compact command status update while tools run.
5. Expand command details only when you need to read the trace or a full error.
6. Click `Export` on the video, then download the current file or latest export.

Supported uploads:

```text
.mp4 .mov .avi .mkv .webm .m4v .flv
```

The upload limit defaults to 4 GB and can be changed with `VEX_WEB_MAX_UPLOAD_MB`.

## Quick Start: Terminal

```bash
vex
```

Then type a normal sentence with a video path:

```text
Vex > trim the first 30 seconds of "D:\videos\clip.mp4"
```

Continue naturally:

```text
Vex > remove the silent pauses
Vex > add subtitles
Vex > export it for youtube
Vex > /quit
```

If no project is loaded, include a video path or YouTube URL in your first message. Vex creates or reuses the project automatically.

## Installation

### Requirements

- Python 3.11+
- FFmpeg installed and available on `PATH`
- `yt-dlp` through the Python environment for YouTube loading
- A Gemini API key or Anthropic API key
- Manim optional for premium generated visuals
- Blender optional for cinematic generated visuals
- Whisper optional for local transcription fallback

FFmpeg install:

- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows: install from `https://ffmpeg.org/download.html` and add `ffmpeg/bin` to `PATH`

### Install Vex

```bash
git clone https://github.com/AppleLamps/vex-lamps.git
cd vex-lamps
pip install -e .
```

Optional extras:

```bash
pip install -e ".[manim]"
pip install -e ".[transcription]"
pip install -e ".[full]"
```

Development install:

```bash
pip install -e ".[full,dev]"
```

After install:

```bash
vex --version
vex web
```

### Windows PATH Note

If `vex` is not recognized after install, add your Python Scripts directory to `PATH`, then restart the terminal.

Example:

```text
C:\Users\<you>\AppData\Roaming\Python\Python311\Scripts
```

## Configuration

Copy the environment example:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Default Gemini setup:

```env
PROVIDER=gemini
GEMINI_API_KEY=your_google_ai_studio_key_here
GEMINI_MODEL=gemma-4-31b-it
```

Claude setup:

```env
PROVIDER=claude
ANTHROPIC_API_KEY=your_anthropic_key_here
CLAUDE_MODEL=claude-sonnet-4-5
```

Important settings:

| Setting | Purpose |
|---|---|
| `PROVIDER` | `gemini` or `claude` |
| `GEMINI_API_KEY` | Google AI Studio key |
| `GEMINI_MODEL` | Gemini model used for planning and tool calling |
| `ANTHROPIC_API_KEY` | Anthropic key |
| `CLAUDE_MODEL` | Claude model used when `PROVIDER=claude` |
| `PEXELS_API_KEY` | Enables stock B-roll search |
| `AGENT_PROJECTS_DIR` | Project storage directory |
| `FFMPEG_PATH` | FFmpeg executable path |
| `BLENDER_PATH` | Blender executable path |
| `WHISPER_MODEL` | Whisper model for local fallback transcription |
| `GEMINI_TRANSCRIPT_MAX_INLINE_MB` | Max video size for Gemini inline transcription |
| `GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC` | Max video duration for Gemini inline transcription |
| `VEX_WEB_MAX_UPLOAD_MB` | Web upload limit |
| `GENAI_TIMEOUT_SEC` | Gemini request timeout |
| `ANTHROPIC_TIMEOUT_SEC` | Claude request timeout |
| `LLM_REQUEST_MAX_RETRIES` | Provider retry count |

## What Vex Can Do

### Core Editing

- Inspect video metadata
- Trim clips by timestamp
- Remove a middle segment while keeping the surrounding footage
- Merge multiple clips
- Adjust playback speed for a full clip or selected segment
- Add fade in, fade out, and fade-through-black transitions
- Add timed text overlays
- Remove silent gaps from raw footage
- Extract selected highlight segments into a shorter cut

### Audio

- Extract audio as `mp3`, `wav`, or `aac`
- Replace a video's audio track
- Mix external audio with original audio
- Mute a selected time range

### Captions and Transcripts

- Transcribe short videos through Gemini video input when using Gemini
- Fall back to local Whisper when selected or required
- Generate `transcript.txt` and `transcript.srt`
- Burn subtitles directly into the video
- Summarize long clips into highlight cuts using transcript-aware segment selection
- Create multiple vertical shorts with captions, ranking, hooks, metadata, and a manifest bundle

### B-Roll and Generated Visuals

- Generate timestamped B-roll suggestions
- Fetch and splice transcript-aware stock B-roll from Pexels
- Generate transcript-aligned visuals and animations with Manim
- Use FFmpeg-rendered editorial cards when Manim is unavailable
- Use Blender for optional cinematic generated shots when installed

### Export and Delivery

- Export with built-in presets for YouTube, Instagram, TikTok, X, and podcast audio
- Export from the web app, REPL, or CLI
- Keep `latest_export` and `export_history` artifacts in project state
- Download the current working video or latest export from the web UI

## Natural-Language Examples

```text
Vex > trim this from 00:05 to 00:18
Vex > cut out 00:12 to 00:19
Vex > remove the silent gaps
Vex > add subtitles and burn them at the bottom
Vex > mute the audio from 00:10 to 00:14
Vex > make this a 60 second highlight reel
Vex > turn this podcast into 4 YouTube Shorts with captions
Vex > add stock cutaways that match the narration
Vex > add precise generated visuals where the explanation needs them
Vex > export this for YouTube 1080p
```

## Full Tool Surface

| Tool | What it does |
|---|---|
| `get_video_info` | Reads duration, resolution, fps, codec, audio presence, format, and size |
| `trim_clip` | Trims the current working video to a selected range |
| `remove_segment` | Removes a middle time range and joins the remaining footage |
| `merge_clips` | Concatenates the current working clip with one or more external clips |
| `adjust_speed` | Changes playback speed globally or for a selected segment |
| `add_transition` | Adds `fade_in`, `fade_out`, or fade-through-black transitions |
| `add_text_overlay` | Adds timed text overlays to the video |
| `extract_audio` | Exports audio from the current working video |
| `replace_audio` | Replaces or mixes audio with an external track |
| `mute_segment` | Silences audio in a selected time range |
| `trim_silence` | Detects and removes dead-air pauses while preserving speech handles |
| `transcribe_video` | Creates transcript artifacts with Gemini video input or optional Whisper fallback |
| `burn_subtitles` | Burns subtitles from an SRT file into the video |
| `summarize_clip` | Uses transcript-aware LLM selection to build a shorter highlight cut |
| `create_auto_shorts` | Builds ranked vertical shorts with captions, metadata, and a manifest bundle |
| `add_auto_broll` | Plans, fetches, reranks, and splices Pexels B-roll into the working video |
| `add_auto_visuals` | Plans generated visuals, renders them with the best supported renderer, and composites them into the video |
| `export_video` | Exports the working video with a named preset and records latest export artifacts |
| `undo` | Rebuilds the project without the last operation |
| `redo` | Reapplies the most recently undone operation |

Inside the REPL, use `/trace` to inspect the latest recorded agent trace for the current project.

## CLI Commands

| Command | Purpose |
|---|---|
| `vex` | Start the interactive REPL |
| `vex web` | Start the local browser app |
| `vex start <video_path>` | Create a project and open the REPL |
| `vex repl [--project TEXT]` | Open the REPL for an existing project |
| `vex run "<instruction>" --project TEXT` | Run one instruction and exit |
| `vex projects` | List saved projects |
| `vex export <preset> --project TEXT` | Export without entering the REPL |
| `vex shorts` | Generate a packaged shorts bundle from an existing project |
| `vex auto-broll` | Apply Pexels-backed stock footage inserts |
| `vex auto-visuals` | Apply generated supporting visuals |
| `vex youtube-shorts` | Download a YouTube video and run auto shorts |
| `vex --version` | Show the installed version |

### Web Command

```bash
vex web [--project <project-id>] [--host 127.0.0.1] [--port 8765] [--open/--no-open]
```

The web app uses local HTTP endpoints for upload, project state, media preview, downloads, and Server-Sent Events job progress.

### REPL Slash Commands

| Command | Action |
|---|---|
| `/status` | Show the current project summary |
| `/timeline` | Show the applied timeline |
| `/undo` | Undo the last edit |
| `/redo` | Redo the last undone edit |
| `/export <preset>` | Export immediately with a preset |
| `/provider` | Show the active provider and model |
| `/projects` | List saved projects |
| `/trace` | Show the latest agent trace |
| `/help` | Show available slash commands |
| `/quit` or `/exit` | Save and exit |

## Export Presets

| Preset | Description | Format |
|---|---|---|
| `youtube_1080p` | YouTube 1080p HD | `mp4` |
| `youtube_4k` | YouTube 4K UHD | `mp4` |
| `instagram_reels` | Instagram Reels and Stories vertical | `mp4` |
| `instagram_square` | Instagram square feed | `mp4` |
| `tiktok` | TikTok vertical | `mp4` |
| `twitter_x` | X landscape | `mp4` |
| `podcast_audio` | Audio-only podcast export | `mp3` |
| `custom` | Start from your own settings | variable |

## Project Storage

Vex never edits the original source file directly.

Each project stores:

- original source path or source URL
- source copy in the project directory
- current working file
- timeline operations
- redo stack
- session log
- metadata
- provider and model
- artifacts such as transcripts, latest export, export history, B-roll manifests, shorts manifests, and trace logs

Default project storage:

```text
~/.video-agent/projects/
```

Override it with:

```env
AGENT_PROJECTS_DIR=D:\vex-projects
```

## Architecture

| Path | Responsibility |
|---|---|
| `main.py` | CLI, REPL, web command, project loading, slash commands, and terminal status UI |
| `web_app.py` | Local HTTP server, upload intake, project API, SSE jobs, media streaming, and downloads |
| `web_static/` | Browser UI for chat, video preview, collapsed tool progress, uploads, exports, and Tips & Tricks |
| `agent.py` | Provider-agnostic agent loop and tool orchestration |
| `agent_trace.py` | Trace event recording for terminal and web progress |
| `providers/` | Gemini and Claude adapters behind one interface |
| `prompts.py` | System prompt and tool schemas |
| `tools/` | Agent-callable editing tools and state updates |
| `engine.py` | FFmpeg and MoviePy operations |
| `state.py` | Persistent project state and timeline history |
| `sources.py` | YouTube source loading and project reuse |
| `visual_intelligence.py` | Transcript beat mining, visual planning, and renderer-aware normalization |
| `renderers/` | Generated-visual backends for Manim, FFmpeg, and optional Blender |
| `vex_manim/` | Manim scene briefs, blueprinting, runtime helpers, validation, and QA |
| `presets/export_presets.json` | Built-in export presets |
| `tests/` | API, engine, config, visual IR, and web app coverage |

## Web API Summary

The web app is local-only by default and binds to `127.0.0.1`.

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | Current provider, model, projects, selected project, and UI-ready project summary |
| `POST /api/upload` | Raw binary upload with filename headers and progress support |
| `POST /api/load` | Load a local path or YouTube URL |
| `POST /api/new-session` | Clear the selected project in the UI |
| `POST /api/select` | Select a recent project |
| `POST /api/jobs` | Start an agent run and return a `job_id` immediately |
| `GET /api/jobs/<job_id>/events` | Stream job events over Server-Sent Events |
| `GET /api/projects/<id>/media/current` | Stream the current working video |
| `GET /api/projects/<id>/download/current` | Download the current working video |
| `GET /api/projects/<id>/download/latest-export` | Download the latest export when one exists |

One active job is allowed per project. Starting another job for the same project while one is running returns `409`.

## Dependencies and Runtime Notes

### FFmpeg

FFmpeg is mandatory for metadata probing, trims, merges, audio processing, subtitle burn-in, silence detection, B-roll compositing, and exports.

### Gemini Video Transcription

When using Gemini and the clip fits the configured inline limits, `transcribe_video` sends the video directly to Gemini and writes `transcript.txt` plus `transcript.srt`.

Defaults:

```env
GEMINI_TRANSCRIPT_MAX_INLINE_MB=100
GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC=90
```

Use Whisper for longer clips, larger files, local-only transcription, or provider fallback.

### Whisper

Whisper is optional.

Install it with:

```bash
pip install -e ".[transcription]"
```

### Manim

`add_auto_visuals` can use the FFmpeg renderer without Manim. Premium generated scenes require Manim.

Install it with:

```bash
pip install -e ".[manim]"
```

### MoviePy

Text overlays use MoviePy. The code includes compatibility handling for current MoviePy APIs and older MoviePy installs.

### Subtitle Burning

Subtitle burn-in depends on FFmpeg builds that include the `subtitles` filter.

## Troubleshooting

### `vex` Is Not Recognized

Add your Python Scripts directory to `PATH`, then restart the terminal.

### `FFmpeg Was Not Found In PATH`

Install FFmpeg and verify this works before launching Vex:

```bash
ffmpeg -version
```

### Web Upload Fails

Check that:

- the file extension is supported
- the file is smaller than `VEX_WEB_MAX_UPLOAD_MB`
- the browser is connected to the same local server process

### The Agent Says The API Key Is Invalid

Update the active provider key in `.env`, then restart `vex web` or the REPL.

For Gemini:

```env
PROVIDER=gemini
GEMINI_API_KEY=your_real_key
```

### Transcription Fails

Check that:

- the active Gemini model supports video input if using Gemini transcription
- the video fits `GEMINI_TRANSCRIPT_MAX_INLINE_MB` and `GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC`
- Whisper is installed if you selected or need local fallback

### Subtitle Burn-In Fails

Check that:

- `transcript.srt` exists
- your FFmpeg build supports the `subtitles` filter
- the subtitle path is valid on your OS

### Text Overlay Fails

Check MoviePy and local font/rendering support. On some Windows setups, ImageMagick may still be needed for older MoviePy text rendering paths.

## Development

Run focused checks:

```bash
python -m py_compile main.py engine.py web_app.py config.py
python -m ruff check main.py engine.py web_app.py config.py tools/export.py tests/test_web_app.py tests/test_config_and_visual_ir.py
python -m pytest
```

Before opening a PR:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy
```

If you report a bug, include:

- OS
- Python version
- active provider and model
- exact command, prompt, or web action
- traceback or browser-visible error
- whether the issue happens on a fresh project or resumed project

## License

MIT. See [LICENSE](LICENSE).
