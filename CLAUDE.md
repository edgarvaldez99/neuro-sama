# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI-VTuber Twitch chat bot ("Mai-chan" / Neuro-Sama style). It reads Twitch chat **and** the
streamer's microphone, generates a character response via a local LLM, synthesizes speech, drives a
VTube Studio avatar's emotion, and plays the audio back (routed into OBS/VTube Studio via a virtual
audio cable). Forked from upstream [Kuebiko](https://github.com/adi-panda/Kuebiko) — the `README.md`
is the upstream's and is **out of date**; trust the code and `docs/` over it.

The migration to a **100% local / free stack is essentially complete**: the old paid-cloud modules
(OpenAI, ElevenLabs, Cartesia, Google TTS, Speaker.bot, the legacy `queue_consumer` system) were
**deleted** in commit `b5fd38c` ("migra a stack 100% local y limpia codigo/deps legacy"). Only the
local pipeline remains. The lone online dependency is Edge TTS (Microsoft voices), which is the default
TTS but can be swapped for fully-offline Piper.

## Commands

```sh
poetry install                      # install deps (requires VLC installed on the OS for playback)
poetry run python main.py           # run the bot (no flags/modes — see Architecture)
poetry run python -m src.check_setup # diagnose setup: checks .env, files, Ollama, VTS before launch

poetry run black .                  # format
poetry run isort .                  # sort imports
poetry run flake8                   # lint (config in .flake8)
poetry run mypy src                 # type check (config in mypy.ini)
poetry run pylint src               # lint (config in pyproject.toml; tuned to match flake8/VSCode)
```

There is **no test suite** and `pytest` is not configured.

External services / assets the bot expects locally:
- **Ollama** at `http://127.0.0.1:11434` serving the model named by `OLLAMA_MODEL` (default
  `qwen2.5:3b`). The bot calls `/api/chat` in **JSON mode** (`format: "json"`) — the system prompt
  must instruct the model to return JSON.
- **Faster-Whisper** for STT runs on an **NVIDIA GPU via CUDA** (`device="cuda"`, `float16`). On
  Windows the CUDA DLLs ship as the `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` pip packages and
  `src/stt_local.py` patches them onto the DLL search path at import time (fixes `cublas64_12.dll not
  found`). The Whisper model auto-downloads to `models/stt/` on first run.
- **VTube Studio** with its plugin API enabled on `VTS_PORT` (default 8001), for avatar emotion
  hotkeys. Optional — the bot runs fine without it (`check_setup` treats it as a warning, not an error).
- **Piper voice files** at `models/tts/es_MX-ald-medium.onnx` (+ `.onnx.json`) — only needed if
  `TTS_ENGINE=piper`. Not committed.

## Configuration

- Copy `.env.example` → `.env`. Loaded via `python-decouple` in `src/credentials.py` and read
  ad-hoc (via `decouple.config`) in `src/tts.py`, `src/vts_controller.py`, `src/chat_ollama.py`. Vars:
  - `TWITCH_TOKEN`, `TWITCH_CHANNEL`, `BOT_NAME` — required (Twitch identity).
  - `OLLAMA_MODEL` — Ollama model tag (default `qwen2.5:3b`; sized for ~6GB VRAM GPUs).
  - `TTS_ENGINE` — `edge` (default, online) or `piper` (offline).
  - `VTS_PORT` — VTube Studio API port (default 8001).
- `main.py` sets `os.environ["BASE_DIR_PATH"] = os.getcwd()`. Many modules read this to resolve paths
  (audio output, `prompt_chat.txt`, `emotion_hotkeys.json`), so the bot **must be launched via
  `main.py`** — running a submodule directly will misresolve paths. (`check_setup` is the exception;
  it's meant to run standalone with `python -m src.check_setup`.)
- `prompt_chat.txt` (repo root) is the system prompt / character definition, loaded fresh on start.
  It must instruct the LLM to reply as JSON `{"response_text": ..., "emotion": ...}` (see flow below).
- `filter.json` (repo root) backs `src/filter_message.py` (blacklist / ignore-list for chat).

## Architecture

### Entry point — two concurrent input loops, one output pipeline

`main.py` is now a flat async launcher (the old `Mode` enum / `VLC_CLOUD`/`SPEAKER`/`STREAMER` switch
is **gone**). It cleans the `audios/` folder, then runs two producers against one shared `Bot`:

1. `asyncio.create_task(bot.start())` — the twitchio bot listening to **Twitch chat**.
2. `await stt.listen_loop()` — `LocalSTT` (`src/stt_local.py`) listening to the **microphone**.

Both feed the **same** `asyncio.Queue` on the `Bot`, so chat and voice are serialized through one
response pipeline (no overlapping audio).

### Response pipeline (`src/twitchbot.py`)

`Bot` extends `twitchio.ext.commands.Bot`. Flow is async + queue-based so the LLM/TTS never block the
event loop:

1. `event_message` (chat) → `message_queue.put_nowait` (drops on `QueueFull`, maxsize 20).
   `inject_mic_message` (voice) does the same, wrapping the text in a `FakeMessage`.
2. `message_worker` (one background task started on `event_ready`) pops messages **one at a time** and
   calls `process_message`, guaranteeing sequential responses.
3. `process_message`:
   - filters via `src/filter_message.py`;
   - runs the blocking `ollama_completion` via `asyncio.to_thread`;
   - the reply is JSON — parsed into `response_text` (spoken) and `emotion` (`happy`/`sad`/`angry`/
     `surprised`/`neutral`). `strip_cjk` (`src/utils.py`) scrubs stray CJK chars qwen sometimes emits;
   - appends to the **class-level** `Bot.conversation` history (trimmed to `CONVERSATION_LIMIT = 20`,
     dropping the oldest user+assistant pair);
   - fires `vts.trigger_emotion(emotion)` as a background task (not awaited — don't delay audio);
   - sets `self.is_speaking = True` around `get_speech_by_text(...)`, then back to `False`.
4. **TTS dispatch:** `src/tts.py` (`get_speech_by_text`) picks the engine by `TTS_ENGINE` and delegates
   to `texttospeech_edge.py` or `texttospeech_piper.py`. Each synthesizes a timestamped file under
   `audios/` (`.mp3` for Edge, `.wav` for Piper) and hands it to `src/generate_audio.py`.
5. **Playback:** `generate_audio.py` `play_audio` plays with python-vlc, waiting for the file to be
   playing then finished. It keeps a rotating history of the last 3 files and deletes older ones with
   retry (VLC releases the Windows file handle lazily → `WinError 32`; `_remove_with_retry` polls).

**`is_speaking` is the anti-echo flag:** while the bot is playing audio, `LocalSTT.listen_loop` throws
away mic input so the bot doesn't transcribe and answer its own voice.

### STT (`src/stt_local.py`)

A simple amplitude-based VAD: continuously reads the mic (must read constantly or the Windows audio
driver blocks), accumulates frames once amplitude crosses `silence_threshold`, and after
`silence_chunks` (~2.5s) of silence transcribes the buffer with Faster-Whisper (`language="es"`,
`asyncio.to_thread`), then `inject_mic_message`s the text. Tuning knobs (`MODEL_SIZE`,
`silence_threshold`, `silence_chunks`) are module constants — see `docs/REPORTE_MEJORAS_STT_AUDIO.md`.

### VTS emotions (`src/vts_controller.py`)

A singleton `VTSController` (via `get_vts_instance`, lock-guarded) connects + authenticates to VTube
Studio (token cached in `vts_token.txt`; popup re-auth if revoked). Each model names its hotkeys
differently, so `trigger_emotion` resolves the abstract emotion → a real hotkey **by keyword matching**
(`EMOTION_KEYWORDS`) against the model's hotkey list. Resolved mappings are written to
`emotion_hotkeys.json` as an editable per-model override scaffold. Falls back to activating a matching
`.exp3.json` expression directly if no hotkey matches.

### Component map (all modules below are active — there is no longer a legacy column)

| Concern | Module |
|---|---|
| Entry / orchestration | `main.py`, `twitchbot.py` (asyncio.Queue, shared by chat + mic) |
| LLM | `chat_ollama.py` (Ollama HTTP, JSON mode) |
| STT (mic in) | `stt_local.py` (Faster-Whisper, CUDA GPU) |
| TTS dispatch | `tts.py` → `texttospeech_edge.py` (default, online) / `texttospeech_piper.py` (offline) |
| Audio out | `generate_audio.py` (python-vlc + `audios/` rotation) |
| Avatar | `vts_controller.py` (VTube Studio emotion hotkeys) |
| Text utils | `utils.py` (`open_file`, `strip_cjk`, `clean_text_for_tts`) |
| Chat filtering | `filter_message.py` (+ `filter.json`) |
| Config / types | `credentials.py`, `chattypes.py`, `logger.py` |
| Setup diagnostics | `check_setup.py` |

`chattypes.py` defines the `ChatCompletionMessage` shape used for history. `logger.py` is a colored
logger; `chat_ollama.ollama_completion` takes an optional `logger` but the active path passes none and
falls back to `print`.

## Conventions

- Code comments and most docstrings/log strings are in **Spanish**; match the surrounding language.
- twitchio, pyvts, vlc and other untyped imports use `# type: ignore`; flake8 line-length is `B950`
  (relaxed E501); black/isort/pylint all target line length 88.
- The local-stack modules are sprinkled with `print("DEBUG: ...")` calls — intentional WIP diagnostics
  (audio playback and STT were heavily debugged; see `docs/REPORTE_MEJORAS_STT_AUDIO.md`).
- Background tasks keep a **strong reference** in a module/instance-level `set` with a `done_callback`
  that discards it — the event loop only holds weak refs, so without this the GC can kill an in-flight
  task. Follow this pattern (`_spawn_background`, `_background_tasks`) when spawning fire-and-forget work.
- `Bot.conversation` is **class-level** — history is global, intentionally shared across the chat and
  mic inputs.

## Direction

`docs/PLAN_NEURO_V2.md` is the design doc for a planned v2 rewrite (multimodal Qwen3-Omni engine,
priority queue with paid-message auctioning, Discord voice, Silero VAD barge-in interruptions, VTube
Studio emotion hotkeys, SQLite persistence). It describes a **target architecture, not the current
code** — that module structure does not exist yet.
