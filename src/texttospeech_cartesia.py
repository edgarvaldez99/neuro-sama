from io import BytesIO

from cartesia import Cartesia  # type: ignore

from .credentials import CARTESIA_API_KEY
from .generate_audio import play_audio

client = Cartesia(api_key=CARTESIA_API_KEY)
# You can check out our voices at https://play.cartesia.ai/
voice_name = "Young Spanish-speaking Woman"
voice_id = "db832ebd-3cb6-42e7-9d47-912b425adbaa"
voice = client.voices.get(id=voice_id)


# You can check out our models at https://docs.cartesia.ai/getting-started/available-models  # noqa: E501 B950
model_id = "sonic-multilingual"
language = "es"  # Language code

# You can find the supported `output_format`s at https://docs.cartesia.ai/api-reference/endpoints/stream-speech-server-sent-events  # noqa: E501 B950
output_format = {
    "container": "wav",
    "encoding": "pcm_s16le",
    "sample_rate": 44100,
}


async def get_speech_by_text(
    user_question: str, bot_response: str, audio_filename="audio.mp3"
):
    text_to_transform_to_audio = user_question + "? " + bot_response

    # Acumular los bytes en un BytesIO objeto
    audio_buffer = BytesIO()

    # Generate and stream audio
    for output in client.tts.sse(
        model_id=model_id,
        transcript=text_to_transform_to_audio,
        voice_embedding=voice["embedding"],
        stream=True,
        output_format=output_format,
        language=language,
    ):
        audio_buffer.write(output["audio"])

    audio_content = audio_buffer.getvalue()

    await play_audio(audio_filename, audio_content)
