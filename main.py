import os

os.environ["BASE_DIR_PATH"] = os.getcwd()


if __name__ == "__main__":
    # Pipeline local: Twitch -> Ollama -> TTS (Edge/Piper) -> VTube Studio -> VLC
    from src.twitchbot import Bot

    bot = Bot()
    bot.run()
