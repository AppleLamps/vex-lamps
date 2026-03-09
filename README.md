# Vex

Vex is an open-source AI video editing agent for the terminal. You talk to it in plain English, point at a video file, and it plans and executes editing operations on a safe working copy of your footage.

It supports interactive editing, persistent project state, undo/redo by timeline rebuild, preset exports, optional local transcription, and multi-provider LLM backends through a clean provider abstraction.

## What Vex Can Do

Vex can:

- inspect video metadata
- trim clips by natural-language timestamps
- merge clips
- change speed for a full clip or a segment
- add fade in / fade out / fade-through-black transitions
- add timed text overlays
- extract, replace, mix, and mute audio
- export for YouTube, Instagram, TikTok, X, podcast audio, or custom settings
- transcribe video locally with Whisper
- persist projects and resume later
- undo and redo edits safely without touching originals

## Why Vex

- Natural language first: type what you want instead of memorizing editing commands
- Original files stay untouched: all edits run against a working copy
- Terminal-native workflow: fast, scriptable, and easy to automate
- Provider-agnostic brain: Gemini or Claude behind the same editing loop
- Stateful projects: close the terminal and continue later

## Quick Start

Install Vex in editable mode:

```bash
pip install -e .
```

Then launch it:

```bash
vex
```

If no project is loaded, just type naturally and include a video path in your message:

```text
Vex > trim the first 30 seconds of "D:\videos\clip.mp4"
Vex > export it for instagram
Vex > /quit
```

If Vex already has exactly one saved project, it resumes it automatically. If you have multiple saved projects, Vex starts clean and waits for you to reference a file or explicitly open a project.

## Installation

### Requirements

- Python 3.11+
- FFmpeg installed and available on `PATH`

FFmpeg install:

- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows: install from `https://ffmpeg.org/download.html` and add `ffmpeg/bin` to `PATH`

### Install Vex

```bash
git clone https://github.com/AKMessi/vex.git
cd vex
pip install -e .
```

### Windows PATH Note

If `vex` is not recognized after install, add your Python user Scripts directory to `PATH`. In this environment it is:

```text
C:\Users\aarya\AppData\Roaming\Python\Python314\Scripts
```

Your exact path may differ depending on your Python install.

## Configuration

Copy the example environment file and fill in the provider you want:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Set one of:

- `PROVIDER=gemini`
- `PROVIDER=claude`

Required keys:

- Gemini: `GEMINI_API_KEY`
- Claude: `ANTHROPIC_API_KEY`

Important shared settings:

- `AGENT_PROJECTS_DIR`
- `FFMPEG_PATH`
- `WHISPER_MODEL`

## Everyday Usage

### Zero-Setup Conversational Flow

This is the intended default experience:

```text
> vex

[Vex banner]
Vex > trim the first 30 seconds of "D:\videos\clip.mp4"
Vex > export it for instagram
Vex > /quit
```

Rules of thumb:

- In the REPL, type natural language
- Include a video path when no video is loaded
- Do not type `vex start ...` or `vex projects` inside the REPL
- Use slash commands inside the REPL, not CLI commands

### What to Type in the REPL

Good:

```text
Vex > trim the first 5 seconds of "D:\videos\clip.mp4"
Vex > add "TechWithAlex" at the bottom for the first 5 seconds
Vex > mute from 0:12 to 0:18
Vex > export it for youtube
```

Wrong inside the REPL:

```text
Vex > vex start clip.mp4
Vex > vex projects
Vex > vex repl
```

Those are shell commands, not REPL messages.

## CLI Commands

Vex has a conversational default mode plus power-user commands.

### `vex`

Starts the interactive REPL.

- resumes the only saved project automatically
- otherwise waits for a natural-language instruction containing a video path

### `vex start <video_path> [--name TEXT]`

Explicitly create a new project from a video and drop into the REPL.

Example:

```bash
vex start "D:\videos\clip.mp4" --name "My Vlog"
```

### `vex repl [--project TEXT]`

Open the REPL for an existing project.

Examples:

```bash
vex repl
vex repl --project 7e5a4d1c
```

### `vex run "<instruction>" --project TEXT`

Run one instruction against a saved project and exit.

Example:

```bash
vex run "export it for instagram" --project 7e5a4d1c
```

### `vex projects`

List saved projects.

### `vex export <preset_name> --project TEXT [--output TEXT]`

Export directly without entering the REPL.

Example:

```bash
vex export instagram_reels --project 7e5a4d1c --output "D:\exports\clip.mp4"
```

### `vex --version`

Show the installed version.

## REPL Slash Commands

These work only inside the interactive session:

| Command | Action |
|---|---|
| `/status` | Show the current project summary |
| `/timeline` | Show the applied edit timeline |
| `/undo` | Undo the last edit |
| `/redo` | Redo the last undone edit |
| `/export <preset>` | Export immediately using a preset |
| `/provider` | Show the active provider and model |
| `/projects` | List saved projects |
| `/help` | Show available slash commands |
| `/quit` or `/exit` | Save and exit |

## Export Presets

Built-in presets:

| Preset | Description | Format |
|---|---|---|
| `youtube_1080p` | YouTube 1080p HD | `mp4` |
| `youtube_4k` | YouTube 4K UHD | `mp4` |
| `instagram_reels` | Instagram Reels / Stories vertical | `mp4` |
| `instagram_square` | Instagram square feed | `mp4` |
| `tiktok` | TikTok vertical | `mp4` |
| `twitter_x` | X / Twitter landscape | `mp4` |
| `podcast_audio` | Audio-only podcast export | `mp3` |
| `custom` | Start from your own settings | variable |

## Real Examples

### Trim a clip from scratch

```text
Vex > trim the first 30 seconds of "D:\videos\clip.mp4"
```

### Add a title card

```text
Vex > add "DealScout" at the bottom for the first 4 seconds
```

### Fix pacing

```text
Vex > speed up the section from 1:10 to 1:35 by 1.25x
```

### Export for social

```text
Vex > export it for instagram
```

### Direct shell-based workflow

```bash
vex start "D:\videos\clip.mp4"
vex export youtube_1080p --project 7e5a4d1c
```

## How Project Loading Works

- Vex never edits your original file directly
- each project keeps:
  - original source file path
  - working copy path
  - timeline of operations
  - provider/model info
  - session history
- if you reference a video path in the REPL:
  - Vex first checks whether a saved project already exists for that exact source file
  - if yes, it loads that project
  - if no, it creates a new project automatically

Project state is stored in:

```text
~/.video-agent/projects/
```

unless overridden via `AGENT_PROJECTS_DIR`.

## Architecture

Vex is organized into a few clear layers:

- `main.py`
  CLI, REPL, auto-loading, slash commands, Rich terminal UX
- `agent.py`
  provider-agnostic agent loop and tool execution orchestration
- `providers/`
  Gemini and Claude adapters behind a shared interface
- `tools/`
  editing actions exposed to the model
- `engine.py`
  FFmpeg and MoviePy integration
- `state.py`
  persistent project model and undo/redo state
- `presets/export_presets.json`
  export targets for common platforms

## Known Requirements and Limitations

### FFmpeg is mandatory

Vex depends on FFmpeg for probing, trimming, merging, audio work, and export.

### Text overlays on Windows may require ImageMagick

`moviepy` text rendering on Windows can require ImageMagick.

If timed text overlays fail, install ImageMagick from:

```text
https://imagemagick.org/script/download.php#windows
```

During installation, enable legacy utilities if prompted.

### Whisper is optional

`transcribe_video` works only if `openai-whisper` is installed and your environment can run it.

## Troubleshooting

### `vex` is not recognized

Add your Python Scripts directory to `PATH`, then restart the terminal.

### `FFmpeg was not found in PATH`

Install FFmpeg and verify `ffmpeg` works in the terminal before starting Vex.

### Vex says no video is loaded

Type a normal sentence that includes a file path:

```text
Vex > trim the first 10 seconds of "D:\videos\clip.mp4"
```

### A random old project was loaded before

That behavior has been tightened. Vex now only auto-resumes when there is exactly one saved project. If multiple projects exist, it starts clean.

## Contributing

Issues, bug reports, and PRs are welcome. If you report a bug, include:

- your OS
- Python version
- provider (`gemini` or `claude`)
- the exact command or REPL input
- the full traceback if one exists

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
