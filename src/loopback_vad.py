"""
LoopbackVAD — ¿el audio del sistema (lo que SUENA: video, música, peli) tiene
VOZ en este momento?

Es la señal que le faltaba al MediaController para decidir *en vivo* si cortar:
solo tiene sentido pausar/duckear el contenido si éste tiene diálogo justo
cuando Mai-chan va a hablar. Si suena música, acción o una escena muda, habla
encima sin tocar nada. Ver docs/plan_vision_general.md §6.1 y §6.3.

Cómo funciona:
  - Un hilo en segundo plano captura el **loopback WASAPI** (lo que sale por un
    dispositivo de salida) con ``pyaudiowpatch`` —el ``pyaudio`` normal NO hace
    loopback en Windows— y lo pasa por **Silero VAD**, el mismo modelo que ya
    trae ``faster-whisper`` (cero dependencias nuevas para el VAD en sí).
  - **Elige solo el canal correcto**: NO escucha el dispositivo de salida por
    defecto a ciegas (que suele ser el cable virtual por donde sale la voz de la
    propia Mai-chan). En su lugar rastrea todos los loopbacks, descarta el del
    bot y se engancha al que realmente tiene audio (el video). Si ese canal se
    queda en silencio un rato, vuelve a rastrear por si el audio se mudó a otro.
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
from typing import Any, List, Optional

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

# Override MANUAL (opcional): nombre (o parte) del dispositivo cuyo loopback
# escuchar. Por defecto vacío = autodetección (recomendado): el VAD busca solo el
# canal con audio que NO sea el del bot. Fijalo solo si querés forzar uno.
VAD_DEVICE = str(environ("MEDIA_VAD_DEVICE", default=""))

# Dispositivos a IGNORAR SIEMPRE en la autodetección, además del de salida del
# bot (subcadenas separadas por coma). Útil para excluir buses de Voicemeeter que
# mezclan la voz de Mai-chan (si no, el VAD la escucharía a ella). Vacío por def.
EXCLUDE_EXTRA = [
    s.strip().lower()
    for s in str(environ("MEDIA_VAD_EXCLUDE", default="")).split(",")
    if s.strip()
]

# Cada cuánto, cuando el dispositivo actual está en silencio, se rastrean TODOS
# los loopbacks para ver si el audio (el video) se mudó a otro lado (segundos).
RESCAN_SECONDS = float(environ("MEDIA_VAD_RESCAN_SECONDS", default=5.0))

# RMS mínimo (sobre audio normalizado [-1,1]) para considerar que un dispositivo
# "tiene audio". Por debajo de esto se lo trata como silencio.
ENERGY_SILENCE = float(environ("MEDIA_VAD_ENERGY", default=0.003))

# Cuánto audio se lee de cada dispositivo al rastrear su energía (segundos).
_PROBE_SECONDS = 0.25

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
        # Nombre del loopback que está escuchando ahora (el canal del video). Lo
        # lee el MediaController para saber QUÉ dispositivo duckear. None si aún
        # no enganchó ninguno.
        self.dispositivo_activo: Optional[str] = None

    # --- Ciclo de vida ------------------------------------------------------

    def start(self) -> bool:
        """Arranca el hilo de captura+VAD. Devuelve True si quedó activo."""
        if not ENABLED:
            return False
        # Imports perezosos: ambas deps son opcionales/solo-Windows. Si falta
        # alguna, el VAD se desactiva sin romper el resto del bot.
        try:
            # pylint: disable=import-outside-toplevel,unused-import,import-error
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
        print("DEBUG: VAD de loopback iniciado (autodetectando el canal del video).")
        return True

    def stop(self) -> None:
        """Detiene el hilo de captura (best-effort)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.disponible = False
        self.dispositivo_activo = None

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
        # pylint: disable=import-outside-toplevel,import-error
        import pyaudiowpatch as pyaudio  # type: ignore
        from faster_whisper.vad import get_speech_timestamps

        audio = None
        stream = None
        dev: Optional[dict] = None
        last_scan = 0.0
        last_signal = 0.0
        try:
            audio = pyaudio.PyAudio()
            # Nombre del dispositivo de salida del bot: nunca se escucha a sí misma.
            excluir = self._bot_device_name(audio, pyaudio)
            # Si no hay ningún loopback candidato (raro), degradar a fallback.
            if not VAD_DEVICE and not self._candidate_loopbacks(audio, excluir):
                print("DEBUG: VAD: no hay loopbacks aparte del bot; VAD off.")
                self.disponible = False
                return

            while not self._stop.is_set():
                now = time.monotonic()

                # (Re)elegir dispositivo: al arranque (dev None) o cuando el actual
                # lleva un rato en silencio (el video pudo haberse mudado de canal).
                necesita_scan = dev is None or (
                    now - last_signal > RESCAN_SECONDS
                    and now - last_scan > RESCAN_SECONDS
                )
                if necesita_scan:
                    last_scan = now
                    nuevo = self._pick_active_device(audio, pyaudio, excluir)
                    dev_idx = dev["index"] if dev is not None else None
                    if nuevo is not None and nuevo["index"] != dev_idx:
                        self._safe_close(stream)
                        stream = self._open_stream(audio, pyaudio, nuevo)
                        dev = nuevo if stream is not None else None
                        if stream is not None:
                            last_signal = now
                            self.dispositivo_activo = str(nuevo["name"])
                            print(f"DEBUG: VAD escuchando ahora: {nuevo['name']}")
                        else:
                            self.dispositivo_activo = None

                if stream is None or dev is None:
                    # Nada con audio todavía; esperar y reintentar el rastreo.
                    time.sleep(0.5)
                    continue

                rate = int(dev["defaultSampleRate"])
                channels = max(1, int(dev["maxInputChannels"]))
                chunk = int(rate * _WINDOW_SECONDS)
                # Lectura NO bloqueante: solo leemos cuando ya hay una ventana
                # entera disponible. Si el canal deja de entregar frames (se apagó
                # o es un bus virtual ocioso), no bloqueamos: el temporizador de
                # silencio dispara un re-rastreo y saltamos a otro canal.
                try:
                    if stream.get_read_available() < chunk:
                        time.sleep(0.05)
                        continue
                    raw = stream.read(chunk, exception_on_overflow=False)
                except Exception as e:  # noqa: BLE001
                    print(f"DEBUG: Error leyendo loopback: {e}")
                    time.sleep(0.2)
                    continue

                mono16k = self._to_mono_16k(raw, channels, rate)
                # Energía del tramo: marca si el dispositivo sigue sonando (decide
                # cuándo conviene re-rastrear) y evita correr Silero sobre silencio.
                if float(np.sqrt(np.mean(mono16k**2))) >= ENERGY_SILENCE:
                    last_signal = now
                else:
                    continue

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
            self._safe_close(stream)
            if audio is not None:
                try:
                    audio.terminate()
                except Exception:  # noqa: BLE001
                    pass

    # --- Selección de dispositivo ------------------------------------------

    @staticmethod
    def _safe_close(stream: Any) -> None:
        """Cierra un stream de pyaudio sin reventar si ya estaba cerrado/None."""
        if stream is None:
            return
        try:
            stream.stop_stream()
            stream.close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _open_stream(audio: Any, pyaudio: Any, dev: dict) -> Any:
        """Abre el stream de loopback de ``dev``. Devuelve None si falla."""
        rate = int(dev["defaultSampleRate"])
        try:
            return audio.open(
                format=pyaudio.paInt16,
                channels=max(1, int(dev["maxInputChannels"])),
                rate=rate,
                input=True,
                input_device_index=int(dev["index"]),
                frames_per_buffer=int(rate * _WINDOW_SECONDS),
            )
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: No pude abrir {dev['name']}: {e}")
            return None

    @staticmethod
    def _bot_device_name(audio: Any, pyaudio: Any) -> str:
        """Nombre del dispositivo de salida por defecto (por donde habla el bot)."""
        try:
            wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            salida = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
            return str(salida["name"])
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _candidate_loopbacks(audio: Any, excluir: str) -> List[dict]:
        """Loopbacks candidatos: todos menos el del bot y los excluidos a mano."""
        fuera = [excluir.lower()] if excluir else []
        fuera += EXCLUDE_EXTRA
        cands: List[dict] = []
        try:
            for loop in audio.get_loopback_device_info_generator():
                nombre = str(loop["name"]).lower()
                if any(f and f in nombre for f in fuera):
                    continue
                cands.append(loop)
        except Exception:  # noqa: BLE001
            return []
        return cands

    @staticmethod
    def _probe_energy(audio: Any, pyaudio: Any, dev: dict) -> float:
        """Mide el RMS del loopback de ``dev`` SIN bloquear (0.0 si silencio/falla).

        Clave: los buses virtuales ociosos (Voicemeeter) no entregan frames y un
        ``read`` bloqueante colgaría el hilo para siempre. Por eso solo leemos lo
        que ``get_read_available`` reporta como ya disponible, con un tope de espera.
        """
        rate = int(dev["defaultSampleRate"])
        channels = max(1, int(dev["maxInputChannels"]))
        n = int(rate * _PROBE_SECONDS)
        stream = None
        try:
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=int(dev["index"]),
                frames_per_buffer=n,
            )
            deadline = time.monotonic() + _PROBE_SECONDS + 0.3
            while time.monotonic() < deadline and stream.get_read_available() < n:
                time.sleep(0.02)
            avail = stream.get_read_available()
            if avail <= 0:
                return 0.0
            raw = stream.read(min(avail, n), exception_on_overflow=False)
            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if data.size == 0:
                return 0.0
            return float(np.sqrt(np.mean(data**2)))
        except Exception:  # noqa: BLE001
            return 0.0
        finally:
            LoopbackVAD._safe_close(stream)

    def _pick_active_device(
        self, audio: Any, pyaudio: Any, excluir: str
    ) -> Optional[dict]:
        """Elige el loopback (que no sea el del bot) con más audio ahora mismo.

        Si ``MEDIA_VAD_DEVICE`` está fijado a mano, devuelve ese (sin rastrear
        energía). Si no, mide el RMS de cada candidato y devuelve el más activo;
        ``None`` si ninguno supera el umbral de silencio.
        """
        if VAD_DEVICE:
            try:
                for loop in audio.get_loopback_device_info_generator():
                    if VAD_DEVICE.lower() in str(loop["name"]).lower():
                        return loop
            except Exception:  # noqa: BLE001
                return None
            return None
        mejor: Optional[dict] = None
        mejor_e = ENERGY_SILENCE
        for loop in self._candidate_loopbacks(audio, excluir):
            energia = self._probe_energy(audio, pyaudio, loop)
            if energia > mejor_e:
                mejor_e = energia
                mejor = loop
        return mejor

    # --- Helpers ------------------------------------------------------------

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
