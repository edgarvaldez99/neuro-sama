import asyncio
import os
import sys

# --- FIX: Cargar DLLs de NVIDIA para Windows ---
if sys.platform == "win32":
    import site

    # Buscar carpetas 'bin' dentro de paquetes nvidia en site-packages
    for s_path in site.getsitepackages():
        nvidia_path = os.path.join(s_path, "nvidia")
        if os.path.exists(nvidia_path):
            for root, dirs, _ in os.walk(nvidia_path):
                if "bin" in dirs:
                    bin_path = os.path.join(root, "bin")
                    # En Python 3.8+, os.add_dll_directory es necesario
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(bin_path)
                    # También añadir al PATH por si acaso (para ctranslate2)
                    os.environ["PATH"] = bin_path + os.pathsep + os.environ["PATH"]

# pylint: disable=wrong-import-position
import numpy as np
import pyaudio
from faster_whisper import WhisperModel

# Configuración del modelo
# Con una 3090, el modelo 'medium' o incluso 'large-v3' iría sobrado,
# pero 'small' es instantáneo y muy preciso para español.
MODEL_SIZE = "small"
DEVICE = "cuda"  # Usar la RTX 3090
COMPUTE_TYPE = "float16"  # Optimizado para GPU


class LocalSTT:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        print(f"DEBUG: Cargando modelo Faster-Whisper ({MODEL_SIZE}) en {DEVICE}...")

        # Guardamos el modelo en la carpeta models/stt para que sea 100% local
        model_path = os.path.join(os.getcwd(), "models", "stt")
        os.makedirs(model_path, exist_ok=True)

        self.model = WhisperModel(
            MODEL_SIZE,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
            download_root=model_path,
        )

        # Configuración de audio
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self.chunk = 1024
        self.audio = pyaudio.PyAudio()

        # Umbrales para detección de silencio (VAD simple)
        self.silence_threshold = 500  # Ajustar según el ruido de tu micro
        self.silence_chunks = (
            35  # ~2.2 segundos de silencio para procesar (más paciente)
        )
        # Tope de seguridad: si alguien (o el ruido) habla sin parar, forzamos la
        # transcripción para que la lista `frames` no crezca sin límite.
        # ~15s / 0.064s por chunk ≈ 234 chunks.
        self.max_record_chunks = 234

    async def listen_loop(self):
        """Bucle infinito que escucha el micrófono y procesa cuando hay voz."""
        stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
        )

        print("DEBUG: Escuchador de micrófono activo. ¡Puedes hablarle a Mai-chan!")

        frames = []
        silent_count = 0
        is_speaking = False

        while True:
            # Leer audio del micro SIEMPRE para evitar que el buffer se llene.
            # IMPORTANTE: stream.read() es BLOQUEANTE (~64ms). Usamos to_thread
            # para no congelar el event loop; si no, twitchio no procesa el chat.
            try:
                data = await asyncio.to_thread(
                    stream.read, self.chunk, exception_on_overflow=False
                )
            except Exception as e:
                print(f"DEBUG: Error de hardware en micrófono: {e}")
                await asyncio.sleep(0.1)
                continue

            # Si el bot habla, tiramos el audio para no procesar su propia voz
            if self.bot.is_speaking:
                if frames:
                    frames = []
                    is_speaking = False
                    silent_count = 0
                continue

            audio_data = np.frombuffer(data, dtype=np.int16)
            amplitude = np.abs(audio_data).mean()

            if amplitude > self.silence_threshold:
                if not is_speaking:
                    print("DEBUG: Voz detectada...")
                    is_speaking = True
                frames.append(data)
                silent_count = 0

                # Tope de seguridad: si la frase se vuelve eterna (ruido constante
                # que nunca baja del umbral), forzamos la transcripción para que
                # `frames` no crezca sin límite.
                if len(frames) >= self.max_record_chunks:
                    print(
                        "DEBUG: Frase demasiado larga, transcribiendo por seguridad..."
                    )
                    await self._process_utterance(frames)
                    frames = []
                    is_speaking = False
                    silent_count = 0
            else:
                if is_speaking:
                    frames.append(data)
                    silent_count += 1

                    # Si el silencio dura lo suficiente (~2.5s), procesamos lo grabado
                    if silent_count > self.silence_chunks:
                        print("DEBUG: Silencio detectado, transcribiendo...")
                        await self._process_utterance(frames)
                        frames = []
                        is_speaking = False
                        silent_count = 0

            # Sin sleep artificial: el to_thread de stream.read ya cede el control
            # al event loop y marca el ritmo a tiempo real. Un sleep extra acá nos
            # haría leer más lento que el audio y desbordaría el buffer del micro.

    async def _process_utterance(self, frames):
        """Transcribe lo grabado e inyecta el texto al bot si es válido."""
        audio_buffer = b"".join(frames)
        text = await self._transcribe(audio_buffer)
        if text and len(text) > 2:
            print(f"DEBUG: Micro transcribió: {text}")
            await self.bot.inject_mic_message(text)
        else:
            print("DEBUG: Transcripción vacía o muy corta.")

    async def _transcribe(self, audio_buffer):
        """Convierte el buffer de audio en texto usando Faster-Whisper."""
        # Convertir buffer a array de float32 entre -1 y 1 (formato que pide Whisper)
        audio_np = (
            np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
        )

        # Ejecutar en thread para no bloquear el loop asíncrono
        def run_whisper():
            # vad_filter=True usa Silero VAD para descartar tramos sin voz real,
            # lo que evita que Whisper "alucine" texto repetitivo sobre ruido o
            # silencio (ej: "lo que es lo que es...").
            segments, _ = self.model.transcribe(
                audio_np, beam_size=5, language="es", vad_filter=True
            )
            return " ".join([segment.text for segment in segments]).strip()

        try:
            return await asyncio.to_thread(run_whisper)
        except Exception as e:
            print(f"DEBUG: Error en transcripción: {e}")
            return ""
