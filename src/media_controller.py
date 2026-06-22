"""
MediaController — que el audio del video no pise la voz de Mai-chan.

Generaliza el flag ``is_speaking`` (que hoy solo silencia el micro) a un
controlador que, cuando Mai-chan va a hablar, además **pausa** o **baja el
volumen** del contenido que se está reproduciendo, y lo restaura al terminar.
Ver docs/plan_vision_general.md §6.

Alcance: **solo Nivel 1** (simular inputs concretos del sistema). NADA de agente
autónomo que controle la PC.

Dos técnicas, elegidas por la *fuente*:
  - **Pausa** = tecla multimedia global Play/Pause (universal: navegador, VLC,
    Netflix...). Un único evento, vía la API de Windows. Es *toggle*, así que el
    controlador recuerda si pausó para no despausar de más.
  - **Ducking** = bajar el volumen SOLO de la app del video (no global, que
    bajaría también la voz de Mai-chan). Se hace por aplicación con ``pycaw``
    (Windows Core Audio).

Condición de corte (no es "siempre que habla"): cortar solo si Mai-chan va a
hablar Y el video tiene voz en ese momento. Esa señal la da ``LoopbackVAD``
(Silero VAD sobre el audio del sistema, ver ``src/loopback_vad.py``) cuando está
activo (``MEDIA_VAD_ENABLED``); si no, ``_hay_dialogo`` cae a la heurística por
config (``MEDIA_ASSUME_DIALOGO``).

Todo se controla desde .env y está **apagado por defecto** (``MEDIA_CONTROL_ENABLED``):
quien no lo configure no ve ningún cambio de comportamiento.
"""

import ctypes
import warnings
from typing import Any, Callable, List, Optional, Tuple

from decouple import config as environ  # type: ignore

from .loopback_vad import LoopbackVAD

# --- Configuración (.env) ---------------------------------------------------

# Apagado por defecto: hay que activarlo explícitamente.
ENABLED = environ("MEDIA_CONTROL_ENABLED", default=False, cast=bool)

# Fuente del contenido → define la técnica preferida (ver matriz en el plan §6.3):
#   gameplay          -> ninguno (narra en vivo, no corta)
#   navegador         -> ducking (baja el volumen del navegador)
#   reproductor_local -> pausa   (tecla multimedia, ideal para pelis/series)
SOURCE = str(environ("MEDIA_SOURCE", default="navegador"))

# Nombre del proceso cuyo volumen se baja al hacer ducking (ej: chrome.exe,
# msedge.exe, firefox.exe, vlc.exe). Solo se usa como FALLBACK por aplicación
# cuando no hay un dispositivo objetivo (ver DUCK_DEVICE).
DUCK_PROCESS = str(environ("MEDIA_DUCK_PROCESS", default="chrome.exe"))

# Ducking por DISPOSITIVO (recomendado) en vez de por app: baja el volumen del
# dispositivo de salida donde suena el video, no de un proceso. Imprescindible
# cuando el video sale por un dispositivo distinto al del bot (ej: video en
# "Altavoces", voz de Mai-chan por un cable virtual): el ducking por app no ve
# las sesiones de otros dispositivos.
#   - Vacío (por defecto) + VAD activo  => AUTO: duckea el dispositivo que el VAD
#     detecta con el video.
#   - Con un nombre (subcadena, ej "Altavoces") => duckea ESE dispositivo.
#   - Vacío + sin VAD => cae al ducking por proceso (DUCK_PROCESS).
DUCK_DEVICE = str(environ("MEDIA_DUCK_DEVICE", default=""))

# A cuánto se baja el volumen del video al hablar (0.0-1.0). 0.2 = 20%.
DUCK_LEVEL = float(environ("MEDIA_DUCK_LEVEL", default=0.2))

# Heurística temporal mientras no haya VAD de loopback: asumimos que el video
# tiene diálogo (así pausa/duckea). Poné False si el contenido es mayormente
# música/acción y preferís que hable encima sin tocar nada.
ASSUME_DIALOGO = environ("MEDIA_ASSUME_DIALOGO", default=True, cast=bool)

# Técnica preferida por fuente.
_TECNICA_POR_FUENTE = {
    "gameplay": "ninguno",
    "navegador": "ducking",
    "reproductor_local": "pausa",
}

# Códigos de la API de Windows para la tecla multimedia Play/Pause.
_VK_MEDIA_PLAY_PAUSE = 0xB3
_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002


class MediaController:
    """Pausa/duckea el contenido mientras Mai-chan habla y lo restaura al terminar."""

    def __init__(self):
        self.enabled = ENABLED
        self.source = SOURCE
        self.tecnica = _TECNICA_POR_FUENTE.get(self.source, "ninguno")
        self._pausado = False
        # Restauradores del ducking: [(set_volumen, valor_previo)]. Guardamos un
        # callable por cada volumen tocado (app o dispositivo) para restaurarlo
        # sin importar de qué tipo de interfaz vino.
        self._saved: List[Tuple[Callable[[float], None], float]] = []
        # VAD de loopback (¿el video tiene voz ahora?). Solo tiene sentido si el
        # control está activo y la fuente realmente corta (no "gameplay"); si no
        # arranca (falta dep/dispositivo), queda None y se cae a ASSUME_DIALOGO.
        self._vad: Optional[LoopbackVAD] = None
        if self.enabled and self.tecnica != "ninguno":
            vad = LoopbackVAD()
            if vad.start():
                self._vad = vad
        if self.enabled:
            print(
                f"DEBUG: MediaController activo. fuente={self.source} "
                f"tecnica={self.tecnica} vad={'on' if self._vad else 'off'}"
            )

    # --- Enganches del ciclo de habla --------------------------------------

    def antes_de_hablar(self) -> None:
        """Llamar JUSTO antes de reproducir el audio de Mai-chan."""
        if not self.enabled or self.tecnica == "ninguno":
            return
        # Video sin voz (música/acción/escena muda) → hablar encima, no tocar nada.
        if not self._hay_dialogo():
            print("DEBUG: Media: no corto (el video no tiene diálogo ahora).")
            return
        if self.tecnica == "pausa":
            self._tecla_play_pause()
            self._pausado = True
            print("DEBUG: Media: video PAUSADO mientras habla Mai-chan.")
        elif self.tecnica == "ducking":
            if self._duck():
                print(
                    f"DEBUG: Media: video bajado a {int(DUCK_LEVEL * 100)}% "
                    "mientras habla Mai-chan."
                )

    def al_terminar(self) -> None:
        """Llamar JUSTO después de que termina el audio de Mai-chan."""
        if not self.enabled:
            return
        if self._pausado:
            self._tecla_play_pause()  # toggle: vuelve a reproducir
            self._pausado = False
        if self._saved:
            self._restore()

    # --- Señal de diálogo ---------------------------------------------------

    def _hay_dialogo(self) -> bool:
        """
        ¿El video tiene voz en este momento?

        Si el VAD de loopback está activo, lo decide en vivo (Silero VAD sobre el
        audio del sistema). Si no, cae a la heurística por config.
        """
        if self._vad is not None and self._vad.disponible:
            return self._vad.hay_voz_ahora()
        return ASSUME_DIALOGO

    def close(self) -> None:
        """Libera recursos (detiene el hilo del VAD). Llamar al apagar el bot."""
        if self._vad is not None:
            self._vad.stop()
            self._vad = None

    # --- Técnica: pausa (tecla multimedia) ---------------------------------

    def _tecla_play_pause(self) -> None:
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            user32.keybd_event(_VK_MEDIA_PLAY_PAUSE, 0, _KEYEVENTF_EXTENDEDKEY, 0)
            user32.keybd_event(
                _VK_MEDIA_PLAY_PAUSE,
                0,
                _KEYEVENTF_EXTENDEDKEY | _KEYEVENTF_KEYUP,
                0,
            )
        except Exception as e:
            print(f"DEBUG: No se pudo enviar la tecla multimedia: {e}")

    # --- Técnica: ducking (pycaw) ------------------------------------------

    def _duck(self) -> bool:
        """Baja el volumen del video y guarda lo previo para restaurar.

        Prefiere bajar el DISPOSITIVO donde suena el video (lo da el VAD o
        DUCK_DEVICE); si no hay objetivo de dispositivo, cae al ducking por
        aplicación (DUCK_PROCESS) en el dispositivo por defecto.
        """
        self._saved = []
        objetivo = self._target_device()
        if objetivo and self._duck_device(objetivo):
            return True
        return self._duck_process()

    def _target_device(self) -> str:
        """Subcadena del dispositivo a duckear: el de .env o, si está vacío, el
        que el VAD detecta con el video (sin el sufijo ' [Loopback]')."""
        if DUCK_DEVICE:
            return DUCK_DEVICE
        if self._vad is not None and self._vad.dispositivo_activo:
            return self._vad.dispositivo_activo.replace(" [Loopback]", "")
        return ""

    def _duck_device(self, name_substr: str) -> bool:
        """Baja el volumen del DISPOSITIVO de salida cuyo nombre contiene la
        subcadena. No toca la voz de Mai-chan si ésta sale por otro dispositivo."""
        vol = self._device_endpoint(name_substr)
        if vol is None:
            print(f"DEBUG: Ducking: no encontré el dispositivo '{name_substr}'.")
            return False
        try:
            prev = vol.GetMasterVolumeLevelScalar()
            vol.SetMasterVolumeLevelScalar(DUCK_LEVEL, None)
            self._saved.append(
                (lambda v: vol.SetMasterVolumeLevelScalar(v, None), prev)
            )
            print(f"DEBUG: Ducking por dispositivo: '{name_substr}'.")
            return True
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: Ducking de dispositivo falló: {e}")
            return False

    @staticmethod
    def _device_endpoint(name_substr: str) -> Any:
        """Devuelve el IAudioEndpointVolume del dispositivo de salida ACTIVO cuyo
        FriendlyName contiene la subcadena, o None."""
        # pylint: disable=import-outside-toplevel,import-error,protected-access
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL  # type: ignore
            from pycaw.api.endpointvolume import IAudioEndpointVolume  # type: ignore
            from pycaw.utils import AudioUtilities  # type: ignore
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: pycaw no disponible para ducking de dispositivo: {e}")
            return None
        objetivo = name_substr.lower()
        with warnings.catch_warnings():
            # pycaw emite UserWarning al leer propiedades de dispositivos
            # deshabilitados/ausentes durante el enumerado; lo silenciamos.
            warnings.simplefilter("ignore")
            try:
                dispositivos = AudioUtilities.GetAllDevices()
            except Exception:  # noqa: BLE001
                return None
        for dev in dispositivos:
            nombre = dev.FriendlyName or ""
            if objetivo not in nombre.lower():
                continue
            if getattr(dev.state, "name", "") != "Active":
                continue
            try:
                iface = dev._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                return cast(iface, POINTER(IAudioEndpointVolume))
            except Exception:  # noqa: BLE001
                continue
        return None

    def _duck_process(self) -> bool:
        """Fallback: baja el volumen de la sesión de DUCK_PROCESS (por app)."""
        try:
            # Import lazy a propósito: pycaw es opcional y solo-Windows; si no
            # está instalado, el ducking se desactiva sin romper el resto.
            # pylint: disable=import-outside-toplevel,import-error,protected-access
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume  # type: ignore
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: Ducking no disponible ({e}). ¿Instalaste pycaw?")
            return False
        try:
            objetivo = DUCK_PROCESS.lower()
            activos: List[str] = []  # nombres de apps con audio, para diagnóstico
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc:
                    activos.append(proc.name())
                if proc and proc.name().lower() == objetivo:
                    # pylint: disable-next=protected-access
                    vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                    prev = vol.GetMasterVolume()
                    vol.SetMasterVolume(DUCK_LEVEL, None)

                    def _set(v: float, _vol: Any = vol) -> None:
                        _vol.SetMasterVolume(v, None)

                    self._saved.append((_set, prev))
            if not self._saved:
                disponibles = sorted(set(activos)) or ["(ninguna)"]
                print(
                    f"DEBUG: Ducking: no hay sesión de audio para '{DUCK_PROCESS}' "
                    f"(en el dispositivo por defecto). Apps con audio: "
                    f"{', '.join(disponibles)}. Probá MEDIA_DUCK_DEVICE."
                )
            return bool(self._saved)
        except Exception as e:  # noqa: BLE001
            print(f"DEBUG: Ducking por proceso falló: {e}")
            return False

    def _restore(self) -> None:
        """Restaura todos los volúmenes que tocó el ducking (app y/o dispositivo)."""
        for set_volumen, prev in self._saved:
            try:
                set_volumen(prev)
            except Exception as e:  # noqa: BLE001
                print(f"DEBUG: No se pudo restaurar el volumen: {e}")
        self._saved = []
