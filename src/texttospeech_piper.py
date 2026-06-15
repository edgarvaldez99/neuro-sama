import os
import time
import wave

from piper import PiperVoice

from .generate_audio import play_audio
from .utils import clean_text_for_tts


class PiperTTS:
    def __init__(self):
        # Rutas a los modelos locales
        model_dir = os.path.join(os.getcwd(), "models", "tts")
        self.model_path = os.path.join(model_dir, "es_MX-ald-medium.onnx")
        self.config_path = os.path.join(model_dir, "es_MX-ald-medium.onnx.json")

        # Piper necesita AMBOS archivos: el modelo .onnx y su config .onnx.json
        for path, nombre in (
            (self.model_path, "modelo (.onnx)"),
            (self.config_path, "config (.onnx.json)"),
        ):
            if not os.path.exists(path):
                print(f"AVISO: No se encuentra el {nombre} de voz en {path}")
                print("Descarga ambos archivos (.onnx y .onnx.json) a esa carpeta.")
                return

        # Cargar la voz de Piper
        self.voice = PiperVoice.load(self.model_path, config_path=self.config_path)

    async def generate_speech(self, text: str, output_filename=None):
        if not hasattr(self, "voice"):
            print("DEBUG: Piper no cargado. Verifica los modelos.")
            return

        if output_filename is None:
            timestamp = int(time.time() * 1000)
            dir_path = os.environ.get("BASE_DIR_PATH", os.getcwd())
            output_filename = os.path.join(dir_path, "audios", f"audio_{timestamp}.wav")

        print(f"DEBUG: Generando audio para: {text[:30]}...")
        # Limpiar texto para el TTS (quitar emojis y símbolos)
        text_to_speak = clean_text_for_tts(text)

        # Ajustar velocidad (1.0 es normal, >1.0 es más lento)
        self.voice.config.length_scale = 1.1

        # wave.open(..., "wb") devuelve Wave_write; pylint infiere Wave_read y marca
        # los setters como inexistentes (falso positivo).
        # pylint: disable=no-member
        with wave.open(output_filename, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.voice.config.sample_rate)

            for chunk in self.voice.synthesize(text_to_speak):
                wav_file.writeframes(chunk.audio_int16_bytes)

        print(f"DEBUG: Audio generado en {output_filename}. Enviando a reproducir...")
        await play_audio(output_filename)


# Instancia global
_piper_instance = None


# user_question se mantiene por simetría con la interfaz de los otros TTS;
# Piper solo sintetiza la respuesta del bot.
async def get_speech_by_text(
    user_question: str,  # pylint: disable=unused-argument
    bot_response: str,
    audio_filename=None,
):
    global _piper_instance
    if _piper_instance is None:
        _piper_instance = PiperTTS()

    # Solo sintetizamos la respuesta del bot para mayor naturalidad
    await _piper_instance.generate_speech(bot_response, audio_filename)
