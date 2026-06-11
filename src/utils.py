import re


def open_file(filepath) -> str:
    with open(filepath, "r", encoding="utf-8") as infile:
        return infile.read()


def words_length(text: str) -> int:
    words = text.split(" ")
    return len(words)


# Rangos CJK (chino/japonés/kana y puntuación ancha) que qwen2.5 a veces filtra.
_CJK_PATTERN = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿＀-￯]+")


def strip_cjk(text: str) -> str:
    """Elimina texto CJK que el modelo puede colar y que rompería el TTS español."""
    cleaned = _CJK_PATTERN.sub("", text)
    # Colapsar espacios dobles que quedan tras quitar bloques de texto
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def clean_text_for_tts(text: str) -> str:
    """
    Limpia el texto para que el TTS no lea emojis ni símbolos raros literalmente.
    Mantiene puntuación básica (. , ! ?) para la entonación.
    """
    # 1. Eliminar Emojis y caracteres especiales de Unicode
    # Rango de emojis comunes y símbolos pictográficos
    text = re.sub(r"[^\x00-\x7F\xc0-\xff]+", "", text)

    # 2. Eliminar símbolos que a veces se leen literalmente
    # Mantener: a-z, A-Z, 0-9, áéíóúüñÁÉÍÓÚÜÑ y puntuación básica
    # Quitar: #, @, *, _, ~, etc.
    text = re.sub(r"[#@*_~]", "", text)

    # 3. Limpieza de espacios
    text = re.sub(r"\s+", " ", text).strip()

    return text
