import re

from twitchio import Message  # type: ignore


def check_and_filter_user_message(message: Message) -> bool:
    """
    Retorna True si el mensaje debe ser filtrado (ignorado).
    """
    if message.echo:
        return True

    user_message = (message.content or "").strip()

    # Filtro de longitud
    if len(user_message) > 150 or len(user_message) < 2:
        return True

    # Si es un comando de twitch bot, ignorar
    if user_message.startswith("!"):
        return True

    # Extraer palabras (solo alfanuméricos). Si no hay ninguna (puro
    # símbolo/spam de caracteres), descartar.
    words_in_message = re.findall(r"\w+", user_message.lower())
    if not words_in_message:
        return True

    return False
