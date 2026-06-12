from typing import List, Optional

import requests
from decouple import config as environ  # type: ignore

from .chattypes import ChatCompletionMessage
from .logger import Logger

# Modelo de Ollama a usar. Configurable en .env (OLLAMA_MODEL). Por defecto
# qwen2.5:3b, que entra 100% en GPU en placas de ~6GB compartiendo con VTS.
OLLAMA_MODEL = str(environ("OLLAMA_MODEL", default="qwen2.5:3b"))


def ollama_completion(
    system_prompt: str,
    messages: List[ChatCompletionMessage],
    model: str = OLLAMA_MODEL,
    temperature: float = 0.5,
    json_mode: bool = True,
    logger: Optional[Logger] = None,
) -> Optional[str]:
    """
    Realiza una petición al servidor local de Ollama.

    Devuelve el texto de la respuesta, o ``None`` si hubo un error de conexión
    (para que el llamador omita la respuesta en vez de sintetizar el error).
    """
    url = "http://127.0.0.1:11434/api/chat"

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}]
        + [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": False,
        # Mantener el modelo en VRAM 30 min para no recargarlo en frío en cada mensaje
        "keep_alive": "30m",
        "options": {
            "temperature": temperature,
        },
    }

    if json_mode:
        payload["format"] = "json"

    try:
        # timeout=(conexión, lectura): evita colgar la cola si Ollama no responde
        response = requests.post(url, json=payload, timeout=(5, 120))
        response.raise_for_status()
        data = response.json()

        content = data.get("message", {}).get("content", "").strip()

        if logger:
            logger.info(f"Ollama Response: {content}")

        return content
    except Exception as e:
        if logger:
            logger.fail(f"Error connecting to Ollama: {e}")
        else:
            print(f"DEBUG: Error conectando a Ollama: {e}")
        return None
