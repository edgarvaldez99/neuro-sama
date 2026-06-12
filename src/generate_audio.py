import asyncio
import os

from vlc import MediaPlayer, State  # type: ignore

# Historial para limpieza rotativa
_AUDIO_HISTORY_LIMIT = 3
_audio_history = []

# Referencias fuertes a las tareas de limpieza en segundo plano. El event loop
# solo guarda referencias débiles, así que sin esto el GC podría recolectar la
# tarea antes de que termine. Se descarta sola al completarse.
_background_tasks: set = set()


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


async def play_audio(audio_filename: str):
    # El motor de TTS ya generó el archivo; acá solo lo reproducimos.
    dir_path = os.environ.get("BASE_DIR_PATH", os.getcwd())
    # Usar rutas normales de Windows
    audio_file_path = os.path.normpath(os.path.join(dir_path, audio_filename))

    if not os.path.exists(audio_file_path):
        print(f"DEBUG: ERROR - El archivo de audio no existe: {audio_file_path}")
        return

    print(f"DEBUG: Intentando reproducir con VLC: {audio_file_path}")

    media = MediaPlayer(audio_file_path)
    assert media is not None  # MediaPlayer siempre devuelve un reproductor válido
    if media.play() == -1:
        print("DEBUG: ERROR - VLC no pudo iniciar la reproducción.")
        media.release()
        return

    # Esperar a que la reproducción arranque DE VERDAD antes de vigilar el fin.
    for _ in range(50):  # hasta ~5s de margen para que VLC inicie
        if media.get_state() == State.Playing:  # type: ignore
            break
        await asyncio.sleep(0.1)
    else:
        print("DEBUG: AVISO - VLC no llegó a iniciar la reproducción.")

    # Esperar a que termine (sin bloquear el resto del bot)
    while media.get_state() == State.Playing:  # type: ignore
        await asyncio.sleep(0.1)

    print("DEBUG: Reproducción finalizada.")
    media.stop()
    media.release()

    # Gestión rotativa de archivos: Mantener los últimos 3
    _audio_history.append(audio_file_path)
    if len(_audio_history) > _AUDIO_HISTORY_LIMIT:
        oldest_file = _audio_history.pop(0)
        # Lanzar la limpieza en segundo plano para no retrasar el bot, guardando
        # una referencia fuerte hasta que la tarea termine (evita S7502 / GC).
        task = asyncio.create_task(_remove_with_retry(oldest_file))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
