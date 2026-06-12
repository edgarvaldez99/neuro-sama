import time

import edge_tts

from .generate_audio import play_audio
from .utils import clean_text_for_tts


class EdgeTTS:
    def __init__(self, voice="es-MX-DaliaNeural", pitch="+15Hz", rate="+5%"):
        """
        pitch: Ajusta el tono. Ej: "+15Hz" para más agudo, "-10Hz" para más grave.
        rate: Ajusta la velocidad. Ej: "+5%" para un poco más rápido (juvenil).
        """
        self.voice = voice
        self.pitch = pitch
        self.rate = rate

    async def generate_speech(self, text: str, output_filename=None):
        if output_filename is None:
            timestamp = int(time.time() * 1000)
            output_filename = f"audio_{timestamp}.mp3"

        print(f"DEBUG: Generando audio con Edge TTS para: {text[:30]}...")
        # Limpiar texto para el TTS (quitar emojis y símbolos)
        text_to_speak = clean_text_for_tts(text)

        # Configuramos los parámetros de personalización
        communicate = edge_tts.Communicate(
            text_to_speak,
            self.voice,
            pitch=self.pitch,
            rate=self.rate,
        )

        try:
            await communicate.save(output_filename)
            print(f"DEBUG: Audio generado en {output_filename}. Reproduciendo...")
            await play_audio(output_filename)
        except Exception as e:
            print(f"DEBUG: Error al generar audio con Edge TTS: {e}")


# Instancia global
_edge_instance = None


# user_question se mantiene por simetría con la interfaz de texttospeech_piper;
# Edge TTS solo sintetiza la respuesta del bot.
async def get_speech_by_text(
    user_question: str,  # pylint: disable=unused-argument
    bot_response: str,
    audio_filename=None,
):
    global _edge_instance
    if _edge_instance is None:
        # Tono más agudo (+15Hz) y un poco más rápido (+5%) para sonar más juvenil
        _edge_instance = EdgeTTS(pitch="+15Hz", rate="+5%")

    # Solo sintetizamos la respuesta del bot
    await _edge_instance.generate_speech(bot_response, audio_filename)
