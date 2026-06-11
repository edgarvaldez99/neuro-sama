from typing import List, Optional

import requests

from .chattypes import ChatCompletionMessage
from .logger import Logger


def ollama_completion(
    system_prompt: str,
    messages: List[ChatCompletionMessage],
    model: str = "qwen2.5:14b",
    temperature: float = 0.5,
    json_mode: bool = True,
    logger: Optional[Logger] = None,
) -> str:
    """
    Realiza una petición al servidor local de Ollama.
    """
    url = "http://127.0.0.1:11434/api/chat"

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}]
        + [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }

    if json_mode:
        payload["format"] = "json"

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        content = data.get("message", {}).get("content", "").strip()

        if logger:
            logger.info(f"Ollama Response: {content}")

        return content
    except Exception as e:
        if logger:
            logger.fail(f"Error connecting to Ollama: {e}")
        return f"Error: No pude conectarme a Ollama. ¿Está corriendo? {e}"
