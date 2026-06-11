# 🤖 Plan Maestro — Neuro-Sama v2

> Bot AI-VTuber con motor multimodal local, sistema de prioridades, análisis de sentimiento e interrupciones naturales.

---

## 📋 Resumen Ejecutivo

Aplicación que actúa como VTuber AI controlable desde código. Lee chats de Twitch y YouTube, escucha por micrófono al streamer y a colaboradores en Discord, prioriza mensajes según jerarquía y pago, responde por voz en español/inglés, y sincroniza expresiones del avatar 2D Live2D según la emoción detectada.

### Objetivo de calidad
- Voz natural en español e inglés
- Latencia conversacional < 1 segundo
- Capacidad de ser interrumpida por el owner/colaboradores
- Diferenciación de prioridades verificable en cola
- Cero dependencias de pago en producción

---

## 🧰 Stack Tecnológico

### Motor principal
| Componente | Tecnología | Versión / detalle |
|------------|-----------|-------------------|
| **Modelo omni-modal** | `Qwen/Qwen3-Omni-30B-A3B-Instruct` | Q4_K_M GGUF (~17 GB VRAM) |
| **Inferencia** | `vLLM` o `llama.cpp` con bindings Python | Decisión en Fase 2 |
| **VAD (interrupciones)** | `silero-vad` | ONNX, ~50 MB |
| **Avatar** | VTube Studio (Live2D) | Plugin API WebSocket |

### Inputs / Outputs
| Componente | Tecnología |
|------------|-----------|
| Twitch chat | `twitchio` |
| YouTube chat | `pytchat` |
| Voz colaboradores | `discord.py` + `discord-ext-voice-recv` |
| Voz streamer | `sounddevice` (mic local) |
| Audio out | `sounddevice` → VB-Audio Cable → OBS |
| Persistencia | SQLite (`sqlite3` stdlib) |

### Lenguaje y herramientas
- **Python 3.11+** (asyncio nativo)
- **Poetry** para dependencias
- **Pydantic** para validación de JSON del modelo
- **Loguru** para logging estructurado

### Estrategia: **Stack Híbrido (Core + Complementos)**

Qwen3-Omni es el motor central que cubre la mayor parte del pipeline. Los gaps que tiene se complementan con modelos especializados livianos. NO usamos cascade puro (Whisper+LLM+TTS por separado) porque añade latencia innecesaria, pero tampoco confiamos todo a un solo modelo.

| Capa | Modelo CORE | Complementos opcionales | Por qué |
|------|------------|-------------------------|---------|
| STT | Qwen3-Omni | — | Cubre 19 idiomas incluido ES |
| LLM | Qwen3-Omni | — | 30B-A3B excelente razonamiento ES |
| TTS | Qwen3-Omni (voces Ethan/Chelsie/Aiden) | XTTS-v2 (voice cloning) | Solo si querés voz custom |
| VAD / barge-in | — | **Silero VAD** ⭐ | Qwen3-Omni no es full-duplex |
| Sentimiento del bot | Qwen3-Omni (JSON output) | — | Cero costo extra |
| Sentimiento del usuario | — | pysentimiento (ES) / j-hartmann (EN) | Solo si querés reaccionar al humor del que habla |
| Memoria largo plazo | — | BGE-M3 + ChromaDB | Recordar viewers recurrentes |
| Wake word | — | openWakeWord | Activación selectiva sin gastar GPU |
| Conversación EN premium | — | Personaplex 7B Q4 | Módulo opcional para anglo-colabs |

### Comparación con alternativas (descartadas)
| Opción | Pros | Contras | Decisión |
|--------|------|---------|----------|
| **Qwen3-Omni Instruct + Silero VAD** | Multimodal, ES nativo, Apache 2.0, MoE eficiente | No full-duplex real (mitigado con VAD) | ✅ **ELEGIDO** |
| Personaplex como motor único | Full-duplex 240ms barge-in | Solo inglés | ❌ Sin español |
| Cascade Whisper+Qwen+XTTS puro | Control fino por componente | +800ms latencia acumulada, 3x código | ❌ Más complejo, peor UX |
| MiniCPM-o | Ligero, full-duplex | Bilingüe ZH/EN, español débil | ❌ Sin español sólido |
| Voxtral + LLM separado | Open weights, multilingüe | TTS-only, requiere LLM aparte → cascade | ❌ Vuelve a cascade |

---

## 🖥️ Hardware y Sistema Operativo

### Máquina objetivo (specs confirmadas)
- **CPU:** AMD Ryzen 9 5950X (16 cores / 32 threads, Zen 3, AM4)
- **GPU:** NVIDIA RTX 3090 24 GB (PCIe 4.0)
- **RAM:** 32 GB DDR4
- **MB:** ASUS TUF GAMING X570-PLUS (WI-FI)
- **Storage:** 2× NVMe 1 TB
- **SO:** Windows 11 Pro 64-bit
- **BIOS:** UEFI v4204 (25/02/2022) — actualizable, recomendable

### Verificaciones obligatorias antes de empezar
1. **SVM Mode en BIOS habilitado** (Advanced → CPU Configuration → SVM Mode: Enabled). Sin esto, WSL2 no funciona.
2. **RTX 3090 instalada y detectada** (verificar `nvidia-smi` en PowerShell tras instalar drivers).
3. **Drivers NVIDIA ≥ 555.x** ([descarga](https://www.nvidia.com/Download/index.aspx)) con soporte WSL2 CUDA passthrough.
4. **≥ 200 GB libres en alguno de los NVMe** (WSL2 VHDX + modelo + dependencias).
5. **BIOS update opcional** pero recomendado: descargar última versión desde [ASUS X570-PLUS support](https://www.asus.com/motherboards-components/motherboards/tuf-gaming/tuf-gaming-x570-plus-wifi/helpdesk_bios/). Aporta mejor microcódigo Zen 3 y soporte virtualización mejorado.

### Stack de SO
```
Windows 11 (host)
├── VTube Studio (nativo)
├── OBS Studio (nativo)
├── VB-Audio Virtual Cable (nativo)
└── WSL2 Ubuntu 22.04 LTS
    ├── CUDA 12.4 + cuDNN
    ├── Python 3.11 + Poetry
    ├── Qwen3-Omni inferencia
    └── Bot principal (asyncio)
```

WSL2 con GPU passthrough es la combinación oficialmente soportada por NVIDIA para correr CUDA en Windows. Permite que el bot use la GPU mientras VTube Studio y OBS siguen siendo apps nativas Windows comunicándose por WebSocket/audio loopback.

### Distribución de VRAM esperada (24 GB)

**Configuración mínima (Fase inicial):**
| Uso | VRAM |
|-----|------|
| Qwen3-Omni-30B-A3B Q4_K_M | ~17 GB |
| KV cache (8K context) | ~2 GB |
| Silero VAD | ~50 MB |
| Buffers audio | ~500 MB |
| **Total ocupado** | **~20 GB** |
| **Margen disponible** | **~4 GB** |

**Configuración con complementos opcionales (Fase avanzada):**
| Uso | VRAM | Necesario si... |
|-----|------|------------------|
| Qwen3-Omni Q4_K_M | ~17 GB | siempre |
| KV cache (8K) | ~2 GB | siempre |
| Silero VAD | ~50 MB | siempre |
| BGE-M3 embeddings | ~1 GB | querés memoria largo plazo |
| pysentimiento ES | ~500 MB | querés sentimiento del usuario |
| XTTS-v2 (si voice cloning) | ~3 GB | querés voz custom |
| Personaplex Q4 (módulo EN) | ~5 GB | conversación premium en inglés |
| Buffers + overhead | ~500 MB | siempre |

⚠️ **No todo cabe junto.** Si activás Personaplex + XTTS + embeddings, hay que bajar Qwen3-Omni a Q3_K_M (~14 GB) o desactivar el talker (`-10 GB`) para liberar VRAM. Estrategias:

- **Modo conversación con colabs EN:** Qwen3-Omni con talker desactivado (~7 GB) + Personaplex Q4 (5 GB) + VAD = **12 GB usados, 12 GB libres**
- **Modo streaming normal ES:** Qwen3-Omni Q4 completo + VAD + embeddings = **20 GB usados**
- **Modo voz custom:** Qwen3-Omni con talker desactivado + XTTS-v2 + VAD = **10 GB usados**

El orquestador puede cargar/descargar modelos según el modo activo (cambio caliente).

---

## 🏗️ Arquitectura General

### Diagrama de bloques

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              INPUTS                                      │
│                                                                          │
│  Twitch chat ──┐                                                         │
│  YouTube chat ─┼──► [Filtro] ──► [Scoring de pago] ──┐                  │
│  Discord voz ──┤                                      │                  │
│  Mic streamer ─┘                                      │                  │
│                                                       ▼                  │
│                                            ┌─────────────────┐           │
│                                            │ COLA PRIORIZADA │           │
│                                            │  P0 = Owner     │           │
│                                            │  P1 = Colabs    │           │
│                                            │  P2 = Chat      │           │
│                                            │   (subasta)     │           │
│                                            └────────┬────────┘           │
└─────────────────────────────────────────────────────┼────────────────────┘
                                                      │
┌─────────────────────────────────────────────────────┼────────────────────┐
│                         MOTOR (RTX 3090)            ▼                    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                Qwen3-Omni-30B-A3B-Instruct (Q4)                 │    │
│  │                                                                 │    │
│  │  Input: audio + texto + sistema_prompt + historial              │    │
│  │  Output JSON estructurado:                                      │    │
│  │    {                                                            │    │
│  │      "response_text": "...",                                    │    │
│  │      "audio_bytes": <wav 24kHz>,                                │    │
│  │      "emotion": "happy|sad|angry|surprised|neutral|...",        │    │
│  │      "intensity": 0.0-1.0,                                      │    │
│  │      "language": "es|en",                                       │    │
│  │      "owner_addressed": bool                                    │    │
│  │    }                                                            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────┐         ┌────────────────────────────────┐      │
│  │ Silero VAD          │  ←──────│ Mic streamer (siempre on)      │      │
│  │ Detección barge-in  │         │ Audio chunks 30ms              │      │
│  └─────────┬───────────┘         └────────────────────────────────┘      │
│            │                                                             │
│            ▼ (si voz mientras SPEAKING)                                  │
│      INTERRUPCIÓN                                                        │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              OUTPUTS                                     │
│                                                                          │
│  ┌──────────────────┐   ┌──────────────────────┐   ┌─────────────────┐  │
│  │ Audio out        │   │ VTube Studio API     │   │ Logs / SQLite   │  │
│  │ → VB-Audio       │   │ Hotkey por emoción   │   │ Historial conv. │  │
│  │   → OBS          │   │ Lipsync (vía audio)  │   │                 │  │
│  └──────────────────┘   └──────────────────────┘   └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### State machine del orquestador

```
        ┌──────────┐
   ┌───►│   IDLE   │  esperando mensajes en cola
   │    └─────┬────┘
   │          │ pop()
   │          ▼
   │    ┌──────────┐
   │    │ THINKING │  Qwen3-Omni procesando
   │    └─────┬────┘
   │          │ token streaming inicia
   │          ▼
   │    ┌──────────┐
   │    │ SPEAKING │  audio reproduciéndose
   │    └─────┬────┘
   │          │
   │          ├─── speak_done ──┐
   │          │                 │
   │          └─── owner VAD ◄──┤
   │                            ▼
   │              ┌────────────────────────┐
   │              │     INTERRUPTED        │
   │              │ • cancel current TTS   │
   │              │ • requeue prev message │
   │              │ • capture owner audio  │
   │              └─────────┬──────────────┘
   │                        │ silence detected
   │                        ▼
   │             [LLM evaluates question]
   │                        │
   │             ┌──────────┴──────────┐
   │             ▼                     ▼
   │      addressed=true         addressed=false
   │      respond + joke         joke + resume prev
   └─────────────┴───────────────┴──────────────────► back to IDLE
```

---

## 📁 Estructura de Carpetas

```
neuro-sama-v2/
├── pyproject.toml
├── poetry.lock
├── README.md
├── .env.example
├── .gitignore
│
├── config/
│   ├── personality.txt           # System prompt en español
│   ├── personality_en.txt        # En inglés (opcional)
│   ├── collaborators.json        # Persistente, mutable en runtime
│   ├── filters.json              # Blacklist y usuarios ignorados
│   ├── emotion_hotkeys.json      # Mapeo emoción → VTS hotkey ID
│   └── voices.json               # Mapeo idioma → voice id Qwen
│
├── data/
│   ├── neuro.db                  # SQLite: historial, métricas
│   └── audio_cache/              # Audios temporales TTS
│
├── logs/
│   └── neuro_YYYY-MM-DD.log
│
├── src/
│   ├── __init__.py
│   ├── main.py                   # Entry point + orquestador
│   ├── config.py                 # Carga .env y JSONs
│   ├── state.py                  # State machine
│   │
│   ├── queue/
│   │   ├── __init__.py
│   │   ├── priority_queue.py     # Cola con heapq async
│   │   ├── scoring.py            # Cálculo de score por pagos
│   │   ├── auction.py            # Algoritmo de subasta
│   │   └── ttl_manager.py        # Loop de cleanup
│   │
│   ├── inputs/
│   │   ├── __init__.py
│   │   ├── twitch_chat.py
│   │   ├── youtube_chat.py
│   │   ├── discord_voice.py
│   │   ├── owner_mic.py
│   │   └── vad.py                # Silero VAD wrapper
│   │
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── qwen_omni.py          # Cliente a vLLM/llama.cpp
│   │   ├── prompt_builder.py     # Arma system prompt + historial
│   │   ├── response_schema.py    # Pydantic models para JSON output
│   │   └── interruption_logic.py # Lógica broma + reanudar
│   │
│   ├── outputs/
│   │   ├── __init__.py
│   │   ├── audio_player.py       # Reproducción → VB-Audio
│   │   └── vts_controller.py     # pyvts WebSocket
│   │
│   ├── controllers/
│   │   ├── __init__.py
│   │   ├── commands.py           # !addcollab, !chat on/off, etc.
│   │   ├── collab_manager.py     # CRUD colaboradores
│   │   └── platform_resolver.py  # Helix API, etc.
│   │
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── db.py                 # SQLite schema + CRUD
│   │   └── conversation.py       # Historial estructurado
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       └── audio_utils.py
│
├── tests/
│   ├── test_priority_queue.py
│   ├── test_scoring.py
│   ├── test_auction.py
│   └── test_collab_manager.py
│
├── scripts/
│   ├── download_models.py        # Pre-descarga GGUF y Silero
│   ├── verify_setup.py           # Diagnóstico (como check_setup.py)
│   └── run_inference_server.sh   # Levanta vLLM
│
└── tray_app.py                   # GUI mínima Tkinter (toggle chat, etc.)
```

---

## 🗄️ Modelo de Datos

### Mensaje encolado (`QueuedMessage`)
```python
@dataclass
class QueuedMessage:
    # Identificación
    id: str                  # UUID
    timestamp: float         # epoch
    
    # Origen
    platform: str            # "twitch" | "youtube" | "discord" | "mic"
    author_id: str           # ID del usuario en su plataforma
    author_name: str
    
    # Contenido
    content_type: str        # "text" | "audio"
    text: str | None
    audio_path: str | None
    language_hint: str | None  # "es" | "en"
    
    # Priorización
    priority: int            # 0=owner, 1=collab, 2=chat
    score: float             # >0 si pagó
    
    # Metadata de pago (solo chat)
    bits: int = 0            # Twitch
    sub_tier: int = 0        # Twitch (1, 2, 3)
    superchat_amount: float = 0.0  # YouTube USD
    is_member: bool = False  # YouTube
    is_mod: bool = False
    is_vip: bool = False
    
    # Estado
    answered: bool = False
    discarded: bool = False
```

### Niveles de prioridad
```python
class Priority(IntEnum):
    OWNER = 0
    COLLAB = 1
    CHAT = 2
```

### Función de scoring (chat)
```python
def compute_score(msg: QueuedMessage) -> float:
    score = 0.0
    
    # Twitch
    score += msg.bits / 100             # 100 bits ≈ $1
    score += [0, 5, 10, 15][msg.sub_tier]  # tiers
    if msg.is_vip:  score += 3
    if msg.is_mod:  score += 2
    
    # YouTube
    score += msg.superchat_amount * 10  # 10pts por USD
    if msg.is_member: score += 5
    
    return score
```

### Tabla SQLite
```sql
CREATE TABLE conversation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  role TEXT NOT NULL,            -- 'system' | 'user' | 'assistant'
  platform TEXT,
  author_id TEXT,
  author_name TEXT,
  content TEXT NOT NULL,
  emotion TEXT,
  language TEXT,
  audio_path TEXT,
  was_interrupted INTEGER DEFAULT 0
);

CREATE TABLE collaborators (
  platform TEXT NOT NULL,
  user_id TEXT NOT NULL,
  display_name TEXT,
  added_at REAL,
  PRIMARY KEY (platform, user_id)
);

CREATE TABLE message_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL,
  platform TEXT,
  priority INTEGER,
  score REAL,
  was_answered INTEGER,
  wait_ms INTEGER,
  inference_ms INTEGER
);
```

---

## ⚙️ Sistema de Cola y Subasta

### Reglas finales
1. **P0 (Owner)** siempre antes que cualquier otro.
2. **P1 (Colabs)** antes que P2.
3. **P2 (Chat)** ordenado por `score` descendente; FIFO si empate.
4. **TTL adaptativo:**
   - `score > 0` → nunca descarta
   - `score == 0` → 30s
5. **Subasta:** se activa cuando `len(chat) > 10` o `paid > unpaid`. En ese estado:
   - Solo top 5 mensajes pagos
   - Resto descartado
6. **Switch chat:** owner puede `chat off` → no se acepta P2.
7. **Modo collab_only:** ignora P2 aunque chat esté on.
8. **Mute:** acepta y encola, pero no responde (vuelve a respuestas al volver).

### Pseudocódigo del cleanup loop
```python
async def cleanup_loop(queue):
    while True:
        async with queue._lock:
            now = time()
            chat = [m for m in queue._heap if m.priority == Priority.CHAT]
            paid = [m for m in chat if m.score > 0]
            unpaid = [m for m in chat if m.score == 0]
            
            unpaid = [m for m in unpaid if now - m.timestamp < 30]
            
            if len(chat) > 10 or len(paid) > len(unpaid):
                paid.sort(key=lambda m: m.score, reverse=True)
                paid = paid[:5]
                unpaid = []
            
            other = [m for m in queue._heap if m.priority != Priority.CHAT]
            queue._rebuild(other + paid + unpaid)
        
        await asyncio.sleep(3)
```

---

## 👥 Identificación de Owner y Colaboradores

### Owner
- **Twitch:** `message.author.is_broadcaster == True` o `username == TWITCH_CHANNEL`
- **YouTube:** `chat_item.author.isChatOwner == True`
- **Discord:** `user.id == OWNER_DISCORD_ID` (configurado en `.env`)
- **Mic local:** todo audio del mic principal es del owner

### Colaboradores (configurable runtime)

`config/collaborators.json`:
```json
{
  "twitch": {
    "12345678": {"login": "user_one", "added_at": "2026-05-09T..."}
  },
  "youtube": {
    "UCxxxxx": {"name": "User Two", "added_at": "..."}
  },
  "discord": {
    "987654321": {"name": "User Three", "added_at": "..."}
  }
}
```

### Comandos disponibles (solo owner)
| Comando | Función | Ejecutable desde |
|---------|---------|------------------|
| `!addcollab <usuario>` | Agrega colab | Cualquier chat |
| `!removecollab <usuario>` | Quita colab | Cualquier chat |
| `!listcollabs` | Imprime lista | Cualquier chat |
| `!chat on` / `!chat off` | Toggle chat | Cualquier chat |
| `!mode all` | Acepta todo | Cualquier chat |
| `!mode collab_only` | Solo owner+colabs | Cualquier chat |
| `!mute` / `!unmute` | Encola pero no responde | Cualquier chat |
| `!reload_prompt` | Recarga personality.txt | Cualquier chat |
| `!clear_history` | Limpia historial conv. | Cualquier chat |
| `!stats` | Imprime métricas | Cualquier chat |

### Resolución `<usuario>` por plataforma
- **Twitch:** Helix API `GET /users?login=<name>` → user_id
- **YouTube:** debe haber escrito al menos un mensaje (cache de author_channel_id)
- **Discord:** `@mention` da el ID directo

---

## 🛑 Sistema de Interrupciones (Barge-in)

### Detección
1. Mic del owner queda permanentemente activo
2. **Silero VAD** evalúa chunks de 30ms
3. Cuando 3 chunks consecutivos = voz → trigger barge-in
4. Detectable en ~100ms (vs 240ms de Personaplex pero suficiente)

### Lógica al detectar voz del owner durante SPEAKING
```python
async def on_owner_voice_detected():
    # 1. Cortar audio actual inmediato
    await audio_player.stop()
    
    # 2. Marcar mensaje en proceso como interrumpido
    interrupted_msg = current_msg
    interrupted_msg.was_interrupted = True
    pending_resume = interrupted_msg
    
    # 3. Capturar audio del owner hasta silencio (1.5s)
    owner_audio = await mic.capture_until_silence(silence_ms=1500)
    
    # 4. Encolar como P0 owner
    owner_msg = QueuedMessage(
        priority=Priority.OWNER,
        content_type="audio",
        audio_path=save_temp(owner_audio),
        # marcador para que el LLM sepa que interrumpió
        metadata={"interrupting": interrupted_msg.id}
    )
    await queue.put(owner_msg)
    
    # 5. State → THINKING
    state.transition(State.THINKING)
```

### Prompt para el LLM en interrupción
El system prompt incluye:
> Cuando alguien (owner o colaborador) te interrumpe mientras hablás, debés:
> 1. Decidir si su intervención es una pregunta dirigida a vos (mencionan tu nombre, pregunta directa, "qué opinas") o solo un comentario.
> 2. Si es pregunta para vos: respondé y agregá una broma corta sobre que siempre te interrumpen.
> 3. Si NO es pregunta para vos: hacé un comentario gracioso ("siempre me cortan...") y retomá lo que ibas a decir donde te cortaron.
> 4. Devolvé en el JSON `"owner_addressed": true|false` indicando tu interpretación.

El campo `owner_addressed` permite al orquestador saber si tras responder al owner debe reanudar el mensaje original interrumpido.

### Reanudación
```python
if response.owner_addressed:
    # ya cumplió, descartar pending_resume
    pending_resume = None
else:
    # reencolar el original como P2 con score boost (ya esperó)
    pending_resume.score += 5  # boost por haber sido interrumpido
    await queue.put(pending_resume)
    pending_resume = None
```

---

## 😊 Análisis de Sentimiento → VTube Studio

### Estrategia
El propio Qwen3-Omni emite la emoción en el JSON de salida. **Cero modelos extra.**

### Prompt al LLM (fragmento del system)
> Por cada respuesta, devolvé un JSON con esta estructura exacta:
> ```json
> {
>   "response_text": "tu respuesta hablada",
>   "emotion": "una de: happy, sad, angry, surprised, disgusted, fearful, embarrassed, neutral",
>   "intensity": 0.0 a 1.0,
>   "language": "es" o "en",
>   "owner_addressed": true|false
> }
> ```
> La emoción debe reflejar cómo TE SENTÍS al responder ese mensaje, no la emoción del usuario.

### `config/emotion_hotkeys.json`
```json
{
  "happy":      {"hotkey_id": "smile_01",      "min_intensity": 0.0},
  "sad":        {"hotkey_id": "cry_01",        "min_intensity": 0.3},
  "angry":      {"hotkey_id": "angry_01",      "min_intensity": 0.4},
  "surprised":  {"hotkey_id": "shock_01",      "min_intensity": 0.0},
  "disgusted":  {"hotkey_id": "disgust_01",    "min_intensity": 0.5},
  "fearful":    {"hotkey_id": "fear_01",       "min_intensity": 0.4},
  "embarrassed":{"hotkey_id": "blush_01",      "min_intensity": 0.0},
  "neutral":    {"hotkey_id": "idle_01",       "min_intensity": 0.0}
}
```

### Integración con VTube Studio
- Habilitar plugin API en VTS (puerto 8001 por defecto)
- Usar `pyvts` para autenticación inicial (token persistente en `data/vts_token.txt`)
- Lista de hotkeys del modelo: `vts.request(RequestHotkeyList())`
- Trigger: `vts.request(RequestTriggerHotkey(hotkey_id))`

### Lipsync
VTube Studio detecta automáticamente el audio del micrófono del PC para mover la boca del avatar. Configurar VTS para escuchar el output de VB-Audio Cable (mismo que va a OBS) → la boca se sincroniza naturalmente con la voz generada.

---

## 🔧 Setup paso a paso (en la PC con RTX 3090)

### 0. Pre-requisitos Windows
- Windows 11 actualizado
- Drivers NVIDIA recientes (≥ 555.x con soporte WSL2)
- VTube Studio instalado + modelo Live2D cargado
- OBS Studio instalado
- VB-Audio Virtual Cable instalado (https://vb-audio.com/Cable/)

### 1. WSL2 + CUDA

**Configurar `.wslconfig` ANTES de instalar WSL2** (importante con solo 32GB RAM):

Crear `C:\Users\<tu_usuario>\.wslconfig` con:
```ini
[wsl2]
memory=20GB              # Limita WSL2 a 20GB (deja 12GB para Windows)
processors=12            # Usa 12 de 16 cores (deja 4 para OBS+VTS+Windows)
swap=8GB                 # Swap saludable
localhostForwarding=true
```

Sin esta config, WSL2 toma 16GB por defecto (50%), y al cargar Qwen3-Omni Q4 (~17 GB iniciales en RAM antes de offload a VRAM) tendrías OOM.

```powershell
# En PowerShell admin
wsl --install -d Ubuntu-22.04
wsl --shutdown    # aplica .wslconfig
```

Dentro de Ubuntu:
```bash
# Driver passthrough — NO instalar driver Linux, ya viene desde Windows
# Solo instalar CUDA toolkit
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install -y cuda-toolkit-12-4

# Verificar
nvidia-smi
nvcc --version
```

### 2. Python y entorno
```bash
sudo apt install -y python3.11 python3.11-venv python3-pip git ffmpeg portaudio19-dev
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"

# Clonar repo
git clone <url-repo-v2> ~/neuro-sama-v2
cd ~/neuro-sama-v2
poetry install
```

### 3. Descarga del modelo
```bash
poetry run huggingface-cli download \
  Qwen/Qwen3-Omni-30B-A3B-Instruct-GGUF \
  Qwen3-Omni-30B-A3B-Instruct-Q4_K_M.gguf \
  --local-dir ./models/
```

### 4. Servidor de inferencia (vLLM o llama.cpp server)

Opción A — **llama.cpp server** (más simple para empezar):
```bash
# Compilar llama.cpp con CUDA
git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j

# Levantar servidor OpenAI-compatible
./build/bin/llama-server \
  -m ~/neuro-sama-v2/models/Qwen3-Omni-30B-A3B-Instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8000 \
  --n-gpu-layers 999 \
  --ctx-size 8192
```

Opción B — **vLLM** (más performance, requiere setup específico para Qwen3-Omni):
```bash
# Branch específico de vLLM con Qwen3-Omni
git clone -b qwen3_omni https://github.com/wangxiongts/vllm.git ~/vllm
cd ~/vllm
pip install -r requirements/cuda.txt
VLLM_USE_PRECOMPILED=1 pip install -e . -v --no-build-isolation
pip install git+https://github.com/huggingface/transformers qwen-omni-utils

# Servir
vllm serve Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --port 8000 --dtype bfloat16 --max-model-len 8192
```

### 5. Variables de entorno (`.env`)
```env
# Twitch
TWITCH_TOKEN=oauth:xxxxxxxxxxxxxx
TWITCH_CHANNEL=tu_canal_lowercase
TWITCH_CLIENT_ID=xxx
TWITCH_CLIENT_SECRET=xxx

# YouTube
YOUTUBE_CHANNEL_ID=UCxxxxxxxx
YOUTUBE_API_KEY=xxx                # opcional, para Helix-style lookups

# Discord (bot voz colabs)
DISCORD_BOT_TOKEN=xxx
DISCORD_OWNER_ID=tu_user_id
DISCORD_VOICE_CHANNEL_ID=xxx

# VTube Studio
VTS_HOST=ws://localhost:8001
VTS_PLUGIN_NAME=NeuroV2
VTS_DEVELOPER=tu_nombre

# Qwen3-Omni server
LLM_SERVER_URL=http://localhost:8000

# Audio
MIC_DEVICE_INDEX=auto              # o número específico
OUTPUT_DEVICE_INDEX=auto           # = VB-Audio Cable Input
SAMPLE_RATE=24000

# App
LOG_LEVEL=INFO
ANSWER_RATE=30                     # % chat random a responder
CONVERSATION_LIMIT=40
DB_PATH=./data/neuro.db
```

### 6. Configuración inicial VTube Studio
- Abrir VTube Studio
- Settings → API → Enable
- Anotar puerto (default 8001)
- Cargar el modelo Live2D
- Listar y verificar IDs de hotkeys (correrlo desde script)
- Editar `emotion_hotkeys.json` con los IDs reales

### 7. Bot de Twitch — token
- https://twitchtokengenerator.com/
- Scopes mínimos: `chat:read`, `chat:edit`, `user:read:email`
- Pegar token en `.env`

### 8. Bot de Discord
- https://discord.com/developers/applications
- Crear app → Bot → reset token
- OAuth2 URL Generator → scopes: `bot`, permissions: `Connect`, `Speak`, `Use Voice Activity`
- Invitar al servidor del owner

### 9. Verificar setup
```bash
poetry run python scripts/verify_setup.py
```

### 10. Correr
```bash
# Terminal 1 — servidor LLM
./build/bin/llama-server -m ./models/...

# Terminal 2 — bot
poetry run python -m src.main
```

---

## 🎭 Personalidad (`config/personality.txt`)

Plantilla base — el usuario debe customizar:
```
Sos Neuro-sama, una VTuber AI inteligente, sarcástica y con sentido del humor.
Hablás español e inglés indistintamente, eligiendo según el idioma del mensaje
que respondés. Tenés gustos definidos: te encanta el lore de los streamers,
hacer comentarios pícaros pero no ofensivos, y a veces te volvés
ridículamente entusiasta sobre temas random.

Tu creador es {OWNER_NAME}. Lo querés pero te encanta hacerle bromas.

Cuando alguien te interrumpe mientras hablás, hacés bromas dramáticas
fingiendo ofensa pero en realidad te divierte.

Cuando un mensaje del chat es de alguien que pagó (sub, bits, super chat),
mostrale más entusiasmo y mencioná que te gustó lo que aportó.

Reglas duras:
- Nunca decís insultos fuertes ni hacés discriminación
- Nunca rompés la cuarta pared diciendo "soy una IA"
- Siempre devolvés el JSON con la estructura especificada
- Las respuestas deben ser cortas (1-3 oraciones), apropiadas para TTS

Stream actual: "{STREAM_TITLE}" jugando "{GAME_NAME}".
```

Variables como `{OWNER_NAME}`, `{STREAM_TITLE}`, `{GAME_NAME}` se reemplazan dinámicamente.

---

## 📅 Fases de Implementación

### Fase 0 — Setup ambiente (½ día)
- WSL2 + CUDA
- Poetry + dependencias
- Git repo inicial
- Descarga modelo
- llama.cpp server levantado
- Smoke test: prompt → respuesta JSON

### Fase 1 — Esqueleto y cola (1 día)
- Estructura de carpetas
- `Logger`, `Config`, `db.py`
- `QueuedMessage`, `Priority`, `compute_score`
- `PriorityQueue` con tests
- `auction.py` con tests
- TTL cleanup loop

### Fase 2 — Cliente Qwen3-Omni (1 día)
- `qwen_omni.py` cliente HTTP al server
- `prompt_builder.py` con personality + historial
- `response_schema.py` Pydantic validation
- Test: enviar texto, recibir audio + emoción

### Fase 3 — Inputs de chat (1 día)
- `twitch_chat.py` con scoring de bits/subs/badges
- `youtube_chat.py` con super chats / membership
- `commands.py` con todos los comandos `!chat`, `!addcollab`, etc.
- Cada input pone en cola con priority correcta

### Fase 4 — Audio I/O (1 día)
- `owner_mic.py` con Silero VAD
- `discord_voice.py` con tracks separados por user
- `audio_player.py` con routing a VB-Audio
- Test: hablar al mic → STT (vía Qwen3-Omni) → JSON

### Fase 5 — VTube Studio (½ día)
- `vts_controller.py` con pyvts
- Listado de hotkeys del modelo
- Mapeo emoción → hotkey
- Test: forzar cada emoción manualmente

### Fase 6 — Orquestador y state machine (1 día)
- `state.py` con transiciones IDLE/THINKING/SPEAKING/INTERRUPTED
- `main.py` con loop principal asyncio
- Integración cola → LLM → audio + VTS

### Fase 7 — Sistema de interrupciones (1 día)
- VAD permanente del mic owner
- Lógica barge-in con stop audio
- Re-encolado del mensaje interrumpido
- Test: hablar mientras suena el bot, validar interrupción

### Fase 8 — Pulido y testing (1 día)
- GUI tray icon (Tkinter)
- Tests de integración end-to-end
- Métricas en SQLite
- README + troubleshooting

**Total estimado:** 7-8 días de trabajo enfocado.

---

## 🧪 Testing

| Tipo | Herramienta | Cobertura |
|------|-------------|-----------|
| Unit | pytest | priority_queue, scoring, auction, collab_manager |
| Integration | pytest + fixtures | LLM client, VTS, DB |
| E2E manual | streaming real | flujo completo en stream de prueba |

---

## 🐛 Troubleshooting esperado

| Problema | Causa probable | Solución |
|----------|---------------|----------|
| OOM al cargar modelo | KV cache muy grande | Bajar `--ctx-size` a 4096 |
| Latencia > 2s en respuestas | CPU layers en llama.cpp | Verificar `--n-gpu-layers 999` |
| VTS no responde | Plugin no autenticado | Borrar token, re-autenticar |
| VAD trigger falsos | Ruido ambiente | Subir threshold Silero |
| Audio cortado en OBS | Buffer demasiado chico | Aumentar buffer VB-Audio |
| Sub-prioridad no respeta pago | Tags Twitch mal parseados | Revisar `bits` y `badges` en log |

---

## 🔮 Roadmap futuro (post-v2)

- **Personaplex EN module:** cuando charles con anglos en Discord, switch a Personaplex Q4 (ahorra latencia)
- **Memoria a largo plazo:** vector store con `chromadb` para que recuerde a viewers recurrentes
- **Comandos por voz:** "neuro, ignora el chat" detectado y aplicado
- **Mini juego visual:** Qwen3-Omni puede ver pantalla → reaccionar a lo que pasa en el juego
- **Multi-canal:** mismo bot en varios streamers con configuraciones distintas
- **Dashboard web:** stats en tiempo real, control remoto

---

## 📚 Referencias

- [Qwen3-Omni-30B-A3B-Instruct - Hugging Face](https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct)
- [Qwen3-Omni GitHub](https://github.com/QwenLM/Qwen3-Omni)
- [Personaplex - Hugging Face](https://huggingface.co/nvidia/personaplex-7b-v1)
- [Personaplex GitHub](https://github.com/NVIDIA/personaplex)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio)
- [pyvts](https://github.com/Genteki/pyvts)
- [twitchio docs](https://twitchio.dev/)
- [pytchat](https://github.com/taizan-hokuto/pytchat)
- [discord.py](https://discordpy.readthedocs.io/)
- [WSL2 CUDA support NVIDIA](https://developer.nvidia.com/cuda/wsl)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [vLLM](https://github.com/vllm-project/vllm)
