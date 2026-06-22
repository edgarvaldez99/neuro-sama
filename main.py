import os

os.environ["BASE_DIR_PATH"] = os.getcwd()


if __name__ == "__main__":
    # Pipeline local: Twitch + Micrófono + Visión -> Ollama -> TTS -> VTS -> VLC
    import asyncio

    from decouple import config as environ

    from src.generate_audio import clean_audio_folder
    from src.stt_local import LocalSTT
    from src.twitchbot import DIRECTOR_ENABLED, Bot

    # Limpiar audios antiguos al iniciar
    clean_audio_folder()

    # ¿Mai-chan "ve" la pantalla? Apagado por defecto: solo se enciende si hay un
    # VLM disponible y se configuró en el .env (ver .env.example, sección Visión).
    VISION_ENABLED = environ("VISION_ENABLED", default=False, cast=bool)

    # Un único event loop para TODA la sesión. Lo creamos y fijamos como loop
    # actual ANTES de instanciar el Bot, porque twitchio captura
    # asyncio.get_event_loop() dentro de su __init__: si el Bot naciera bajo un
    # loop distinto del que luego lo corre, twitchio aborta con
    # "Attempted to start a Bot instance on a different loop...". Por eso no
    # usamos asyncio.run() (que crearía un loop nuevo), sino run_until_complete
    # sobre este mismo loop, también para el resumen final del stream.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Bot y STT fuera de main() para poder guardar el resumen del stream al cerrar.
    bot = Bot()
    stt = LocalSTT(bot)

    async def main():
        # Productores que alimentan la MISMA cola del bot: chat, micrófono y
        # (opcional) visión y director. Usamos gather (no create_task suelto) para
        # que, si alguno falla, la excepción se propague y la veas, en vez de
        # tragarse en silencio y dejar al bot mudo sin explicación.
        productores = [bot.start(), stt.listen_loop()]

        if VISION_ENABLED:
            # Import perezoso a propósito: screen_vision arrastra deps de visión
            # que solo queremos cargar si la visión está activa.
            # pylint: disable=import-outside-toplevel
            from src.screen_vision import ScreenVision

            productores.append(ScreenVision(bot).watch_loop())

        if DIRECTOR_ENABLED:
            productores.append(bot.director_loop())

        await asyncio.gather(*productores)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Bot apagándose por el usuario...")
    finally:
        # Detener el hilo del VAD de loopback (si estaba activo) antes de salir.
        try:
            bot.media.close()
        except Exception as e:
            print(f"DEBUG: No se pudo cerrar el MediaController: {e}")
        # Al cerrar, generar y persistir el resumen del stream (memoria episódica).
        # Best-effort: si Ollama no responde, no bloquea el apagado. Reutilizamos
        # el mismo loop (no asyncio.run) y recién después lo cerramos.
        try:
            loop.run_until_complete(bot.save_stream_summary())
        except Exception as e:
            print(f"DEBUG: No se pudo guardar el resumen del stream: {e}")
        finally:
            loop.close()
