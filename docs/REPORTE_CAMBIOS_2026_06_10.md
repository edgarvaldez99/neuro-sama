# 📝 Reporte de Cambios — 10 de Junio de 2026

## 🎯 Objetivo de la sesión
Migrar el bot de Neuro-Sama (Mai-chan) a una arquitectura **100% local y gratuita**, eliminando dependencias de APIs de pago (OpenAI, ElevenLabs, etc.) y mejorando la latencia.

---

## 🚀 Logros Alcanzados

### 1. Inteligencia Local (LLM)
- **Motor:** Se instaló y configuró **Ollama**.
- **Modelo:** Se migró a **Qwen 2.5 14B**, un modelo mucho más potente y apto para la RTX 3090 que el Llama 3.1 8B inicial.
- **Integración:** Se creó `src/chat_ollama.py` para manejar peticiones locales asíncronas.

### 2. Voz Local (TTS)
- **Motor:** Se instaló la librería oficial de **Piper TTS**.
- **Modelo de Voz:** Se configuró la voz **"Ald" (Español México, Medium)**.
- **Arquitectura:** Se creó `src/texttospeech_piper.py` para generar audio sin depender de internet.

### 3. Orquestación y Rendimiento
- **Asincronía Total:** Se refactorizó `src/twitchbot.py` para usar `asyncio`. El bot ya no se "congela" mientras piensa o habla.
- **Cola de Mensajes:** Se implementó un `asyncio.Queue` y un `message_worker` para que los mensajes se procesen en orden secuencial sin saltarse el audio.
- **Nombres Únicos:** Se implementó la generación de nombres de archivo temporales con timestamps (`audio_1234567.wav`) para evitar errores de permisos de Windows.

### 4. Personalidad
- **Ajuste de Prompt:** Se reescribió `prompt_chat.txt` con reglas estrictas para que Mai-chan mantenga su personaje de streamer y no revele que es una IA.

---

## ⚠️ Problemas Pendientes (Para continuar mañana)

### 🔊 El "Misterio del Audio Silencioso"
- **Estado:** Los archivos `.wav` se están generando correctamente en la carpeta raíz y ya no están corruptos. Ollama responde bien.
- **Síntoma:** Aunque el sistema de DEBUG indica que VLC inicia y termina la reproducción, el usuario no escucha el sonido por los altavoces.
- **Posibles causas:**
    - Conflicto de rutas de Windows en la librería `python-vlc`.
    - El archivo se borra demasiado rápido antes de que los buffers de audio se vacíen.
    - El dispositivo de salida de audio de VLC no está configurado correctamente en el código.

### 🛠️ Pruebas para mañana:
1.  **Mantener archivos:** Desactivar el borrado automático de los `.wav` para inspeccionarlos manualmente tras la ejecución.
2.  **Cambio de Player:** Si VLC sigue dando problemas en Windows, considerar usar `pygame.mixer` o `winsound` para mayor compatibilidad nativa.
3.  **VTube Studio:** Una vez que el audio suene, conectar el sistema de emociones a los Hotkeys de VTS.

---

## 📂 Archivos Modificados/Creados
- `src/chat_ollama.py` (Nuevo)
- `src/texttospeech_piper.py` (Nuevo)
- `src/twitchbot.py` (Refactorizado)
- `src/generate_audio.py` (Refactorizado con Debugs)
- `prompt_chat.txt` (Actualizado)
- `models/tts/` (Carpeta con modelos locales)

---

# 🔧 Sesión 2 (10/Jun/2026, tarde) — Debug con Claude Code

## ✅ El audio YA SUENA
El "misterio del audio silencioso" quedó resuelto: en la prueba de hoy VLC reproduce
correctamente por los altavoces (`DEBUG: Reproducción finalizada.` con el sonido audible).
**Pendiente de confirmar mañana**: validar que se escuche consistentemente en todos los mensajes.

## 🐞 Errores detectados en esta corrida

### 1. `WinError 32` al borrar el `.wav`
```
[WinError 32] El proceso no tiene acceso al archivo porque está siendo
utilizado por otro proceso: 'audio_1781136093340.wav'
```
- **Causa:** `python-vlc` libera el handle del archivo de forma **diferida** en Windows.
  El `os.remove()` corría inmediatamente después de `media.release()`, cuando VLC todavía
  no había soltado el archivo → fallaba el borrado y se acumulaban los `.wav` en la raíz.
- **Arreglo:** función `_remove_with_retry()` en `src/generate_audio.py` que reintenta el
  borrado hasta 15 veces (~3s) con pausas de 0.2s antes de rendirse.

### 2. El modelo (qwen2.5:14b) filtra texto en chino
```
Mai-chan: Ay, esos sonidos inquietantes... 😳音频中提到的游戏声音让Mai-chan感到有些不安...
```
- **Causa:** qwen2.5 a veces cuela caracteres CJK (chino/japonés) al final de la respuesta.
  Eso se guardaba en el historial Y se mandaba al TTS español (que lo destrozaría).
- **Arreglo (doble):**
  - `strip_cjk()` en `src/utils.py` elimina rangos CJK antes de guardar en historial y hablar
    (aplicado en `src/twitchbot.py`, justo después de la respuesta de Ollama). **Esta es la
    garantía dura.**
  - Regla 6 nueva en `prompt_chat.txt`: "Responde SIEMPRE en español. NUNCA uses caracteres
    chinos, japoneses…" (ataca la causa raíz a nivel prompt).

### 3. Riesgo de audio cortado prematuramente
- **Causa:** se usaba `media.is_playing()` que podía devolver `False` **antes** de que VLC
  arrancara la reproducción (no porque hubiera terminado), cortando el audio.
- **Arreglo:** ahora `play_audio()` espera primero a `State.Playing` (hasta ~5s) y recién
  después vigila el fin con `get_state()`.

## 📂 Archivos modificados en esta sesión
- `src/generate_audio.py` — borrado con reintentos + detección de reproducción vía `get_state()`
- `src/utils.py` — nueva función `strip_cjk()` (+ `import re`)
- `src/twitchbot.py` — importa y aplica `strip_cjk()` sobre la respuesta de Ollama
- `prompt_chat.txt` — regla 6 (solo español, sin CJK)
- `CLAUDE.md` — creado (guía de arquitectura para Claude Code)
- Se borraron los `.wav` huérfanos acumulados (quedó `audio_1781135120153.wav` bloqueado por
  un proceso; se borra solo al cerrar el bot/VLC).

## 💡 Recomendaciones para mañana (en orden de prioridad)

1. **Confirmar que strip_cjk + la regla del prompt eliminan el chino.** Si igual aparece,
   bajar la `temperature` en `chat_ollama.py` de 0.7 a ~0.5, o probar el modelo `qwen2.5:14b`
   con un prompt de sistema más corto y firme.

2. **`filter_message.py` descarga corpus de NLTK EN CADA MENSAJE.** Por eso aparece el bloque
   `[nltk_data] Downloading...` repetido en cada turno → es lento e innecesario. Mover los
   `nltk.download(...)` al nivel de módulo (que corran una sola vez al importar). Además su
   lógica de filtrado es muy agresiva/rara (chequea si CADA palabra del mensaje está en el
   diccionario inglés Y español) y probablemente descarta mensajes válidos. **Revisar si vale
   la pena ese filtro o simplificarlo** a solo longitud + blacklist.

3. **Doble escritura del `.wav`:** Piper escribe el archivo, lo lee a bytes, y `play_audio` lo
   vuelve a escribir con el mismo nombre. Funciona pero es redundante. Limpiar: que Piper
   pase el path y `play_audio` solo reproduzca (sin reescribir).

4. **Si VLC sigue dando lata en Windows**, la alternativa nativa es `winsound.PlaySound` (solo
   WAV, sin dependencias) o `pygame.mixer`. Pero por ahora VLC anda, no tocar si no hace falta.

5. **Próximo hito (del plan v2):** una vez estable el audio, conectar el sistema de emociones a
   los Hotkeys de VTube Studio. Ver `docs/PLAN_NEURO_V2.md` (sección "Análisis de Sentimiento").

## 🧠 Contexto rápido para retomar
- Entrypoint: `python main.py` desde la raíz. El modo está hardcodeado: `mode = Mode.VLC_CLOUD`
  (el stack local nuevo: Ollama + Piper + VLC).
- Servicios que tienen que estar prendidos: **Ollama** (`qwen2.5:14b`) y los modelos **Piper**
  en `models/tts/es_MX-ald-medium.onnx`.
- Flujo: chat Twitch → `asyncio.Queue` → `message_worker` → Ollama → `strip_cjk` → Piper TTS → VLC.
- Hay una guía de arquitectura completa en `CLAUDE.md` (raíz del repo).

---
**Mai-chan recuperó la voz 🎙️ y dejó de hablar en chino 🀄→🚫. Mañana: limpiar el filtro NLTK y conectar VTube Studio.**

---

# 🔧 Sesión 3 (11/Jun/2026) — Optimizaciones y VTube Studio

## ✅ Logros Alcanzados hoy

### 1. Limpieza y Rendimiento (Refactor)
- **NLTK Optimizado:** Se movieron las descargas y la carga de corpus en `src/filter_message.py` al nivel de módulo. El bot ya no se congela descargando datos en cada mensaje.
- **Pipeline de Audio:** Se eliminó la doble escritura/lectura de archivos `.wav`. Ahora Piper escribe y VLC reproduce directamente del disco.
- **Limpieza Rotativa:** Se implementó un sistema que mantiene solo los **últimos 3 audios** en la carpeta raíz, borrando automáticamente los antiguos para ahorrar espacio.
- **Limpieza de Texto para TTS:** Nueva función `clean_text_for_tts` que elimina emojis y símbolos antes de hablar, evitando que el bot lea "cara sonriente" o "asterisco" literalmente.

### 2. Estabilidad de IA (Ollama)
- **Temperatura:** Se bajó de 0.7 a **0.5**. Mai-chan es ahora más coherente y ha dejado de filtrar caracteres chinos (CJK).

### 3. VTube Studio (Integración Inicial)
- **JSON Mode:** El bot ahora responde en formato JSON estructurado: `{"response_text": "...", "emotion": "happy"}`.
- **Controlador VTS:** Se creó `src/vts_controller.py` usando la librería `pyvts` y peticiones crudas de la API oficial (`HotkeysInCurrentModelRequest`).
- **Lipsync:** La boca se mueve correctamente sincronizada con el audio (vía VB-Audio Cable).
- **Emociones:** El bot detecta la emoción en el texto y busca el Hotkey correspondiente.

## ⚠️ Problemas Pendientes

### 🎭 El "Misterio de los Hotkeys Vacíos"
- **Estado:** El bot se conecta y autentica en VTube Studio (v1.35.7), pero la lista de hotkeys regresa vacía (`[]`).
- **Síntoma:** Aunque el bot detecta el modelo (`akari`), no puede activar las expresiones.
- **Causas probables:**
    - Falta activar el icono de la **máscara/cara** (permiso de expresiones) en la lista de plugins de VTS.
    - El modelo necesita estar "enfocado" o la API de VTS requiere una suscripción a eventos más profunda.

## 📂 Archivos Modificados hoy
- `src/filter_message.py` — NLTK rápido y filtros suaves.
- `src/generate_audio.py` — Limpieza rotativa y soporte para archivos persistentes.
- `src/texttospeech_piper.py` — Integración con filtro de texto.
- `src/utils.py` — Filtros de texto CJK y Emojis.
- `src/vts_controller.py` (Nuevo) — Conexión con VTube Studio.
- `src/twitchbot.py` — Lógica para procesar JSON y emociones.
- `prompt_chat.txt` — Instrucciones de formato JSON y emociones.

### 🛠️ Próximos pasos y tareas pendientes:
1. **Forzar Permisos VTS:** Investigar por qué la lista de hotkeys regresa vacía (posible problema de enfoque o suscripción a eventos en VTS 1.35.7).
2. **Interfaz Visual (Launcher):** Crear una GUI (con CustomTkinter o un archivo .bat avanzado) para encender el entorno virtual y el bot con un solo botón.
3. **Conexión de Emociones:** Una vez resuelto el punto 1, validar que el cambio de expresiones sea fluido durante el stream.
