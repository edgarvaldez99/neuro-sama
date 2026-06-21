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
from typing import Any, List, Optional, Tuple

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
# msedge.exe, firefox.exe, vlc.exe). Solo aplica si la técnica es "ducking".
DUCK_PROCESS = str(environ("MEDIA_DUCK_PROCESS", default="chrome.exe"))

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
        # Volúmenes guardados durante el ducking: [(sesion_volumen, valor_previo)]
        self._saved: List[Tuple[Any, float]] = []
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
            return
        if self.tecnica == "pausa":
            self._tecla_play_pause()
            self._pausado = True
        elif self.tecnica == "ducking":
            if self._duck():
                pass  # _saved ya quedó cargado

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

    # --- Técnica: ducking (pycaw, por aplicación) --------------------------

    def _duck(self) -> bool:
        """Baja el volumen de la sesión de audio de DUCK_PROCESS. Guarda el previo."""
        try:
            # Import lazy a propósito: pycaw es opcional y solo-Windows; si no
            # está instalado, el ducking se desactiva sin romper el resto.
            # pylint: disable=import-outside-toplevel
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume  # type: ignore

            self._saved = []
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc and proc.name().lower() == DUCK_PROCESS.lower():
                    # _ctl es la forma idiomática de pycaw de obtener la interfaz.
                    vol = (
                        session._ctl.QueryInterface(  # pylint: disable=protected-access
                            ISimpleAudioVolume
                        )
                    )
                    prev = vol.GetMasterVolume()
                    self._saved.append((vol, prev))
                    vol.SetMasterVolume(DUCK_LEVEL, None)
            return bool(self._saved)
        except Exception as e:
            print(f"DEBUG: Ducking no disponible ({e}). ¿Instalaste pycaw?")
            self._saved = []
            return False

    def _restore(self) -> None:
        """Restaura los volúmenes guardados por el ducking."""
        try:
            for vol, prev in self._saved:
                vol.SetMasterVolume(prev, None)
        except Exception as e:
            print(f"DEBUG: No se pudo restaurar el volumen: {e}")
        self._saved = []
