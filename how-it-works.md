# How Vex Works

This document is the technical map for the current Vex repo. It explains the browser app, terminal workflow, agent loop, project state, tool system, and media engine.

## What Vex Is

Vex is a local AI video editing workspace.

It has two main entry points:

- `vex web`: a local browser UI for upload, preview, chat, live job progress, export, and download
- `vex`: a terminal REPL for conversational editing and power-user workflows

Both entry points use the same project state, provider layer, agent loop, tools, and media engine.

The core design is:

1. keep user interaction conversational
2. keep real editing state in structured project files
3. let the model choose tools through schemas
4. validate and execute edits with deterministic Python, FFmpeg, and MoviePy code
5. persist enough state to resume, undo, redo, inspect, preview, and export

## Runtime Entry Points

The Typer app in `main.py` exposes:

| Command | Purpose |
|---|---|
| `vex` | Start the default interactive REPL |
| `vex web` | Start the local browser app |
| `vex start <video_path>` | Create a project and open the REPL |
| `vex repl [--project TEXT]` | Open the REPL for an existing project |
| `vex run "<instruction>" --project TEXT` | Run one instruction and exit |
| `vex projects` | List saved projects |
| `vex export <preset> --project TEXT` | Export without entering the REPL |
| `vex shorts` | Generate a packaged shorts bundle |
| `vex auto-broll` | Apply stock B-roll inserts |
| `vex auto-visuals` | Apply generated supporting visuals |
| `vex youtube-shorts` | Download a YouTube video and run auto shorts |
| `vex --version` | Show the installed version |

## Configuration

Vex loads `.env` and environment variables through `config.py`.

Important settings:

| Setting | Purpose |
|---|---|
| `PROVIDER` | `gemini` or `claude` |
| `GEMINI_API_KEY` | Required when `PROVIDER=gemini` |
| `GEMINI_MODEL` | Gemini model used for planning, tool calls, and Gemini transcription |
| `ANTHROPIC_API_KEY` | Required when `PROVIDER=claude` |
| `CLAUDE_MODEL` | Claude model used when selected |
| `PEXELS_API_KEY` | Enables stock B-roll search |
| `AGENT_PROJECTS_DIR` | Project storage root |
| `FFMPEG_PATH` | FFmpeg executable |
| `BLENDER_PATH` | Blender executable |
| `WHISPER_MODEL` | Whisper model for local fallback transcription |
| `GEMINI_TRANSCRIPT_MAX_INLINE_MB` | Gemini inline video transcription size limit |
| `GEMINI_TRANSCRIPT_MAX_INLINE_DURATION_SEC` | Gemini inline video transcription duration limit |
| `VEX_WEB_MAX_UPLOAD_MB` | Web upload limit |
| `GENAI_TIMEOUT_SEC` | Gemini request timeout |
| `ANTHROPIC_TIMEOUT_SEC` | Claude request timeout |
| `LLM_REQUEST_MAX_RETRIES` | Provider retry count |

Startup validates provider selection, required API keys, FFmpeg availability, and the project storage directory.

## Web App Flow

`vex web` creates the provider, optionally loads an existing project, then starts `run_web_app()` in `web_app.py`.

Default bind:

```text
http://127.0.0.1:8765
```

Options:

```bash
vex web --project <project-id>
vex web --host 127.0.0.1
vex web --port 8766
vex web --no-open
```

### Browser UI

The UI lives in `web_static/index.html`.

Current structure:

- sidebar with `New session`, `Projects`, `Exports`, `Queue`, `Settings`, `Tips & Tricks`, and recent projects
- empty state centered around video upload
- chat-focused loaded state with the video preview at the top
- fixed composer with attach, prompt input, model label, and run button
- compact command summary that stays collapsed by default
- expandable tool trace rows with full error detail inline
- Tips & Tricks page listing common editing, transcript, audio, shorts, B-roll, generated-visual, and export prompts

The loaded view keeps project controls minimal. Upload happens through the composer. Export happens through the video area.

### Web API

`web_app.py` serves a local JSON and media API:

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | Return provider, model, selected project, recent projects, and UI-ready metadata |
| `POST /api/upload` | Accept raw binary upload with filename headers |
| `POST /api/load` | Load a local path or YouTube URL |
| `POST /api/new-session` | Clear the selected project |
| `POST /api/select` | Select a saved project |
| `POST /api/jobs` | Start an agent job and return immediately with `job_id` |
| `GET /api/jobs/<job_id>/events` | Stream job progress over Server-Sent Events |
| `GET /api/projects/<id>/media/current` | Stream the current working video |
| `GET /api/projects/<id>/download/current` | Download the current working video |
| `GET /api/projects/<id>/download/latest-export` | Download the latest export when available |

### Upload Intake

The web upload path:

1. browser sends raw video bytes with filename and content length headers
2. server validates extension and upload size
3. server writes a temporary upload file
4. server creates a new project under `AGENT_PROJECTS_DIR`
5. source video is copied into the project as `source_<safe_filename>`
6. metadata is probed
7. output directory is set to `<working_dir>/outputs`
8. server returns the loaded project state

Supported extensions:

```text
.mp4 .mov .avi .mkv .webm .m4v .flv
```

### Live Jobs

The browser never waits on a blocking chat endpoint.

The flow is:

1. `POST /api/jobs` starts a background agent run
2. the API returns `job_id`
3. the browser opens `GET /api/jobs/<job_id>/events`
4. the server streams events until result or error

Events include:

- `started`
- `trace`
- `tool_start`
- `tool_finish`
- assistant text chunks
- `state`
- `result`
- `error`

Only one active job is allowed per project. A second job for the same project returns `409`.

### Preview and Download Safety

Media endpoints only serve files that belong to the selected project workspace.

The UI can preview:

- the current `state.working_file`
- refreshed media after each successful edit

The UI can download:

- current working video
- latest export when `state.artifacts["latest_export"]` exists

## Terminal REPL Flow

The REPL supports natural language and slash commands.

Before user text reaches the agent, the REPL checks for:

- local video paths
- quoted Windows paths
- Unix paths
- supported video extensions
- YouTube URLs

If a referenced local file already belongs to a project, Vex loads that project. Otherwise, Vex creates a new project.

If a YouTube URL is referenced, Vex downloads it through `yt-dlp`, stores source URL artifacts, creates or reuses a project, then continues with the user's instruction.

Slash commands:

| Command | Action |
|---|---|
| `/status` | Show project summary |
| `/timeline` | Show timeline |
| `/undo` | Undo last edit |
| `/redo` | Redo last undone edit |
| `/export <preset>` | Export current project |
| `/provider` | Show provider and model |
| `/projects` | List projects |
| `/trace` | Show latest agent trace |
| `/help` | Show commands |
| `/quit` or `/exit` | Save and exit |

## Agent Loop

`VideoAgent` in `agent.py` owns the provider-agnostic loop.

Per turn:

1. append the user message to session context
2. build a system prompt with current project facts
3. send messages and tool schemas to the active provider
4. stream assistant text when available
5. execute requested tools in order
6. append tool results back into the provider conversation
7. refresh project state after mutating tools
8. stop with a final assistant response or a surfaced tool error

The loop is capped to prevent runaway tool recursion.

Tool failures are surfaced directly. The web UI stores long details in trace metadata so the user can expand and read the full error inline.

## System Prompt

`prompts.py` builds the agent instructions and tool schemas.

The prompt includes current project facts:

- project name
- provider and model
- working file
- duration
- resolution
- fps
- timeline operation count
- last operation

It also gives routing rules. Examples:

- use `remove_segment` when the user wants to cut out a middle section
- use `transcribe_video` before `burn_subtitles` if captions are requested and no SRT path exists
- prefer Gemini video transcription for short clips when available
- treat Whisper as a local fallback
- keep final responses concise and grounded in the actual tool result

## Provider Layer

Vex has a shared provider interface with Gemini and Claude adapters.

### Gemini

The Gemini adapter:

- creates a `google-genai` client
- converts Vex schemas to Gemini function declarations
- sanitizes schema fields for Gemini compatibility
- streams partial assistant text
- accumulates tool calls across chunks
- preserves function-call metadata required by Gemini follow-up messages
- enables thinking config only for models that support it

Gemini is also used by `transcribe_video` for short video transcription when the active model supports video input and the file is within configured inline limits.

### Claude

The Claude adapter:

- creates an Anthropic client
- converts Vex schemas to Claude tools
- converts neutral messages into Claude-native content blocks
- streams text
- extracts final tool calls

## Project State

Every project is a `ProjectState` persisted to disk.

Stored fields include:

- `project_id`
- `project_name`
- `created_at`
- `updated_at`
- `source_files`
- `working_file`
- `working_dir`
- `output_dir`
- `timeline`
- `redo_stack`
- `session_log`
- `metadata`
- `provider`
- `model`
- `artifacts`

Common artifacts:

- `transcript_txt`
- `transcript_srt`
- `latest_export`
- `export_history`
- auto shorts manifests
- auto B-roll manifests
- auto visuals manifests
- latest agent trace

The original source file is never edited. A project copies the source into the workspace and all later edits derive from the current working copy.

## Timeline, Undo, and Redo

State-changing tools append timeline operations.

Each operation records:

- operation name
- normalized parameters
- timestamp
- result file
- human-readable description

Undo rebuilds the project from the original project source by replaying all timeline operations except the removed step.

Replay support includes:

- `trim_clip`
- `remove_segment`
- `merge_clips`
- `adjust_speed`
- `add_transition`
- `add_text_overlay`
- `replace_audio`
- `mute_segment`
- `trim_silence`
- `burn_subtitles`
- `summarize_clip`

Redo reapplies the most recently undone operation.

## Execution Engine

`engine.py` owns deterministic media operations.

Shared behavior:

- generate unique output paths
- call FFmpeg, ffprobe, or MoviePy
- raise `VideoEngineError` on failure
- return the new output path on success

### Metadata

`probe_video()` uses `ffprobe` to read:

- duration
- fps
- width
- height
- codec
- audio presence
- file size
- container format

### Timestamp Parsing

`parse_timestamp()` supports:

- seconds such as `30`
- suffixed seconds such as `30s`
- `MM:SS`
- `HH:MM:SS`
- decimals

### Trim and Remove Segment

`trim()` keeps one selected range.

`remove_segment()` removes a selected range and joins the before and after portions into a new working file.

### Merge

`merge()` normalizes clips before concat:

- common resolution
- padding when needed
- fps normalization
- audio resampling
- silent audio synthesis when a clip has no audio

### Extract Segments

`extract_segments()` builds highlight cuts by trimming selected ranges and merging them.

### Speed

`adjust_speed()` supports full-clip and segment-only speed changes. Audio tempo filters are chained so FFmpeg stays within supported ranges.

### Transitions

Vex supports:

- `fade_in`
- `fade_out`
- fade-through-black behavior for single-clip crossfade requests

### Text Overlays

Text overlays use MoviePy.

The implementation handles current MoviePy APIs and older MoviePy installs, including method naming differences such as `with_*` and `set_*`.

### Audio

Audio helpers include:

- extraction to `mp3`, `wav`, or `aac`
- full audio replacement
- mixed replacement with original audio
- segment muting
- silent audio synthesis when needed

### Silence Trimming

`trim_silence()`:

1. runs FFmpeg `silencedetect`
2. parses silence windows
3. builds keep segments
4. preserves speech padding
5. merges nearby cuts
6. renders the final cut through segment extraction

### Subtitle Burning

`burn_subtitles()` uses FFmpeg `subtitles` filter and force-style settings for:

- font size
- primary text color
- outline color
- subtitle position
- path escaping

### Export

`export()` applies preset settings and streams FFmpeg progress by parsing time markers.

`tools/export.py` stores:

- `state.artifacts["latest_export"]`
- `state.artifacts["export_history"]`

## Tool Execution Model

Tools live in `tools/` and return a standard payload:

- `success`
- `message`
- `suggestion`
- `updated_state`
- `tool_name`

Mutating tools update `working_file`, refresh metadata, append timeline operations, and save state.

### Tool Breakdown

| Tool | Behavior |
|---|---|
| `get_video_info` | Probe current video and refresh metadata |
| `trim_clip` | Keep a selected time range |
| `remove_segment` | Cut out a middle section and keep the rest |
| `merge_clips` | Merge the working file with external clips |
| `adjust_speed` | Change speed globally or within a segment |
| `add_transition` | Add fade behavior |
| `add_text_overlay` | Render timed text on top of the video |
| `extract_audio` | Export audio without changing the timeline |
| `replace_audio` | Replace or mix audio and record the edit |
| `mute_segment` | Silence a selected time range |
| `trim_silence` | Remove detected dead-air gaps |
| `transcribe_video` | Generate transcript artifacts through Gemini video input or Whisper fallback |
| `burn_subtitles` | Burn an SRT into the current video |
| `summarize_clip` | Build a shorter cut from transcript-selected ranges |
| `create_auto_shorts` | Generate ranked vertical shorts and metadata bundle |
| `add_auto_broll` | Plan, fetch, rerank, and composite stock B-roll |
| `add_auto_visuals` | Plan, render, validate, and composite generated visuals |
| `export_video` | Export with a preset and persist latest export artifacts |
| `undo` | Rebuild project without the last operation |
| `redo` | Reapply the last undone operation |

## Transcription Flow

`transcribe_video` chooses the engine based on request, provider, and file limits.

Gemini path:

1. verify the active provider/model can be used for Gemini video transcription
2. check file duration and size limits
3. send inline video data to Gemini
4. require structured transcript content
5. write `transcript.txt`
6. write `transcript.srt`
7. store transcript artifacts

Whisper path:

1. import local Whisper
2. load `WHISPER_MODEL`
3. transcribe the current working file
4. write the same transcript artifacts

Whisper is optional. It is useful for long clips, larger files, local-only transcription, or fallback.

## Auto Shorts

The auto shorts flow:

1. ensures transcript artifacts exist
2. mines timestamped transcript windows
3. asks the active provider to select strong short candidates
4. scores selected clips with explainable viral factors
5. renders vertical captioned shorts
6. writes transcript, metadata, notes, and a manifest bundle
7. stores the latest manifest path in project artifacts

Generated shorts are deliverables. They do not replace the active working file by default.

## Auto B-Roll

The B-roll flow:

1. ensures `transcript.srt` exists
2. asks the active provider for useful B-roll beats and search queries
3. falls back to heuristics if model output is unusable
4. searches Pexels when `PEXELS_API_KEY` is configured
5. reranks stock candidates against transcript context
6. downloads and caches selected MP4 assets
7. overlays them in subtitle-aligned windows
8. preserves original source audio
9. writes manifest, notes, and attribution
10. records the operation in the timeline

## Auto Visuals

The generated-visual pipeline:

1. ensures transcript artifacts exist
2. turns transcript sentences into visual cards
3. scores cards for visualizability, safety, specificity, and usefulness
4. plans only the strongest beats
5. normalizes the plan into renderer-aware specs
6. chooses Manim, FFmpeg, or Blender based on the spec and installed tools
7. validates generated scenes
8. composites accepted visuals back into the working video

Renderer roles:

- `manim`: premium explainer scenes, diagrams, comparisons, process visuals, timelines
- `ffmpeg`: fast editorial cards and picture-in-picture support graphics
- `blender`: optional cinematic generated replacement shots

## Export Presets

Presets live in `presets/export_presets.json`.

Current built-ins:

- `youtube_1080p`
- `youtube_4k`
- `instagram_reels`
- `instagram_square`
- `tiktok`
- `twitter_x`
- `podcast_audio`
- `custom`

Preset fields can include resolution, video codec, audio codec, video bitrate, audio bitrate, fps, output format, and audio-only behavior.

## Trace and Streaming UX

`agent_trace.py` records structured events for both terminal and web.

Terminal UX:

- Rich spinner while a tool run is active
- streaming assistant text
- `/trace` panel for recent events

Web UX:

- SSE job stream
- compact command summary in chat
- pulsing running indicator while tools execute
- command count and error count
- collapsed tool cards by default
- expandable full error details
- final state refresh after successful edits

Trace event detail is preserved in metadata so the UI can show a short row and a full expanded body.

## Reliability Model

Vex does not rely on model memory for edit state.

Reliability comes from:

- structured project JSON
- explicit tool schemas
- deterministic engine functions
- standardized tool results
- provider abstraction
- source file protection
- timeline replay for undo and redo
- artifact paths for transcripts, exports, shorts, B-roll, visuals, and traces
- web media path checks that keep downloads inside the project workspace

## Limitations

Current limitations:

- FFmpeg must be installed
- selected provider API key must be valid
- Gemini video transcription is limited by configured inline size and duration
- Whisper is required only when using local fallback transcription
- subtitle burning depends on FFmpeg subtitle filter support
- MoviePy text rendering can depend on local font/rendering support
- very long conversations can still drift on preferences that are not represented in project state
- undo replay depends on required source assets still existing
- web app is local-only and has no authentication because it binds to `127.0.0.1` by default
- no reliable cancellation for running jobs yet

## Extension Contract

To add a new editing capability:

1. add the deterministic media operation in `engine.py`
2. add a tool executor in `tools/`
3. register the schema in `prompts.py`
4. register the executor in `tools/__init__.py`
5. add undo replay support in `tools/undo.py` if it mutates the timeline
6. expose any user-facing behavior in `README.md`
7. update the web UI if the new tool changes visible project state, progress, artifacts, or download behavior
8. add focused tests in `tests/`

## Current Test Map

Relevant test areas:

- web API upload, state, jobs, concurrency, media, and download checks in `tests/test_web_app.py`
- config and visual IR checks in `tests/test_config_and_visual_ir.py`
- FFmpeg and engine behavior in `tests/test_engine_ffmpeg.py`
- provider and agent behavior in the rest of `tests/`

Recommended verification:

```bash
python -m py_compile main.py engine.py web_app.py config.py
python -m ruff check main.py engine.py web_app.py config.py tools/export.py tests/test_web_app.py tests/test_config_and_visual_ir.py
python -m pytest
```

## Short Version

Vex is a structured local video editing system.

The user talks to a chat UI or terminal REPL. The model chooses validated tools. The tools update persistent project state. The engine performs deterministic media operations. The web app streams progress, previews the current cut, and delivers exports.
