from decouple import config as environ  # type: ignore

# You're Twitch Token
TWITCH_TOKEN = str(environ("TWITCH_TOKEN", ""))
# Your TWITCH Channel Name
TWITCH_CHANNEL = str(environ("TWITCH_CHANNEL", ""))
# Your OpenAI API Key
OPENAI_API_KEY = str(environ("OPENAI_API_KEY", ""))
# Your Google Cloud JSON Path
GOOGLE_JSON_PATH = str(environ("GOOGLE_JSON_PATH", ""))
# Your BOT_NAME, example = Neuro-sama
BOT_NAME = str(environ("BOT_NAME", ""))
# Your ELEVENLABS_APIKEY, example = AAAAA
ELEVENLABS_APIKEY = str(environ("ELEVENLABS_APIKEY", ""))
# Your ELEVENLABS_VOICEID, example = BBBBB
ELEVENLABS_VOICEID = str(environ("ELEVENLABS_VOICEID", ""))
# Your WEBSOCKET_URL, example = ws://localhost:7580
WEBSOCKET_URL = str(environ("WEBSOCKET_URL", ""))
# Your CARTESIA_API_KEY, example = CCCC
CARTESIA_API_KEY = str(environ("CARTESIA_API_KEY", ""))
# Your HUGGING_FACE_MODEL, example = XLM-RoBERTa-base
HUGGING_FACE_MODEL = str(environ("HUGGING_FACE_MODEL", ""))
