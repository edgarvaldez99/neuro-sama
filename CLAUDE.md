# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI-VTuber Twitch chat bot ("Mai-chan" / Neuro-Sama style). It reads Twitch chat, generates a
character response via an LLM, synthesizes speech, and plays it back (routed into OBS/VTube Studio via
a virtual audio cable). Forked from upstream [Kuebiko](https://github.com/adi-panda/Kuebiko) — the
`README.md` is the upstream's and is **out of date**; trust the code and `docs/` over it.

The project is mid-migration from paid cloud APIs (OpenAI, ElevenLabs, Google TTS) to a **100% local,
free stack** (Ollama + Piper TTS). Both the legacy and new code paths coexist; see Mode selection below.

## Commands

```sh
poetry install                 # install deps (requires VLC installed on the OS for the legacy/VLC path)
poetry run python main.py      # run the bot (mode is hardcoded in main.py — see below)

poetry run black .             # format
poetry run isort .             # sort imports
poetry run flake8              # lint (config in .flake8)
poetry run mypy src            # type check (config in mypy.ini)
```

There is **no test suite** despite `docs/` describing one as planned. `pytest` is not configured.

External services the bot expects to be running locally:
- **Ollama** at `http://127.0.0.1:11434` serving model `qwen2.5:14b` (see `src/chat_ollama.py`).
- **Piper voice model** files at `models/tts/es_MX-ald-medium.onnx` (+ `.onnx.json`), not committed.

## Configuration

- Copy `.env.example` → `.env` and fill credentials. `.env` is loaded via `python-decouple` in
  `src/credentials.py`. Note: the active local stack (Ollama + Piper) only needs `TWITCH_TOKEN`,
  `TWITCH_CHANNEL`, and `BOT_NAME`; the OpenAI/ElevenLabs/Cartesia/Google keys are only used by the
  legacy modules.
- `main.py` sets `os.environ["BASE_DIR_PATH"] = os.getcwd()`. Several modules read this env var to
  resolve file paths, so the bot **must be launched via `main.py`** (running a submodule directly will
  fail with a missing `BASE_DIR_PATH`).
- `prompt_chat.txt` (repo root) is the system prompt / character definition, loaded fresh on bot start.
  It contains placeholders (`STREAM_TITLE`, `GAME_NAME`) that the legacy `QueueConsumer` substitutes
  at runtime from the Twitch channel's live info.

## Architecture

### Entry point and mode switch

`main.py` selects one of three implementations via the hardcoded `mode = Mode.VLC_CLOUD` (`src/enums.py`):

- **`VLC_CLOUD`** (currently active / recommended): the new local pipeline in `src/twitchbot.py`.
- **`SPEAKER`**: same `twitchbot.py` `Bot` but with `speaker_bot=True` — sends text over a websocket to
  an external [Speaker.bot](https://speaker.bot) instead of synthesizing locally.
- **`STREAMER`** (legacy): the older `src/speaker_bot_based.py` + `src/queue_consumer.py` system.

To change which path runs, edit the `mode` value in `main.py`. There are no CLI flags.

### Active pipeline (`src/twitchbot.py`)

`Bot` extends `twitchio.ext.commands.Bot`. The flow is async and queue-based to avoid blocking the
event loop while the LLM thinks or audio plays:

1. `event_message` → pushes incoming chat onto an `asyncio.Queue`.
2. `message_worker` (one background task started on `event_ready`) pops messages **one at a time** and
   calls `process_message`, guaranteeing sequential responses (no overlapping audio).
3. `process_message`: filters the message (`src/filter_message.py`), then runs the blocking Ollama call
   via `asyncio.to_thread(ollama_completion, ...)`, appends to the shared `Bot.conversation` history
   (trimmed to `CONVERSATION_LIMIT = 20`), then either sends to Speaker.bot or synthesizes locally.
4. TTS: `src/texttospeech_piper.py` (`get_speech_by_text`) synthesizes the bot reply to a uniquely
   timestamped `audio_<ms>.wav`, then `src/generate_audio.py` (`play_audio`) plays it with python-vlc
   and deletes the file afterward.

Key shared state: `Bot.conversation` is a **class-level** list, so history is global across instances.

### Component map

| Concern | Active (local) | Legacy / alternate |
|---|---|---|
| LLM | `chat_ollama.py` (Ollama HTTP) | `chat.py`/`openai.py` (OpenAI), `chat_huggingface.py`, `test.py` (transformers) |
| TTS | `texttospeech_piper.py` (Piper) | `texttospeech_evenlabs.py`, `texttospeech_google.py`, `texttospeech_cartesia.py`, `texttospeech_sherpa.py`, `texttospeech_openai.py` |
| Audio out | `generate_audio.py` (VLC) | Speaker.bot via `websocket.py` |
| STT | — | `speechtotext_openai.py` |
| Orchestration | `twitchbot.py` (asyncio.Queue) | `speaker_bot_based.py` + `queue_consumer.py` |

`chattypes.py` defines `ChatCompletionMessage` (OpenAI message union) and a `CustomMessage` class used
by the legacy consumer. `logger.py` is a custom colored logger used only by the legacy path.

### Legacy path (`STREAMER` mode)

`speaker_bot_based.py` runs the twitchio bot on one thread while `queue_consumer.py` runs an
`asyncio.run` loop on a separate thread. The consumer also ingests YouTube/voice input by polling text
files (`chat_exchange.txt`, `streamer_exchange.txt`) written by external tools, applies a blacklist /
ignore-list from `filter.json`, decides probabilistically whether to answer (`answer_rate`), and speaks
via Speaker.bot websocket. Owner `!`-commands (`!reload_prompt`, `!clear_conv`, `!update_info`, etc.)
are handled in `event_message`.

## Conventions

- Code comments and many docstrings/log strings are in **Spanish**; match the surrounding language.
- twitchio and other untyped imports use `# type: ignore`; flake8 line-length is `B950` (relaxed E501).
- The local-stack modules are sprinkled with `print("DEBUG: ...")` calls — these are intentional WIP
  diagnostics (audio playback was being debugged; see `docs/REPORTE_CAMBIOS_2026_06_10.md`).

## Direction

`docs/PLAN_NEURO_V2.md` is the design doc for a planned v2 rewrite (multimodal Qwen3-Omni engine,
priority queue with paid-message auctioning, Discord voice, Silero VAD barge-in interruptions,
VTube Studio emotion hotkeys, SQLite persistence). It describes a **target architecture, not the
current code** — none of that module structure exists yet.
