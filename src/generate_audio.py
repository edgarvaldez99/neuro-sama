import asyncio
import os

from vlc import MediaPlayer, State  # type: ignore

# Historial para limpieza rotativa
_AUDIO_HISTORY_LIMIT = 3
_audio_history = []


async def _remove_with_retry(path: str, attempts: int = 15) -> None:
    """VLC libera el handle del archivo de forma diferida en Windows.
    Reintentamos el borrado un rato antes de rendirnos (evita WinError 32)."""
    for _ in range(attempts):
        try:
            if os.path.exists(path):
                os.remove(path)
                print(f"DEBUG: Archivo antiguo eliminado: {path}")
            return
        except PermissionError:
            await asyncio.sleep(0.2)
    print(f"DEBUG: No se pudo borrar el archivo tras varios intentos: {path}")


async def play_audio(audio_filename: str, audio_content: bytes | None = None):
    global _audio_history
    # Si se pasa contenido, lo escribimos (caso legacy o APIs externas)
    if audio_content is not None:
        with open(audio_filename, "wb") as out:
            out.write(audio_content)

    dir_path = os.environ.get("BASE_DIR_PATH", os.getcwd())
    # Usar rutas normales de Windows
    audio_file_path = os.path.normpath(os.path.join(dir_path, audio_filename))

    if not os.path.exists(audio_file_path):
        print(f"DEBUG: ERROR - El archivo de audio no existe: {audio_file_path}")
        return

    print(f"DEBUG: Intentando reproducir con VLC: {audio_file_path}")

    media = MediaPlayer(audio_file_path)
    if media.play() == -1:
        print("DEBUG: ERROR - VLC no pudo iniciar la reproducción.")
        media.release()
        return

    # Esperar a que la reproducción arranque DE VERDAD antes de vigilar el fin.
    for _ in range(50):  # hasta ~5s de margen para que VLC inicie
        if media.get_state() == State.Playing:
            break
        await asyncio.sleep(0.1)
    else:
        print("DEBUG: AVISO - VLC no llegó a iniciar la reproducción.")

    # Esperar a que termine (sin bloquear el resto del bot)
    while media.get_state() == State.Playing:
        await asyncio.sleep(0.1)

    print("DEBUG: Reproducción finalizada.")
    media.stop()
    media.release()

    # Gestión rotativa de archivos: Mantener los últimos 3
    _audio_history.append(audio_file_path)
    if len(_audio_history) > _AUDIO_HISTORY_LIMIT:
        oldest_file = _audio_history.pop(0)
        # Lanzar la limpieza en segundo plano para no retrasar el bot
        asyncio.create_task(_remove_with_retry(oldest_file))
