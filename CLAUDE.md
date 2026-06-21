# CLAUDE.md

AI-VTuber Twitch bot ("Mai-chan", Neuro-Sama style), forked from
[Kuebiko](https://github.com/adi-panda/Kuebiko). Reads Twitch chat + the streamer's mic
(+ optionally the screen), generates an in-character reply via a local LLM, synthesizes speech,
drives a VTube Studio avatar's emotion, and plays the audio back (routed into OBS/VTS via a virtual
audio cable). The stack is **100% local/free** (the old paid-cloud modules — OpenAI, ElevenLabs,
Cartesia, Google TTS, Speaker.bot — were deleted in commit `b5fd38c`); the only online piece is
Edge TTS, swappable for fully-offline Piper.

`README.md` is the upstream's and is **out of date** — trust the code and `docs/` over it.

## Environment (not obvious from the code)

- **Windows-only in practice:** playback needs **VLC installed on the OS**; STT and vision need an
  **NVIDIA GPU + CUDA**; `pycaw`, `PIL.ImageGrab`, the Win32 media key and the `WinError 32`
  file-handle dance are all Windows-specific.
- **Ollama runs in WSL2** (dev) at `http://127.0.0.1:11434`. The `qwen3-vl` vision models need a
  **recent Ollama** (>= 0.30; v0.5.7 rejects them with HTTP 412). Update with
  `wsl -e bash -c "curl -fsSL https://ollama.com/install.sh | sh"`. **Use the `-instruct`
  variant** (`qwen3-vl:4b-instruct` / `:8b-instruct`) — the plain `qwen3-vl:4b` is the *thinking*
  variant and hangs reasoning forever instead of emitting the description (`think:false` /
  `/no_think` don't stop it in this build).
- **Two machines, one codebase:** dev = this PC (**GTX 1660 6GB**), prod = another PC
  (**RTX 3090 24GB**). All models/params come from `.env`, so the same code runs on both — code
  defaults target the 3090; the dev `.env` overrides down to smaller models.
- **CUDA DLLs on Windows** ship as the `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` pip packages;
  `src/stt_local.py` patches them onto the DLL search path at import time (fixes
  `cublas64_12.dll not found`).
- **Launch only via `main.py`:** it sets `BASE_DIR_PATH=cwd`, which many modules use to resolve
  paths (`prompt_chat.txt`, `audios/`, `emotion_hotkeys.json`). Running a submodule directly
  misresolves paths. Exception: `check_setup` (`python -m src.check_setup`).
- **No test suite**; `pytest` is not configured.

## Commands

```sh
poetry install
poetry run python main.py            # run the bot
poetry run python -m src.check_setup # diagnose .env / Ollama / VTS before launch
poetry run python -m src.screen_vision   # standalone vision prototype (no bot)
poetry run black . && poetry run isort . && poetry run flake8 && poetry run mypy src && poetry run pylint src
```

## Config & contracts (`.env`, via `python-decouple`)

- Required: `TWITCH_TOKEN`, `TWITCH_CHANNEL`, `BOT_NAME`. Copy `.env.example` → `.env` (gitignored;
  the real one also holds dead legacy cloud keys — ignore them).
- `prompt_chat.txt` (repo root) is the character/system prompt; it **must** make the LLM reply as
  JSON `{"response_text": ..., "emotion": ...}` — the bot calls Ollama in JSON mode and parses that.
- `filter.json` backs `src/filter_message.py` (chat blacklist/ignore-list).
- Optional subsystems are **off by default** and `.env`-gated: vision (`VISION_ENABLED`), media
  control (`MEDIA_CONTROL_ENABLED`), attention mode (`ATTENTION_MODE`). See `.env.example` and
  `docs/plan_vision_general.md`.

## Architecture (only the non-obvious bits)

Up to four producers feed **one shared `asyncio.PriorityQueue`** on the `Bot`, so all inputs are
serialized through a single response pipeline (never overlapping audio):
- chat (`event_message`), mic (`LocalSTT.listen_loop` → `inject_mic_message`), vision
  (`ScreenVision.watch_loop` → `inject_vision_message`, only when `VISION_ENABLED`), and the
  optional `director_loop` (proactive, only when `DIRECTOR_ENABLED`).
- Queue items are `(priority, seq, message)`. `ATTENTION_MODES` sets each source's priority per mode
  (`VIDEO_FIRST` / `CHAT_FIRST` / `HYBRID`); the mic is always first; `seq` gives FIFO on ties.
  Switch live with `!mode video|chat|hybrid` (broadcaster only).
- **Commands (`!hola`, `!mode`) are NOT sent to the LLM** — handled in `event_message` and skipped
  from the queue.

Pipeline gotchas (`src/twitchbot.py`):
- `process_message` runs the blocking `ollama_completion` via `asyncio.to_thread`, parses the JSON
  reply (`strip_cjk` scrubs stray CJK chars qwen emits), and appends to the **class-level**
  `Bot.conversation` (history is global, shared across all inputs; trimmed to 20).
- **`is_speaking` is the anti-echo flag:** while true, `LocalSTT` and `ScreenVision` throw away their
  input so the bot never reacts to its own voice/output. Set around speech generation.
- **`MediaController`** (`src/media_controller.py`, **Level 1 only** — simulated inputs, no autonomous
  PC control) hooks around `get_speech_by_text` to **pause** (Win32 media key) or **duck** (`pycaw`,
  per-app volume) the playing video so it doesn't talk over Mai-chan. Technique is source-driven;
  whether to cut is gated by `_hay_dialogo()`. When `MEDIA_VAD_ENABLED`, that answer comes live from
  **`LoopbackVAD`** (`src/loopback_vad.py`): a background thread captures the WASAPI **loopback**
  (system audio) via **`pyaudiowpatch`** — the plain `pyaudio` can't do loopback on Windows — and runs
  **Silero VAD** (reused from `faster-whisper`, no new model dep) to detect *speech* (not energy), so
  music/SFX don't trigger a cut. It only updates a flag; the query is instant. Degrades gracefully to
  the `MEDIA_ASSUME_DIALOGO` heuristic if the dep/device is missing.
- **Vision is two-stage:** the VLM only *describes* the frame (objective, cheap); the personality LLM
  turns that into an in-character comment through the normal `process_message`. `scene_difference`
  skips unchanged frames (anti-spam).
- **Playback** (`generate_audio.py`) uses python-vlc, rotates the last 3 `audios/` files and retries
  deletes (VLC releases the Windows handle lazily → `WinError 32`).
- **Memory** (`src/memory.py`) is **SQLite from the stdlib** — no server, no deps; the DB file is
  `maichan_memory.db` (gitignored). Tables: `viewers` (new vs returning), `agenda` (today's plan,
  populated via `!agenda`), `stream_summaries`. On start the bot prepends a *session brief* (recent
  summaries + today's agenda) to the system prompt; on shutdown it generates and saves a one-line
  summary. The **`director_loop`** (opt-in, `DIRECTOR_ENABLED`) is a 4th producer that, when the
  queue is idle, enqueues a low-priority proactive action so the stream isn't silent.

## Conventions

- Comments / docstrings / log strings are in **Spanish** — match the surrounding language.
- Untyped imports (twitchio, pyvts, vlc, pycaw, decouple) use `# type: ignore`; line length 88
  (flake8 `B950` relaxes E501). Keep pylint at 10/10 — annotate intentional warnings inline.
- `print("DEBUG: ...")` calls are intentional WIP diagnostics, not leftover debugging.
- Fire-and-forget tasks must keep a **strong reference** (`_spawn_background` + `_background_tasks`):
  the event loop holds only weak refs, so the GC can kill an in-flight task otherwise.

## Direction (`docs/`)

- `PLAN_NEURO_V2.md` — target v2 rewrite (Qwen3-Omni, priority queue with paid-message auctions,
  Discord voice, Silero VAD barge-in, SQLite). **Design, not current code.**
- `plan_vision_general.md` — the general vision/reaction plan. Phases V2–V4 (vision integration,
  `MediaController`, attention modes) are **done**; V1 (qwen3-vl quality) and V5 (SQLite memory +
  `director_loop`) are pending. Supersedes the WoW-specific `plan_vision_wow.md`.
- `REPORTE_MEJORAS_STT_AUDIO.md` — STT/audio tuning notes.
