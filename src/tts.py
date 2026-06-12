"""
Selector de motor de Text-To-Speech.

El motor se elige con la variable de entorno ``TTS_ENGINE`` (en .env):
  - ``edge``  -> Edge TTS (online, voces de Microsoft). Por defecto.
  - ``piper`` -> Piper TTS (100% offline, requiere los modelos en models/tts/).

Para agregar un motor nuevo: creá su módulo con una función
``get_speech_by_text(user_question, bot_response, audio_filename=None)`` y
registralo en ``_ENGINES`` abajo.
"""

from typing import Awaitable, Callable, Optional

from decouple import config as environ  # type: ignore

from .texttospeech_edge import get_speech_by_text as _edge_speak
from .texttospeech_piper import get_speech_by_text as _piper_speak

SpeakFn = Callable[[str, str, Optional[str]], Awaitable[None]]

# Registro de motores disponibles. La clave es el valor de TTS_ENGINE en .env.
_ENGINES: dict[str, SpeakFn] = {
    "edge": _edge_speak,
    "piper": _piper_speak,
}

TTS_ENGINE = str(environ("TTS_ENGINE", default="edge")).lower()


async def get_speech_by_text(
    user_question: str,
    bot_response: str,
    audio_filename: Optional[str] = None,
) -> None:
    """Sintetiza la respuesta con el motor configurado en TTS_ENGINE."""
    speak = _ENGINES.get(TTS_ENGINE)
    if speak is None:
        disponibles = ", ".join(_ENGINES)
        print(
            f"DEBUG: TTS_ENGINE='{TTS_ENGINE}' no es válido. "
            f"Usando 'edge'. Opciones: {disponibles}."
        )
        speak = _edge_speak
    await speak(user_question, bot_response, audio_filename)
