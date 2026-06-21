# 👁️ Plan: Visión General + Reacción para Mai-chan

> Reemplaza el enfoque acotado de [`plan_vision_wow.md`](./plan_vision_wow.md) (lectura de
> píxeles + OCR, atado a WoW) por un módulo **general**: que Mai-chan pueda "ver" *cualquier
> cosa* en pantalla —YouTube, TikToks, pelis, series, anime, gameplay— y reaccionar o comentar.
> Alineado a [`PLAN_NEURO_V2.md`](./PLAN_NEURO_V2.md); pensado para integrarse al pipeline actual.

---

## 1. Objetivo

Mai-chan mira lo que pasa en la pantalla y reacciona como una streamer: comenta un video,
se ríe de un meme, reacciona a una escena de anime, narra un gameplay. No depende de reglas
fijas por juego: **entiende la escena** mediante un modelo de visión-lenguaje (VLM), no leyendo
coordenadas. El plan de WoW sigue siendo válido como complemento opcional (OCR para texto
exacto: subtítulos, marcadores), pero el núcleo es semántico.

## 2. Por qué NO el enfoque de píxeles/OCR

El de `plan_vision_wow.md` lee colores en coordenadas fijas (barra de vida) y OCR del chat de
sistema. Funciona en WoW porque la UI está siempre en el mismo lugar. No escala a video/anime/
pelis: no hay coordenadas fijas ni barras; el contenido es *semántico* (entender qué se ve),
no *posicional*. Para eso se necesita un VLM.

## 3. Estado del prototipo (validado 2026-06-20)

Existe `src/screen_vision.py` (standalone: `poetry run python -m src.screen_vision`). Hace el
flujo completo y **funciona**:

- ✅ Captura con `PIL.ImageGrab` — **instantánea** (~0.09s a 1920×1080). No hizo falta `mss`.
- ✅ **Detección de cambio de escena** (compara miniaturas en gris) → no comenta pantallas
  estáticas. Es la pieza anti-spam.
- ✅ Reduce el frame a 1280px, lo manda al VLM por la API de Ollama (mismo patrón que
  `chat_ollama.py`), devuelve JSON `{comentario, vale_la_pena}`.
- ✅ Marcado el punto donde, integrado, irá `bot.inject_vision_message(...)` (calcado de
  `inject_mic_message`).

**Hallazgos que condicionan el plan:**

| Hallazgo | Implicancia |
|---|---|
| Ollama **v0.5.7** no soporta Qwen-VL (error 412) → actualizado a **0.30.10** | Ya se puede usar `qwen3-vl`. Update: `wsl -e bash -c "curl -fsSL https://ollama.com/install.sh \| sh"`. |
| `qwen3-vl:4b` (tag genérico) es la variante **thinking** | Se **cuelga razonando**: con 800 tokens escribió 3298 chars de `<think>` (en inglés) y **nunca** emitió la descripción. Ni `think:false` ni `/no_think` lo frenan en esta build. **Inusable.** |
| **`qwen3-vl:4b-instruct`** (variante sin thinking) | ✅ **El ganador.** JSON limpio, **español correcto**, 1 frase precisa (identificó "campo de batalla de Venganza, cuenta regresiva de 20s, varios personajes"). **2.8s en caliente** en la 1660. → default de visión. |
| `llava:7b` (respaldo) | "Ve" razonable pero **insuficiente**: ignora "1 oración" (párrafos), pierde la imagen a veces, español flojo. Solo si no se puede actualizar Ollama. |
| Primera llamada a cada modelo = **carga en frío** (~70-100s) | Y como en 6 GB no entran 2 VLM a la vez, Ollama descarga uno para cargar el otro. En caliente baja a ~3s. Usar `keep_alive` largo. |

**Conclusiones clave:** (1) confirma la **arquitectura de 2 etapas** (§5.3) — el VLM solo *describe*;
(2) para visión hay que usar la **variante `-instruct`**, nunca la genérica (que arrastra thinking).

## 4. Hardware y configuración por `.env`

**El plan está diseñado para producción (RTX 3090 24 GB).** Pero **todos los modelos y
parámetros se leen de `.env`** (vía `decouple`, como el resto del proyecto), así que la misma
base de código corre en una GPU chica de desarrollo (GTX 1660 6 GB) bajando valores sin tocar
nada. Los **defaults del código apuntan a la 3090**; el `.env` de cada máquina sobreescribe.

- **Producción:** RTX 3090 **24 GB** — el bot real, valores grandes (defaults).
- **Desarrollo (esta PC):** GTX 1660 **6 GB** — overrides en su `.env` local.

| Variable `.env` | Default (PROD 3090) | DEV (1660 6GB) | Qué controla |
|---|---|---|---|
| `VISION_VLM_MODEL` | `qwen3-vl:8b-instruct` | `qwen3-vl:4b-instruct` | Modelo de visión (¡**-instruct**!) |
| `OLLAMA_MODEL` | `qwen2.5:7b/14b` | `qwen2.5:3b` | LLM de personalidad (ya existe) |
| `VISION_INTERVAL_SECONDS` | `3` | `6` | Cada cuánto mira la pantalla |
| `VISION_NUM_PREDICT` | `128` | `64` | Tokens del VLM (↓ = ↓ latencia) |
| `VISION_MAX_WIDTH` | `1280` | `1280` | Ancho del frame enviado |
| `VISION_SCENE_THRESHOLD` | `6` | `6` | Sensibilidad al cambio de escena |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | idem | Host de Ollama (WSL2/remoto) |

Latencia esperada: **~1-3s** en la 3090, **~5-12s** en la 1660 (con salida corta).

> **Prerequisito para Qwen-VL:** actualizar Ollama a la última versión
> (https://ollama.com/download). El Ollama actual (v0.5.7) no soporta la familia Qwen-VL; hasta
> actualizarlo, en dev se usa `llava:7b` como puente. En dev corre en WSL2.

## 5. Arquitectura del módulo de visión

### 5.1 Captura
`PIL.ImageGrab.grab(bbox=...)`. `bbox=None` = pantalla completa; tupla `(l,t,r,b)` = región
(p.ej. solo la ventana del navegador/reproductor). Para multi-monitor o más rendimiento se
puede migrar a `mss` luego; hoy ImageGrab sobra.

### 5.2 Muestreo inteligente (anti-spam)
Capturar cada `INTERVAL_SECONDS`, pero **comentar solo si la escena cambió** lo suficiente
(`SCENE_CHANGE_THRESHOLD`). Sin esto, Mai-chan comentaría sin parar y el stream sería
insoportable. Es el filtro más importante.

### 5.3 Dos etapas: ver ≠ actuar
```
   frame ──► [VLM: describe objetivo] ──► descripción ──► [LLM personalidad] ──► comentario
            qwen3-vl (barato, neutro)                    qwen2.5 (carácter Mai-chan)
```
- **Etapa 1 (VLM):** "describe qué pasa en pantalla" → frase objetiva. Probado: el VLM lo hace
  bien; actuar el personaje, no.
- **Etapa 2 (LLM):** la descripción entra como un evento más al pipeline existente
  (`process_message`), y tu LLM de personalidad genera el comentario con tono, emoción y VTS,
  **reutilizando todo lo que ya tenés**.

> Atajo para demos: el prototipo tiene un modo `react` que comenta directo con el VLM (una sola
> etapa). Sirve para ver algo rápido, pero la calidad real viene de las 2 etapas.

### 5.4 Inyección a la cola
Un productor más, idéntico al micrófono. Donde el STT hace `inject_mic_message`, la visión hará
`inject_vision_message(descripcion)`, envolviendo el texto en un `FakeMessage` con autor
`"[VISIÓN]"`. Así chat, mic y visión se serializan por el mismo pipeline (sin audios solapados).

## 6. Control de reproducción — `MediaController`

**Objetivo:** que el audio del video no pise la voz de Mai-chan. Generaliza el flag
`is_speaking` actual (que hoy solo silencia el mic) a un controlador que además pausa/baja el
video. Se engancha en las transiciones `→ SPEAKING` y `speak_done →` de la state machine del v2.

### 6.1 Condición de corte (no es "siempre que habla")
Cortar **solo si** Mai-chan va a hablar **Y** el video tiene voz/diálogo *en ese momento*. Si el
video es música, acción o silencio → habla encima sin tocar nada. La señal "¿hay voz ahora?" la
da **Silero VAD** (ya en el v2 para barge-in) apuntado al **audio del sistema/loopback**, no al
mic. Segundo uso de una pieza ya planificada.

### 6.2 Pausa vs Ducking
- **Pausa** = **tecla multimedia global** Play/Pause (universal: navegador, VLC, Netflix,
  Spotify). Un único evento, sin integrar fuente por fuente. Es *toggle*: el controlador recuerda
  el estado para no despausar por error.
- **Ducking** = bajar el volumen del video al hablar y restaurarlo al terminar. **No puede ser
  global** (bajaría también la voz de Mai-chan): se hace **por aplicación** con `pycaw` (Windows
  Core Audio), bajando solo la sesión de `chrome.exe`/`vlc.exe`.

### 6.3 Matriz de decisión por fuente
La fuente define la *técnica preferida*; el VAD decide *en vivo* si hace falta cortar:

| Fuente | ¿Diálogo ahora? (VAD) | Acción al hablar |
|---|---|---|
| Gameplay | — | Narra en vivo, **no corta** |
| Video/YouTube (música, acción) | No | Habla encima |
| Video/YouTube (hay voz) | Sí | **Ducking** (pycaw baja el navegador) |
| Película/serie/anime | Sí | **Pausa** (tecla multimedia) |
| Película/anime (escena muda) | No | Habla encima |

Esto produce automáticamente los dos comportamientos que Edgar quería conviviendo:
*pausa-y-reacciona* (pelis con diálogo) y *reacciona-en-vivo* (lo demás).

### 6.4 Esbozo
```python
class MediaController:
    fuente: str            # gameplay | navegador | reproductor_local
    tecnica: str           # "pausa" | "ducking" | "ninguno"  (según fuente)
    _vad_sistema: SileroVAD # ¿hay voz en el audio del video?
    _pausado: bool

    def antes_de_hablar(self):
        if self.fuente == "gameplay": return
        if not self._vad_sistema.hay_voz(): return     # video sin diálogo → encima
        if self.tecnica == "pausa":   self._tecla_multimedia(); self._pausado = True
        if self.tecnica == "ducking": self._pycaw_bajar(self.fuente)

    def al_terminar(self):
        if self._pausado: self._tecla_multimedia(); self._pausado = False
        else:             self._pycaw_restaurar()
```

> **Alcance: solo Nivel 1** (simular inputs concretos: tecla multimedia, volumen). NADA de
> agente autónomo que controle la PC ("Nivel 2") — eso queda fuera de este plan por lento y
> frágil en vivo.

## 7. Modos de atención (video vs chat)

No requiere arquitectura nueva: son pesos en la cola priorizada del v2. Configurable por el
admin (`!mode ...`) o elegido por Mai-chan al arrancar (ver §9):

| Modo | Comportamiento |
|---|---|
| `VIDEO_FIRST` | Reacciona al video; el chat se acumula y se responde en huecos/al final |
| `CHAT_FIRST` | Prioriza chat; comenta el video solo en silencios |
| `HYBRID` | Ambos compiten naturalmente (default) |
| `AUTO` ⏳ | Mai-chan elige según el contenido del día (lee su agenda) — **no implementado** (ver §12) |

## 8. Memoria (para que sea "independiente") — 3 capas

RAG resuelve **memoria**, no **autonomía** (§9). Y no todo es RAG:

1. **Estructurada → SQLite (NO RAG).** Datos exactos: `viewers(user_id, primera_vez,
   n_mensajes, ultima_visita)` → "¿es nuevo?" es un `SELECT`, no un embedding. También
   `agenda(fecha, que_hacer, sugerido_por, estado)` para planear streams futuros. El v2 ya usa
   SQLite; solo se agregan tablas.
2. **Episódica → resúmenes por stream.** Al cerrar cada stream, el LLM genera un resumen corto
   ("Stream 12/06: con Pedro vimos Akira, prometimos la secuela"). Se guarda. Al inicio del
   próximo, se inyectan los últimos N al contexto.
3. **Semántica → RAG (BGE-M3 + ChromaDB), opcional.** Solo cuando los resúmenes/transcripciones
   no entren en contexto (cientos de streams). Recupera por *significado*. El v2 ya lo prevé.

**Regla:** datos exactos → SQLite; recuerdos en lenguaje natural buscados por significado → RAG.
Empezar con 1 y 2; sumar 3 cuando el volumen lo pida.

## 9. Autonomía — el "director loop" (falta en el v2)

La cola del v2 es 100% reactiva. Para que Mai-chan actúe sola falta un productor extra:

- **`director_loop`:** cada N segundos, si hay silencio (nada en chat, nada nuevo en pantalla),
  encola proactivamente una acción de baja prioridad: comentar el video, retomar su "plan del
  día" (de la agenda), saludar a un viewer recurrente, soltar un pensamiento.
- **La visión encaja como otro productor** que compite en la cola; cuando no hay nada visual
  interesante, el director rellena.
- Opcional: **estado interno** (humor, energía, tema) persistente que sesga sus reacciones y da
  continuidad.

Las 3 capas de prompt (para que quede claro que nadie tipea en vivo):

| Capa | Qué | Quién/cuándo | Frecuencia |
|---|---|---|---|
| A. Personalidad | "Sos Mai-chan…" | Edgar, en `prompt_chat.txt` | casi nunca cambia |
| B. Brief de sesión | "Hoy reaccionás al video X" | **auto-generado** desde la agenda, o 1 línea al arrancar | 1×/stream |
| C. Frame al VLM | "describe la pantalla" | el código, interno | cada 2-8s, invisible |

## 10. Fases sugeridas

- **Fase V0 — prototipo (hecho).** `screen_vision.py` validado en dev con llava.
- **Fase V1 — calidad del VLM (✅ hecho).** Ollama actualizado a 0.30.10; elegido
  **`qwen3-vl:4b-instruct`** (dev) / **`:8b-instruct`** (prod) tras descartar la variante
  *thinking* (se cuelga) y `llava:7b` (calidad floja). Latencia ~2.8s en caliente en la 1660.
  Defaults del código y `.env` actualizados a la variante `-instruct`.
- **Fase V2 — integración al bot (✅ hecho).** `ScreenVision.watch_loop` (productor async,
  calcado de `LocalSTT`) respeta `is_speaking` y hace `inject_vision_message`
  (`FakeMessage("[VISIÓN]")`, texto envuelto en contexto). La etapa 2 (personalidad) es el
  `process_message` existente. Se arranca desde `main.py` si `VISION_ENABLED=true`.
- **Fase V3 — `MediaController` (✅ Nivel 1, completo).** `src/media_controller.py`: tecla
  multimedia (ctypes/Win32) + `pycaw` ducking por app; matriz por fuente; enganchado al
  `is_speaking` actual (en `_generate_and_speak`, alrededor de `get_speech_by_text`). El **VAD de
  loopback** ya está: `src/loopback_vad.py` (`LoopbackVAD`) captura el audio del sistema (loopback
  WASAPI vía `pyaudiowpatch`) en un hilo aparte y corre **Silero VAD** —reusado de
  `faster-whisper`, sin modelo nuevo— para decidir *en vivo* si hay voz; `_hay_dialogo()` lo
  consulta cuando `MEDIA_VAD_ENABLED`, y si no, cae a `MEDIA_ASSUME_DIALOGO`. Validado en dev: el
  loopback se detecta y Silero distingue voz real de silencio/tono. Tunable por `.env`
  (`MEDIA_VAD_THRESHOLD`, `MEDIA_VAD_HOLD_SECONDS`).
- **Fase V4 — modos de atención (✅ hecho).** La cola pasó de `asyncio.Queue` plana a
  `asyncio.PriorityQueue` (tuplas `(prioridad, secuencia, mensaje)`; el `seq` da FIFO en
  empates). `ATTENTION_MODES` define la prioridad de cada fuente (chat/mic/visión) por modo;
  el micro va siempre primero. Configurable por `.env` (`ATTENTION_MODE`) y en vivo con el
  comando **`!mode video|chat|hybrid`** (solo el dueño del canal). Como efecto colateral, los
  comandos (`!hola`, `!mode`) ya **no** se mandan al LLM: se atienden en `event_message`.
  **Pendiente (a futuro):** el modo `AUTO` de §7 — que al arrancar fije el modo solo según la
  agenda del día — quedó sin implementar; hoy el modo inicial viene de `.env`. Ver §12.
- **Fase V5 — memoria + director (✅ hecho).** `src/memory.py` con **SQLite de la stdlib**
  (sin instalar nada): tablas `viewers` (nuevo/recurrente), `agenda` (plan del día) y
  `stream_summaries`. El bot registra viewers en cada chat real (y avisa al LLM si es la primera
  vez), antepone un **brief de sesión** (resúmenes recientes + agenda) al prompt al arrancar
  (capa B), y al cerrar **genera y guarda un resumen** del stream (memoria episódica). El
  **`director_loop`** (opt-in, `DIRECTOR_ENABLED`) habla en los silencios retomando la agenda o
  soltando un comentario (prioridad mínima en la cola). Comando **`!agenda [texto]`** para
  consultar/poblar el plan. (RAG semántico = capa 3, aún pendiente, solo si el volumen lo pide.)

## 11. Dependencias nuevas

- `pillow` (ya instalado) — captura. Opcional `mss` (multi-monitor/perf).
- `pycaw` — ducking por aplicación (Windows).
- `pyaudiowpatch` (instalado) — captura del loopback WASAPI para el VAD (el `pyaudio` normal no
  hace loopback). El **modelo Silero VAD se reusa de `faster-whisper`**, así que no hay dep nueva
  del modelo.
- Modelo `qwen3-vl:*` en Ollama (tras actualizarlo).

## 12. Pendientes y tareas a futuro

Las fases V0–V5 están **completas** (incluido el VAD de loopback de V3). Lo que queda es opcional
y no bloquea usar el bot:

1. **Modo de atención `AUTO`** (§7) — al arrancar, leer la agenda del día (ya existe en
   `memory.py`) y fijar solo el modo inicial (p.ej. "hoy reacciono a un video" → `VIDEO_FIRST`),
   en vez de tomarlo de `.env`. Reusa el brief de sesión y los modos ya implementados. *Tarea
   chica, a futuro.*
2. **Capa 3 de memoria: RAG semántico** (§8) — BGE-M3 + ChromaDB para recuperar recuerdos por
   significado. Solo cuando los resúmenes no entren en contexto (cientos de streams). *Diferido
   por diseño hasta que el volumen lo pida.*
3. **Afinar calidad/latencia de visión** — pulir el prompt de la etapa 1 (descripción objetiva)
   y, en la 3090, evaluar `qwen3-vl:8b-instruct` y un LLM de personalidad más grande
   (`qwen2.5:14b`). *Ajuste fino, no bloqueante.*
4. **Tuning del VAD en vivo** — calibrar `MEDIA_VAD_THRESHOLD` / `MEDIA_VAD_HOLD_SECONDS` con
   contenido real en cada máquina (los defaults 0.5 / 1.5s son un punto de partida).
