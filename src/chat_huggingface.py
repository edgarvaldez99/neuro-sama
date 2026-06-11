from typing import Iterable, List

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

from .chattypes import ChatCompletionMessage
from .credentials import BOT_NAME, HUGGING_FACE_MODEL
from .logger import Logger

_default_stop = [f"{BOT_NAME}:", "CHATTER:"]


def local_model_completion(
    system_prompt: Iterable[ChatCompletionMessage],
    messages: Iterable[ChatCompletionMessage] = tuple(),
    logger: Logger | None = None,
    model_name=HUGGING_FACE_MODEL,
    verbose=False,
    temp=0.9,
    tokens=150,
    freq_pen=2.0,
    pres_pen=2.0,
    stop: List[str] = _default_stop,
):
    # Inicializar el modelo y el tokenizador (se descargarán la primera vez)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name)

    # Preparar el input
    input_text = ""
    for m in system_prompt:
        input_text += f"{m['role']}: {m['content']}\n"
    for m in messages:
        input_text += f"{m['role']}: {m['content']}\n"

    if logger is not None:
        logger.info(input_text, verbose)

    # Tokenizar el input
    input_ids = tokenizer.encode(input_text, return_tensors="pt")

    # Configurar los parámetros de generación
    gen_kwargs = {
        "max_new_tokens": tokens,
        "temperature": temp,
        "do_sample": True,
        "top_k": 50,
        "top_p": 0.95,
        "repetition_penalty": (freq_pen + pres_pen) / 2,  # Aproximación
        "pad_token_id": tokenizer.eos_token_id,
    }

    # Generar texto
    with torch.no_grad():
        output = model.generate(input_ids, **gen_kwargs)
    print(f"Output: {output}")
    # Decodificar la salida
    generated_text = tokenizer.decode(output[0], skip_special_tokens=True)
    print(f"Generated text: {generated_text}")
    # Eliminar el texto de entrada
    generated_text = generated_text[len(input_text) :].strip()  # noqa: E203
    print(f"Cleaned text: {generated_text}")
    # Procesar el texto generado para respetar los tokens de parada
    for stop_sequence in stop:
        if stop_sequence in generated_text:
            generated_text = generated_text.split(stop_sequence)[0]
    print(f"Final text: {generated_text}")
    return generated_text.strip()


# Ejemplo de uso
if __name__ == "__main__":
    system_prompt: Iterable[ChatCompletionMessage] = [
        {"role": "system", "content": "Eres un asistente útil."}
    ]
    messages: Iterable[ChatCompletionMessage] = [
        {"role": "user", "content": "¿Cuál es la capital de Francia?"}
    ]
    response = local_model_completion(system_prompt, messages)
    print(response)
