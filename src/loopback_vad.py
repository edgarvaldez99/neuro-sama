"""
LoopbackVAD — ¿el audio del sistema (lo que SUENA: video, música, peli) tiene
VOZ en este momento?

Es la señal que le faltaba al MediaController para decidir *en vivo* si cortar:
solo tiene sentido pausar/duckear el contenido si éste tiene diálogo justo
cuando Mai-chan va a hablar. Si suena música, acción o una escena muda, habla
encima sin tocar nada. Ver docs/plan_vision_general.md §6.1 y §6.3.

Cómo funciona:
  - Un hilo en segundo plano captura el **loopback WASAPI** (lo que sale por los
    parlantes por defecto) con ``pyaudiowpatch`` —el ``pyaudio`` normal NO hace
    loopback en Windows— y lo pasa por **Silero VAD**, el mismo modelo que ya
    trae ``faster-whisper`` (cero dependencias nuevas para el VAD en sí).
  - El VAD detecta *voz humana* específicamente (no energía a secas), así que
    música/efectos no disparan el corte; sí el diálogo de una peli/serie/video.
  - El hilo solo actualiza un flag (``_hay_voz`` + marca de tiempo); la consulta
    ``hay_voz_ahora()`` es instantánea y no bloquea el pipeline de habla.

Todo es **opcional y degradable**: si falta ``pyaudiowpatch``, no hay tarjeta de
loopback o algo falla, el VAD queda ``disponible=False`` y el MediaController
cae a la heurística por config (``MEDIA_ASSUME_DIALOGO``) sin romperse.
Apagado por defecto: se activa con ``MEDIA_VAD_ENABLED`` en el .env.
"""

import threading
import time
from typing import Any, Optional

import numpy as np
from decouple import config as environ  # type: ignore

# --- Configuración (.env) ---------------------------------------------------

# Apagado por defecto: además de MEDIA_CONTROL_ENABLED hay que activar esto.
ENABLED = environ("MEDIA_VAD_ENABLED", default=False, cast=bool)

# Umbral de Silero (0.0-1.0): probabilidad mínima para considerar que hay voz.
# Más alto = menos falsos positivos (corta menos), más bajo = más sensible.
VAD_THRESHOLD = float(environ("MEDIA_VAD_THRESHOLD", default=0.5))

# Cuánto se "sostiene" la decisión de hay-voz tras el último tramo con voz, para
# que las micro-pausas entre palabras no hagan parpadear el flag.
HOLD_SECONDS = float(environ("MEDIA_VAD_HOLD_SECONDS", default=1.5))

# Silero VAD solo acepta 16 kHz (u 8 kHz); el loopback suele venir a 44.1/48 kHz,
# así que remuestreamos a este destino.
_TARGET_RATE = 16000

# Tamaño de la ventana de audio analizada en cada vuelta (segundos).
_WINDOW_SECONDS = 1.0


class LoopbackVAD:
    """Detecta voz en el audio del sistema en un hilo aparte; flag consultable."""

    def __init__(self) -> None:
        self.disponible = False
        self._hay_voz = False
        self._ultima_voz = 0.0  # time.monotonic() del último tramo con voz
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._vad_options: Any = None

    # --- Ciclo de vida ------------------------------------------------------

    def start(self) -> bool:
        """Arranca el hilo de captura+VAD. Devuelve True si quedó activo."""
        if not ENABLED:
            return False
        # Imports perezosos: ambas deps son opcionales/solo-Windows. Si falta
        # alguna, el VAD se desactiva sin romper el resto del bot.
        try:
            # pylint: disable=import-outside-toplevel,unused-import
            import pyaudiowpatch  # type: ignore # noqa: F401
            from faster_whisper.vad import VadOptions, get_vad_model
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: VAD de loopback no disponible ({e}). ¿Falta pyaudiowpatch?")
            return False
        self._vad_options = VadOptions(threshold=VAD_THRESHOLD)
        # Precargamos el modelo Silero (cacheado) acá para que el primer corte no
        # pague la carga y para detectar temprano si algo falla.
        try:
            get_vad_model()
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: No se pudo cargar el modelo Silero VAD: {e}")
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="loopback-vad", daemon=True
        )
        self._thread.start()
        self.disponible = True
        print("DEBUG: VAD de loopback iniciado (escuchando el audio del sistema).")
        return True

    def stop(self) -> None:
        """Detiene el hilo de captura (best-effort)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.disponible = False

    # --- Consulta (instantánea, no bloquea) ---------------------------------

    def hay_voz_ahora(self) -> bool:
        """¿Sonaba voz en el último ~segundo? Con sostén anti-parpadeo."""
        if not self.disponible:
            return False
        if self._hay_voz and (time.monotonic() - self._ultima_voz) > HOLD_SECONDS:
            self._hay_voz = False
        return self._hay_voz

    # --- Hilo de captura ----------------------------------------------------

    def _run(self) -> None:
        # pylint: disable=import-outside-toplevel
        import pyaudiowpatch as pyaudio  # type: ignore
        from faster_whisper.vad import get_speech_timestamps

        audio = None
        stream = None
        try:
            audio = pyaudio.PyAudio()
            dev = self._find_loopback_device(audio, pyaudio)
            if dev is None:
                print("DEBUG: No se encontró dispositivo de loopback WASAPI; VAD off.")
                self.disponible = False
                return
            src_rate = int(dev["defaultSampleRate"])
            channels = max(1, int(dev["maxInputChannels"]))
            chunk = int(src_rate * _WINDOW_SECONDS)
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=src_rate,
                input=True,
                input_device_index=int(dev["index"]),
                frames_per_buffer=chunk,
            )
            while not self._stop.is_set():
                try:
                    raw = stream.read(chunk, exception_on_overflow=False)
                except Exception as e:  # noqa: BLE001
                    print(f"DEBUG: Error leyendo loopback: {e}")
                    time.sleep(0.2)
                    continue
                mono16k = self._to_mono_16k(raw, channels, src_rate)
                try:
                    tramos = get_speech_timestamps(
                        mono16k,
                        vad_options=self._vad_options,
                        sampling_rate=_TARGET_RATE,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"DEBUG: Error en Silero VAD (loopback): {e}")
                    continue
                if tramos:
                    self._hay_voz = True
                    self._ultima_voz = time.monotonic()
                # Si no hubo voz, hay_voz_ahora() lo apaga solo tras HOLD_SECONDS.
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: El VAD de loopback se detuvo: {e}")
            self.disponible = False
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
            if audio is not None:
                try:
                    audio.terminate()
                except Exception:  # noqa: BLE001
                    pass

    # --- Helpers ------------------------------------------------------------

    @staticmethod
    def _find_loopback_device(audio: Any, pyaudio: Any) -> Optional[dict]:
        """
        Encuentra el dispositivo de loopback del altavoz por defecto.

        En WASAPI, el loopback de un altavoz es un dispositivo de *entrada*
        espejo. Tomamos el output por defecto y buscamos su loopback asociado.
        """
        try:
            wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        except Exception:  # noqa: BLE001
            return None
        try:
            salida = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
        except Exception:  # noqa: BLE001
            salida = None
        # Si el output por defecto ya es un loopback, usarlo directo.
        if salida is not None and salida.get("isLoopbackDevice"):
            return salida
        nombre = salida["name"] if salida else ""
        try:
            for loop in audio.get_loopback_device_info_generator():
                # El loopback se llama igual que el altavoz (+ "[Loopback]").
                if not nombre or nombre in loop["name"]:
                    return loop
        except Exception:  # noqa: BLE001
            return None
        return None

    @staticmethod
    def _to_mono_16k(raw: bytes, channels: int, src_rate: int) -> np.ndarray:
        """int16 entrelazado → float32 mono normalizado [-1,1] remuestreado a 16k."""
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            # Recortar a un múltiplo de channels por si el buffer vino justo.
            usable = (len(data) // channels) * channels
            data = data[:usable].reshape(-1, channels).mean(axis=1)
        if src_rate != _TARGET_RATE and len(data) > 1:
            n_out = int(round(len(data) * _TARGET_RATE / src_rate))
            if n_out > 1:
                x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
                x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
                data = np.interp(x_new, x_old, data).astype(np.float32)
        return data.astype(np.float32)
