<a name="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <h3 align="center">Mai-chan — AI VTuber for Twitch</h3>

  <p align="center">
    "Neuro-Sama"-style AI VTuber bot, <strong>100% local and free</strong>.
    It reads Twitch chat and the streamer's mic (and optionally the screen),
    generates an in-character reply with a local LLM, synthesizes it into speech,
    drives a VTube Studio avatar's emotion, and plays the audio back.
    <br />
    <br />
    Fork of <a href="https://github.com/adi-panda/Kuebiko">Kuebiko</a>, migrated to a
    stack with no paid services.
    <br />
    <br />
    <strong>🇬🇧 English</strong> · <a href="#mai-chan--ai-vtuber-para-twitch">🇪🇸 Español</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of contents</summary>
  <ol>
    <li><a href="#about-the-project">About the project</a></li>
    <li><a href="#architecture">Architecture</a></li>
    <li>
      <a href="#getting-started">Getting started</a>
      <ul>
        <li><a href="#requirements">Requirements</a></li>
        <li><a href="#installation">Installation</a></li>
        <li><a href="#configuration-env">Configuration (.env)</a></li>
      </ul>
    </li>
    <li><a href="#commands-makefile">Commands (Makefile)</a></li>
    <li><a href="#chat-commands">Chat commands</a></li>
    <li><a href="#optional-subsystems">Optional subsystems</a></li>
    <li><a href="#documentation">Documentation</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->

## About the project

Mai-chan is a "Neuro-Sama"-style AI VTuber bot. The pipeline is:

> **Twitch + Microphone (+ Screen)** → **Ollama (local LLM)** → **TTS** → **VTube Studio** → **VLC**

The whole chain runs **locally and at no cost**. The old paid-cloud modules
(OpenAI, ElevenLabs, Cartesia, Google TTS, Speaker.bot) were removed; the only online
piece is **Edge TTS**, swappable for **Piper** to go fully offline.

> ℹ️ The project is built **for Windows**: playback needs **VLC installed on the OS**, and
> STT and vision require an **NVIDIA GPU + CUDA**. Audio is routed into OBS/VTS with a
> **virtual audio cable** (e.g. VB-Audio Cable).

### Built with

- **Python 3.11** + [Poetry](https://python-poetry.org/)
- [Ollama](https://ollama.com/) — local LLM (Qwen2.5) and vision VLM (Qwen3-VL)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — local STT + Silero VAD
- [Edge TTS](https://github.com/rany2/edge-tts) / [Piper](https://github.com/rhasspy/piper) — speech synthesis
- [pyvts](https://github.com/Genteki/pyvts) — VTube Studio control
- [python-vlc](https://pypi.org/project/python-vlc/) — audio playback
- [twitchio](https://github.com/PythonistaGuild/TwitchIO) — Twitch chat
- `pycaw` / `pyaudiowpatch` — volume control and loopback capture (Windows)
- SQLite (stdlib) — episodic memory

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Architecture

Up to **four producers** feed **one shared `asyncio.PriorityQueue`**, so all inputs are
serialized through a single response pipeline (audio never overlaps):

| Producer | Source | Notes |
|----------|--------|-------|
| **Chat** | `event_message` | Twitch messages |
| **Microphone** | `LocalSTT.listen_loop` | Local STT; **always top priority** |
| **Vision** | `ScreenVision.watch_loop` | Only if `VISION_ENABLED` |
| **Director** | `director_loop` | Proactive; only if `DIRECTOR_ENABLED` |

- Queue items are `(priority, seq, message)`. The **attention mode**
  (`VIDEO_FIRST` / `CHAT_FIRST` / `HYBRID`) sets the per-source priority; `seq` gives FIFO
  on ties. Switch it live with `!mode` (channel owner only).
- **Chat commands (`!hola`, `!mode`, `!agenda`) do NOT go to the LLM**: they are handled
  separately and never enter the queue.
- **`is_speaking`** is the anti-echo flag: while Mai-chan is talking, STT and vision drop
  their input so she never reacts to her own voice/output.
- **Two-stage vision:** the VLM only *describes* the frame (objective, cheap) and the
  personality LLM turns that description into an in-character comment.
- **Episodic memory** (`src/memory.py`): stdlib SQLite (no server). On start it prepends a
  *session brief* (recent summaries + today's agenda) to the prompt; on shutdown it
  generates and saves a one-line summary of the stream.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->

## Getting started

### Requirements

- **Windows** (see note above) with **VLC installed** on the system.
- **NVIDIA GPU + CUDA** (for STT and vision). CUDA DLLs ship via the pip packages
  `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` (patched onto the PATH in `src/stt_local.py`).
- **[Ollama](https://ollama.com/)** running with the models pulled.
  - The default LLM in `.env.example` is `qwen2.5:3b` (fits 6GB GPUs):
    ```sh
    ollama pull qwen2.5:3b
    ```
  - For vision use the **`-instruct`** VLM variant (the plain one is *thinking* and hangs):
    ```sh
    ollama pull qwen3-vl:8b-instruct   # prod (RTX 3090); use qwen3-vl:4b-instruct on small GPUs
    ```
    > The `qwen3-vl` models need **Ollama >= 0.30**.
- **[Poetry](https://python-poetry.org/docs/#installation)**.
- **VTube Studio** open with its API enabled (port `8001` by default).
- A **virtual audio cable** (VB-Audio Cable) to route audio into OBS/VTS.

### Installation

1. Clone the repo:
   ```sh
   git clone https://github.com/edgarvaldez99/neuro-sama.git
   cd neuro-sama
   ```
2. Install dependencies:
   ```sh
   poetry install      # or: make install
   ```
3. Copy `.env.example` → `.env` and fill in the variables (see below).
4. Verify the environment before launching:
   ```sh
   make check-setup    # or: poetry run python -m src.check_setup
   ```
5. Run the bot:
   ```sh
   make run            # or: poetry run python main.py
   ```

> ⚠️ **Always launch via `main.py`** (or `make run`): it sets `BASE_DIR_PATH=cwd`, which
> several modules use to resolve paths (`prompt_chat.txt`, `audios/`,
> `emotion_hotkeys.json`). Running a submodule directly misresolves those paths.

### Configuration (.env)

Every option is read from `.env` (via `python-decouple`). The minimum required:

```sh
TWITCH_CHANNEL="your_channel"
TWITCH_TOKEN="your_twitch_oauth_token"   # https://twitchtokengenerator.com/
BOT_NAME="Neuro-Sama"
OLLAMA_MODEL="qwen2.5:3b"
TTS_ENGINE="edge"                        # "edge" (online) or "piper" (offline)
```

Other config files in the root:

- **`prompt_chat.txt`** — character/system prompt. It **must** make the LLM reply in JSON
  `{"response_text": ..., "emotion": ...}` (the bot calls Ollama in JSON mode and parses it).
- **`filter.json`** — chat blacklist / ignore-list (`src/filter_message.py`).

> `.env.example` documents **all** variables of every subsystem (vision, MediaController,
> attention mode, director). Code defaults target the production machine (RTX 3090); for
> small GPUs, uncomment the "dev" values.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Commands (Makefile)

The `Makefile` centralizes day-to-day commands. `make` or `make help` lists everything:

| Command | What it does |
|---------|--------------|
| `make install` | Install the local stack dependencies (`poetry install`) |
| `make format` | Format the code (`isort` + `black`) |
| `make lint` | Run the 6 quality tools (same as VSCode) |
| `make check` | Alias of `lint` (checks without modifying files) |
| `make check-setup` | Environment diagnostics (Ollama, VTS, `.env` variables) |
| `make run` | Start the bot |

`make lint` runs: **flake8**, **isort --check**, **black --check**, **mypy**, **pylint**
and **pyright**. pylint is expected to stay at **10/10** (annotate intentional warnings
inline). Line length: **88**.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Chat commands

| Command | Who | What it does |
|---------|-----|--------------|
| `!hola` (aliases: `!op`, `!alo`, `!haupei`, `!buen día`) | Everyone | Greeting |
| `!mode video\|chat\|hybrid` | Owner | Switch attention mode live |
| `!agenda` | Owner | List today's plan |
| `!agenda <text>` | Owner | Add a task/idea to the agenda |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Optional subsystems

All are **off by default** and enabled from `.env`:

- **Vision** (`VISION_ENABLED`) — Mai-chan "sees" the screen and reacts. Uses a VLM
  (`qwen3-vl`) to describe the frame, with scene-difference anti-spam. Standalone prototype:
  `poetry run python -m src.screen_vision`.
- **MediaController** (`MEDIA_CONTROL_ENABLED`) — keeps the video audio from talking over
  Mai-chan: it **pauses** (media key) or **ducks** the volume (`pycaw`, per-app) while she
  speaks. Level 1 only (simulated inputs, no autonomous PC control).
- **Loopback VAD** (`MEDIA_VAD_ENABLED`) — instead of assuming, it **detects live** whether
  the video has speech: captures system audio (WASAPI loopback via `pyaudiowpatch`) and runs
  **Silero VAD** (reused from faster-whisper). So music/SFX don't trigger cuts. Degrades to
  the `MEDIA_ASSUME_DIALOGO` heuristic if the dep/device is missing.
- **Attention mode** (`ATTENTION_MODE`) — `VIDEO_FIRST` / `CHAT_FIRST` / `HYBRID`.
- **Director** (`DIRECTOR_ENABLED`) — when there's silence, Mai-chan speaks on her own:
  resumes today's agenda or drops a comment, so the stream isn't dead air.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Documentation

Detailed design and direction docs live in `docs/`:

- **`docs/plan_vision_general.md`** — general vision/reaction plan.
- **`docs/PLAN_NEURO_V2.md`** — target v2 rewrite design (Qwen3-Omni, paid-message auctions
  in the queue, Discord voice, Silero VAD barge-in). *Design, not current code.*
- **`docs/REPORTE_MEJORAS_STT_AUDIO.md`** — STT/audio tuning notes.

> The project is governed by `CLAUDE.md` (architecture instructions and conventions). The
> original upstream README is out of date: trust the code and `docs/`.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->

## Contributing

Contributions are welcome. Before opening a PR, make sure `make lint` passes.

1. Fork the project
2. Create your branch (`git checkout -b feature/MyFeature`)
3. Commit your changes (`git commit -m 'Add MyFeature'`)
4. Push the branch (`git push origin feature/MyFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->

## License

Distributed under the MIT License.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

- [Kuebiko](https://github.com/adi-panda/Kuebiko) — the original project this is a fork of.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---
---

<a name="mai-chan--ai-vtuber-para-twitch"></a>

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <h3 align="center">Mai-chan — AI VTuber para Twitch</h3>

  <p align="center">
    Bot AI-VTuber estilo "Neuro-Sama", <strong>100% local y gratis</strong>.
    Lee el chat de Twitch y el micro del streamer (y opcionalmente la pantalla),
    genera una respuesta en personaje con un LLM local, la sintetiza en voz,
    mueve la emoción de un avatar de VTube Studio y reproduce el audio.
    <br />
    <br />
    Fork de <a href="https://github.com/adi-panda/Kuebiko">Kuebiko</a>, migrado a
    un stack sin servicios pagos.
    <br />
    <br />
    <a href="#readme-top">🇬🇧 English</a> · <strong>🇪🇸 Español</strong>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Tabla de contenidos</summary>
  <ol>
    <li><a href="#sobre-el-proyecto">Sobre el proyecto</a></li>
    <li><a href="#arquitectura">Arquitectura</a></li>
    <li>
      <a href="#cómo-empezar">Cómo empezar</a>
      <ul>
        <li><a href="#requisitos">Requisitos</a></li>
        <li><a href="#instalación">Instalación</a></li>
        <li><a href="#configuración-env">Configuración (.env)</a></li>
      </ul>
    </li>
    <li><a href="#comandos-makefile">Comandos (Makefile)</a></li>
    <li><a href="#comandos-del-chat">Comandos del chat</a></li>
    <li><a href="#subsistemas-opcionales">Subsistemas opcionales</a></li>
    <li><a href="#documentación">Documentación</a></li>
    <li><a href="#contribuir">Contribuir</a></li>
    <li><a href="#licencia">Licencia</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->

## Sobre el proyecto

Mai-chan es un bot AI-VTuber al estilo "Neuro-Sama". El pipeline es:

> **Twitch + Micrófono (+ Pantalla)** → **Ollama (LLM local)** → **TTS** → **VTube Studio** → **VLC**

Toda la cadena corre **local y sin costos**. Los antiguos módulos de nube pagos
(OpenAI, ElevenLabs, Cartesia, Google TTS, Speaker.bot) fueron eliminados; la única
pieza online es **Edge TTS**, intercambiable por **Piper** para quedar 100% offline.

> ℹ️ El proyecto está pensado **para Windows**: la reproducción necesita **VLC instalado
> en el sistema**, y el STT y la visión requieren **GPU NVIDIA + CUDA**. El audio se
> rutea hacia OBS/VTS con un **cable de audio virtual** (ej: VB-Audio Cable).

### Construido con

- **Python 3.11** + [Poetry](https://python-poetry.org/)
- [Ollama](https://ollama.com/) — LLM local (Qwen2.5) y VLM de visión (Qwen3-VL)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — STT local + Silero VAD
- [Edge TTS](https://github.com/rany2/edge-tts) / [Piper](https://github.com/rhasspy/piper) — síntesis de voz
- [pyvts](https://github.com/Genteki/pyvts) — control de VTube Studio
- [python-vlc](https://pypi.org/project/python-vlc/) — reproducción de audio
- [twitchio](https://github.com/PythonistaGuild/TwitchIO) — chat de Twitch
- `pycaw` / `pyaudiowpatch` — control de volumen y captura de loopback (Windows)
- SQLite (stdlib) — memoria episódica

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Arquitectura

Hasta **cuatro productores** alimentan **una única `asyncio.PriorityQueue`** compartida,
de modo que todas las entradas se serializan por un solo pipeline de respuesta (el audio
nunca se solapa):

| Productor | Origen | Notas |
|-----------|--------|-------|
| **Chat** | `event_message` | Mensajes de Twitch |
| **Micrófono** | `LocalSTT.listen_loop` | STT local; **siempre prioridad máxima** |
| **Visión** | `ScreenVision.watch_loop` | Solo si `VISION_ENABLED` |
| **Director** | `director_loop` | Proactivo; solo si `DIRECTOR_ENABLED` |

- Los ítems de la cola son `(prioridad, seq, mensaje)`. El **modo de atención**
  (`VIDEO_FIRST` / `CHAT_FIRST` / `HYBRID`) define la prioridad por fuente; `seq` da FIFO
  ante empates. Se cambia en vivo con `!mode` (solo el dueño del canal).
- Los **comandos del chat (`!hola`, `!mode`, `!agenda`) NO van al LLM**: se atienden
  aparte y no entran a la cola.
- **`is_speaking`** es el flag anti-eco: mientras Mai-chan habla, el STT y la visión
  descartan su entrada para que no reaccione a su propia voz/salida.
- **Visión en dos etapas:** el VLM solo *describe* el frame (objetivo, barato) y el LLM
  de personalidad convierte esa descripción en un comentario en personaje.
- **Memoria episódica** (`src/memory.py`): SQLite de la stdlib (sin servidor). Al arrancar
  antepone un *brief de sesión* (resúmenes recientes + agenda del día) al prompt; al cerrar
  genera y guarda un resumen de una línea del stream.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->

## Cómo empezar

### Requisitos

- **Windows** (ver nota arriba) con **VLC instalado** en el sistema.
- **GPU NVIDIA + CUDA** (para STT y visión). Las DLLs de CUDA llegan vía los paquetes pip
  `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` (se parchean al PATH en `src/stt_local.py`).
- **[Ollama](https://ollama.com/)** corriendo y con los modelos descargados.
  - El LLM por defecto del `.env.example` es `qwen2.5:3b` (entra en GPUs de 6GB):
    ```sh
    ollama pull qwen2.5:3b
    ```
  - Para visión usá la variante **`-instruct`** del VLM (la genérica es *thinking* y se cuelga):
    ```sh
    ollama pull qwen3-vl:8b-instruct   # prod (RTX 3090); usar qwen3-vl:4b-instruct en GPUs chicas
    ```
    > Los modelos `qwen3-vl` necesitan **Ollama >= 0.30**.
- **[Poetry](https://python-poetry.org/docs/#installation)**.
- **VTube Studio** abierto con su API habilitada (puerto `8001` por defecto).
- Un **cable de audio virtual** (VB-Audio Cable) para rutear el audio hacia OBS/VTS.

### Instalación

1. Cloná el repo:
   ```sh
   git clone https://github.com/edgarvaldez99/neuro-sama.git
   cd neuro-sama
   ```
2. Instalá las dependencias:
   ```sh
   poetry install      # o: make install
   ```
3. Copiá `.env.example` → `.env` y completá las variables (ver abajo).
4. Verificá el entorno antes de arrancar:
   ```sh
   make check-setup    # o: poetry run python -m src.check_setup
   ```
5. Arrancá el bot:
   ```sh
   make run            # o: poetry run python main.py
   ```

> ⚠️ **Arrancá siempre con `main.py`** (o `make run`): éste fija `BASE_DIR_PATH=cwd`, que
> varios módulos usan para resolver rutas (`prompt_chat.txt`, `audios/`,
> `emotion_hotkeys.json`). Correr un submódulo directo desmapea esas rutas.

### Configuración (.env)

Todas las opciones se leen del `.env` (vía `python-decouple`). Lo mínimo requerido:

```sh
TWITCH_CHANNEL="tu_canal"
TWITCH_TOKEN="tu_twitch_oauth_token"   # https://twitchtokengenerator.com/
BOT_NAME="Neuro-Sama"
OLLAMA_MODEL="qwen2.5:3b"
TTS_ENGINE="edge"                      # "edge" (online) o "piper" (offline)
```

Otros archivos de configuración en la raíz:

- **`prompt_chat.txt`** — prompt de personaje/sistema. **Debe** hacer que el LLM responda
  en JSON `{"response_text": ..., "emotion": ...}` (el bot llama a Ollama en modo JSON y
  parsea eso).
- **`filter.json`** — blacklist / ignore-list del chat (`src/filter_message.py`).

> El `.env.example` documenta **todas** las variables de cada subsistema (visión,
> MediaController, modo de atención, director). Los defaults del código apuntan a la
> máquina de producción (RTX 3090); para GPUs chicas, descomentá los valores "dev".

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Comandos (Makefile)

El `Makefile` centraliza los comandos del día a día. `make` o `make help` lista todo:

| Comando | Qué hace |
|---------|----------|
| `make install` | Instala las dependencias del stack local (`poetry install`) |
| `make format` | Formatea el código (`isort` + `black`) |
| `make lint` | Corre las 6 herramientas de calidad (igual que VSCode) |
| `make check` | Alias de `lint` (verifica sin modificar archivos) |
| `make check-setup` | Diagnóstico del entorno (Ollama, VTS, variables `.env`) |
| `make run` | Arranca el bot |

`make lint` ejecuta: **flake8**, **isort --check**, **black --check**, **mypy**,
**pylint** y **pyright**. Se espera mantener pylint en **10/10** (anotar inline las
advertencias intencionales). Longitud de línea: **88**.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Comandos del chat

| Comando | Quién | Qué hace |
|---------|-------|----------|
| `!hola` (alias: `!op`, `!alo`, `!haupei`, `!buen día`) | Todos | Saludo |
| `!mode video\|chat\|hybrid` | Dueño | Cambia el modo de atención en vivo |
| `!agenda` | Dueño | Lista el plan del día |
| `!agenda <texto>` | Dueño | Agrega una tarea/idea a la agenda |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Subsistemas opcionales

Todos están **apagados por defecto** y se activan desde el `.env`:

- **Visión** (`VISION_ENABLED`) — Mai-chan "ve" la pantalla y reacciona. Usa un VLM
  (`qwen3-vl`) para describir el frame, con anti-spam por diferencia de escena.
  Prototipo standalone: `poetry run python -m src.screen_vision`.
- **MediaController** (`MEDIA_CONTROL_ENABLED`) — evita que el audio del video pise la voz
  de Mai-chan: **pausa** (tecla multimedia) o **duckea** el volumen (`pycaw`, por app)
  mientras ella habla. Nivel 1 (solo simula inputs, sin control autónomo de la PC).
- **VAD de loopback** (`MEDIA_VAD_ENABLED`) — en vez de asumir, **detecta en vivo** si el
  video tiene voz: captura el audio del sistema (loopback WASAPI vía `pyaudiowpatch`) y lo
  pasa por **Silero VAD** (reusado de faster-whisper). Así la música/SFX no disparan cortes.
  Degrada al heurístico `MEDIA_ASSUME_DIALOGO` si falta la dependencia/dispositivo.
- **Modo de atención** (`ATTENTION_MODE`) — `VIDEO_FIRST` / `CHAT_FIRST` / `HYBRID`.
- **Director** (`DIRECTOR_ENABLED`) — cuando hay silencio, Mai-chan habla sola: retoma su
  agenda del día o suelta un comentario, para que el stream no quede mudo.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Documentación

Documentación detallada del diseño y la dirección del proyecto en `docs/`:

- **`docs/plan_vision_general.md`** — plan general de visión/reacción.
- **`docs/PLAN_NEURO_V2.md`** — diseño objetivo de la reescritura v2 (Qwen3-Omni, subastas
  de mensajes pagos en la cola, Discord voice, barge-in con Silero VAD). *Diseño, no código actual.*
- **`docs/REPORTE_MEJORAS_STT_AUDIO.md`** — notas de tuning de STT/audio.

> El proyecto se gobierna con `CLAUDE.md` (instrucciones de arquitectura y convenciones).
> El README upstream original quedó obsoleto: confiá en el código y en `docs/`.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->

## Contribuir

Las contribuciones son bienvenidas. Antes de abrir un PR, asegurate de que pase `make lint`.

1. Forkeá el proyecto
2. Creá tu rama (`git checkout -b feature/MiFeature`)
3. Commiteá tus cambios (`git commit -m 'Agrega MiFeature'`)
4. Pusheá la rama (`git push origin feature/MiFeature`)
5. Abrí un Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->

## Licencia

Distribuido bajo la licencia MIT.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Agradecimientos

- [Kuebiko](https://github.com/adi-panda/Kuebiko) — proyecto original del que es fork.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[forks-shield]: https://img.shields.io/github/forks/edgarvaldez99/neuro-sama.svg?style=for-the-badge
[forks-url]: https://github.com/edgarvaldez99/neuro-sama/network/members
[stars-shield]: https://img.shields.io/github/stars/edgarvaldez99/neuro-sama.svg?style=for-the-badge
[stars-url]: https://github.com/edgarvaldez99/neuro-sama/stargazers
[issues-shield]: https://img.shields.io/github/issues/edgarvaldez99/neuro-sama.svg?style=for-the-badge
[issues-url]: https://github.com/edgarvaldez99/neuro-sama/issues
