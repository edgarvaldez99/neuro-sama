from typing import TypedDict


class ChatCompletionMessage(TypedDict):
    """Mensaje de chat estilo OpenAI ({"role": ..., "content": ...}).

    Definido localmente para que el stack local (Ollama) no dependa del paquete
    ``openai``. Solo necesitamos estos dos campos para armar el historial.
    """

    role: str
    content: str
