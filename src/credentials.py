from decouple import config as environ  # type: ignore

# Tu Twitch OAuth Token
TWITCH_TOKEN = str(environ("TWITCH_TOKEN", ""))
# El nombre de tu canal de Twitch
TWITCH_CHANNEL = str(environ("TWITCH_CHANNEL", ""))
# El nombre del bot, ej: Neuro-sama
BOT_NAME = str(environ("BOT_NAME", ""))
