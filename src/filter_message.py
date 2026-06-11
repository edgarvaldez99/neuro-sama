import re

import nltk  # type: ignore
from twitchio import Message  # type: ignore

# Inicializar NLTK una sola vez al cargar el módulo
try:
    nltk.data.find("corpora/words")
except LookupError:
    nltk.download("words")

try:
    nltk.data.find("corpora/cess_esp")
except LookupError:
    nltk.download("cess_esp")

# Cargar vocabularios en sets para búsqueda O(1)
_ENGLISH_WORDS = set(word.lower() for word in nltk.corpus.words.words())
_SPANISH_WORDS = set(word.lower() for word in nltk.corpus.cess_esp.words())


def check_and_filter_user_message(message: Message) -> bool:
    """
    Retorna True si el mensaje debe ser filtrado (ignorado).
    """
    if message.echo:
        return True

    user_message = message.content.strip()

    # Filtro de longitud
    if len(user_message) > 150 or len(user_message) < 2:
        return True

    # Si es un comando de twitch bot, ignorar
    if user_message.startswith("!"):
        return True

    # Extraer palabras (solo alfanuméricos)
    words_in_message = re.findall(r"\w+", user_message.lower())

    if not words_in_message:
        return True

    # El filtro original era muy agresivo.
    # Ahora: solo filtramos si NO encontramos ninguna palabra ni en inglés ni en español
    # (esto ayuda a filtrar spam de símbolos, caracteres aleatorios, etc.)
    has_valid_word = any(
        w in _ENGLISH_WORDS or w in _SPANISH_WORDS for w in words_in_message
    )

    if not has_valid_word:
        # Permitir si al menos tiene algunos caracteres comunes (emotes, etc)
        # o si la longitud es razonable, pero por ahora mantenemos una versión suave
        # de la validación de diccionario para evitar basura.
        return False  # Si no estamos seguros, mejor dejar pasar

    return False
