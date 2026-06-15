# 📊 Reporte de Mejoras y Cambios - 13 de Junio 2026

Este documento detalla las implementaciones, optimizaciones y correcciones realizadas en el proyecto **neuro-sama** (Mai-chan Bot) para habilitar interacción por voz local y mejorar la gestión de recursos.

## 🎤 1. Sistema de Voz Local (STT)
Se integró un sistema de **Speech-to-Text (STT) 100% local** para permitir que el streamer hable directamente con Mai-chan sin usar internet.

- **Tecnología**: [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper).
- **Aceleración por Hardware**: Configurado para usar la **NVIDIA RTX 3090 (CUDA)**.
- **Modelo**: `small` (balance ideal entre velocidad instantánea y precisión en español).
- **Ubicación de Modelos**: Guardados en `models/stt/` para evitar descargas futuras.

### Mejoras de Sensibilidad y VAD:
- **Silencio**: Ajustado a ~2.5 segundos para permitir pausas naturales al hablar.
- **Sordera Inteligente**: El micrófono se desactiva automáticamente mientras el bot está reproduciendo audio para evitar feedback (eco).
- **Lectura Continua**: El stream de audio se lee constantemente para evitar bloqueos del controlador de audio en Windows.

## 📂 2. Gestión de Archivos y Carpetas
Se profesionalizó el manejo de archivos temporales de audio.

- **Nueva Carpeta `audios/`**: Centraliza todos los archivos `.mp3` y `.wav` generados.
- **Limpieza al Inicio**: El bot vacía automáticamente esta carpeta cada vez que se enciende (`main.py` -> `clean_audio_folder`).
- **Limpieza Rotativa**: Se mantiene la lógica de conservar solo los últimos 3 audios durante la ejecución para optimizar espacio.

## 🛠️ 3. Correcciones Técnicas (Bugfixes)

### Estabilidad en Windows:
- **DLLs de NVIDIA**: Se solucionó el error `cublas64_12.dll not found` mediante la instalación de redistribuibles (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) y un parche de carga dinámica en `src/stt_local.py`.
- **Rutas Absolutas**: Se migró de rutas relativas a rutas absolutas normalizadas para evitar archivos de 0 bytes y errores de reproducción en VLC.

### Compatibilidad de Objetos:
- **FakeMessage**: Se creó una clase para simular mensajes de Twitch provenientes del micrófono, incluyendo el atributo `tags` y evitando que intenten ejecutar comandos de la API de TwitchIO que causarían crashes.

## 🔴 4. Corrección Crítica: Event Loop Bloqueado (Post-mortem)

Tras integrar el micrófono, el bot **dejó de responder al chat** y los audios de Edge TTS salían **corruptos / incompletos**. Ambos síntomas resultaron ser **el mismo bug**.

### Causa raíz
El nuevo `main.py` corre el bot de Twitch y el escuchador de micrófono en el **mismo event loop** (`asyncio`). Dentro de `stt_local.py`, la lectura del micro usaba `stream.read()` de PyAudio, que es una llamada **bloqueante** (~64 ms por chunk). Al correr en el hilo del event loop, lo congelaba constantemente, y eso provocaba dos fallas en cadena:

1. **Twitch ahogado**: TwitchIO no conseguía tiempo de loop para procesar el chat → el bot parecía mudo.
2. **Audio corrupto**: Edge TTS descarga el audio por WebSocket de forma asíncrona. Con el loop bloqueado, la descarga se interrumpía y el `.mp3` quedaba incompleto (los "archivos de 0 bytes" del punto 3 eran el mismo problema).

### Soluciones aplicadas
- **`asyncio.to_thread` para la lectura del micro** (`stt_local.py`): la llamada bloqueante de PyAudio se delega a un hilo, dejando el event loop libre para TwitchIO y para la descarga de Edge TTS. **Este fue el arreglo principal: resolvió la falta de respuesta y el audio corrupto de una sola vez.**
- **`asyncio.gather` en vez de `create_task` suelto** (`main.py`): antes, si `bot.start()` fallaba, la excepción se tragaba en silencio y el bot quedaba mudo sin explicación. Ahora los errores se propagan y se ven en consola.

### Mejoras adicionales del STT
- **Filtro VAD en Whisper** (`vad_filter=True` en `stt_local.py`): Silero VAD descarta los tramos sin voz antes de transcribir, eliminando las "alucinaciones" de texto repetitivo (ej: *"¿lo que es lo que es...?"*) que Whisper generaba sobre ruido o silencio.
- **Micro silenciado durante todo el procesamiento** (`twitchbot.py`): el flag `is_speaking` ahora envuelve **todo** `process_message` (no solo la reproducción), así el STT también ignora la entrada mientras Ollama piensa. Se restaura en un `finally` para que el micro nunca quede sordo de forma permanente ante un error.

### Optimización del buffer de micrófono (Paso 1)
Para evitar que el buffer de PyAudio se desborde (audio "picado" que arruina la transcripción):

- **Eliminado el `await asyncio.sleep(0.01)`** del loop de captura: era un resto de la versión bloqueante vieja. Con `to_thread`, la lectura ya cede el control al event loop; el sleep extra hacía que leyéramos **más lento que el tiempo real** (64 ms de audio cada ~74 ms), atrasándonos y llenando el buffer del micro. Sin él, se consume al ritmo exacto del audio.
- **Tope de duración (`max_record_chunks`, ~15s)**: si el ruido constante mantiene el VAD activo y nunca se detecta silencio, la lista `frames` crecía sin límite (fuga de memoria + la frase nunca cerraba). Ahora se fuerza la transcripción al llegar al tope.
- Refactor menor: la transcripción + inyección al bot se extrajo al helper `_process_utterance()` para no duplicarla entre el corte por silencio y el corte por duración.

## 🚀 5. Estado Actual del Stack
- **IA (LLM)**: Ollama (Local).
- **Voz Salida (TTS)**: Edge TTS (Online) / Piper (Local).
- **Voz Entrada (STT)**: Faster-Whisper (Local GPU).
- **Avatar**: VTube Studio vía WebSocket + Lipsync por audio.

## ⚠️ Notas para Futuras Mejoras
- **Sensibilidad del Mic**: Si hay mucho ruido ambiental, el valor `silence_threshold` en `src/stt_local.py` puede subirse de 500 a 800-1000.
- **Modelos STT**: Con 24GB de VRAM, se podría probar el modelo `medium` o `large-v3` para una precisión casi perfecta, aunque el `small` es notablemente más rápido.
- **Captura en modo callback (Paso 2 — pendiente)**: el Paso 1 evita el desborde del buffer en condiciones normales, pero la solución "a prueba de balas" es pasar PyAudio a **modo callback** (`stream_callback`). En vez de leer en un loop, PyAudio invoca una función desde su propio hilo de alta prioridad cada vez que hay un chunk y lo empuja a una `queue.Queue`; el loop async solo consume de la cola. Así, capturar y procesar quedan **desacoplados** y el buffer de hardware nunca desborda (ni siquiera durante la transcripción, que hoy deja un hueco de lectura). Es además la base natural para el "barge-in con Silero VAD" descrito en `PLAN_NEURO_V2.md`.
