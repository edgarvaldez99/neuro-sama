import os
import wave

import numpy as np
import sherpa_onnx  # type: ignore

from .generate_audio import play_audio


class SherpaTTS:
    def __init__(self):
        # Rutas a los modelos locales
        model_dir = os.path.join(os.getcwd(), "models", "tts")
        model_path = os.path.join(model_dir, "es_LA-renee-medium.onnx")

        if not os.path.exists(model_path):
            print(f"ERROR: No se encuentra el modelo de voz en {model_path}")
            return

        # Configuración del motor Sherpa-ONNX
        tts_config = sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineVitsModelConfig(
                model=model_path,
                lexicon="",
                tokens=os.path.join(
                    model_dir, "tokens.txt"
                ),  # Algunos modelos requieren esto
                data_dir="",
                noise_scale=0.667,
                noise_scale_w=0.8,
                length_scale=1.0,
            ),
            num_threads=4,
            debug=False,
            provider="cpu",  # Cambiar a "cuda" si tienes GPU
        )

        self.tts = sherpa_onnx.OfflineTts(tts_config)

    async def generate_speech(self, text: str, output_filename="audio.wav"):
        if not hasattr(self, "tts"):
            print("TTS no inicializado.")
            return

        # Generar audio
        audio = self.tts.generate(text)

        # Guardar a un archivo temporal para usar con tu sistema de play_audio actual
        with wave.open(output_filename, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)  # 16-bit
            f.setframerate(audio.sample_rate)
            # Convertir float32 a int16
            samples = (audio.samples * 32767).astype(np.int16)
            f.writeframes(samples.tobytes())

        # Usar tu función actual para reproducir
        with open(output_filename, "rb") as f:
            audio_content = f.read()
            await play_audio(output_filename, audio_content)


# Instancia global para ser usada por el bot
_tts_instance = None


async def get_speech_by_text(
    user_question: str, bot_response: str, audio_filename="audio.wav"
):
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = SherpaTTS()

    full_text = f"{bot_response}"
    await _tts_instance.generate_speech(full_text, audio_filename)
