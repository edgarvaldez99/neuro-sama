import os

os.environ["BASE_DIR_PATH"] = os.getcwd()


if __name__ == "__main__":
    # Pipeline local: Twitch + Micrófono -> Ollama -> TTS -> VTS -> VLC
    import asyncio

    from src.generate_audio import clean_audio_folder
    from src.stt_local import LocalSTT
    from src.twitchbot import Bot

    # Limpiar audios antiguos al iniciar
    clean_audio_folder()

    async def main():
        bot = Bot()
        stt = LocalSTT(bot)

        # Corremos el bot de Twitch y el escuchador de micrófono en el mismo
        # event loop. Usamos gather (no create_task suelto) para que, si alguno
        # falla, la excepción se propague y la veas, en vez de tragarse en
        # silencio y dejar al bot mudo sin explicación.
        await asyncio.gather(
            bot.start(),
            stt.listen_loop(),
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot apagado por el usuario.")
