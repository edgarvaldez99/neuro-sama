"""
Módulo de VISIÓN de Mai-chan.

Captura lo que se ve en la pantalla (un video de YouTube, una peli, un anime, un
gameplay...) y se lo pasa a un modelo de visión local (VLM) servido por Ollama
para que lo "vea" y genere un comentario, igual que el micrófono inyecta voz.

Tiene dos caras:

1. **Integrado al bot** (lo normal): la clase ``ScreenVision`` corre como un
   productor más del pipeline —calcado de ``LocalSTT``—, mirando la pantalla en
   bucle ``async`` y haciendo ``bot.inject_vision_message(...)`` cuando la escena
   cambia. Se arranca desde ``main.py`` si ``VISION_ENABLED=true``.

2. **Prototipo standalone** (para validar visión sin levantar el bot):

       poetry run python -m src.screen_vision

Arquitectura de 2 etapas (ver docs/plan_vision_general.md §5.3):
  - El VLM solo DESCRIBE lo que ve (barato, objetivo) → modo ``describe``.
  - El texto se inyecta a la cola y el LLM de personalidad (qwen2.5, vía
    ``process_message``) lo convierte en un comentario con el carácter de Mai-chan.
Para demos rápidas existe el modo ``react`` (el VLM comenta directo, una sola
etapa); la calidad real viene de las 2 etapas.

Toda la configuración se lee de .env (ver .env.example). Los DEFAULTS apuntan a
PRODUCCIÓN (RTX 3090, qwen3-vl:8b); para desarrollar en una GPU chica basta
sobreescribir ``VISION_VLM_MODEL`` y demás en el .env local.

NOTA sobre el modelo: usá la variante **-instruct** de qwen3-vl
(``qwen3-vl:4b-instruct`` en dev, ``qwen3-vl:8b-instruct`` en prod). La variante
genérica (``qwen3-vl:4b``) es *thinking* y se cuelga razonando sin emitir la
descripción. Requiere Ollama >= 0.30 (el v0.5.7 la rechaza con HTTP 412).
``llava:7b`` sirve de respaldo pero es de menor calidad (párrafos, español flojo).
"""

import asyncio
import base64
import io
import json
import time
from typing import Optional, Tuple

import requests
from decouple import config as environ  # type: ignore
from PIL import Image, ImageChops, ImageGrab, ImageStat

# --- Configuración (todo leído de .env, con defaults para PRODUCCIÓN / 3090) ---
# Los defaults apuntan a la PC de producción (RTX 3090). Para desarrollar en una
# GPU chica (ej: GTX 1660 6GB) basta sobreescribir estas vars en tu .env local
# (ver .env.example), sin tocar código.

OLLAMA_URL = (
    str(environ("OLLAMA_HOST", default="http://127.0.0.1:11434")).rstrip("/")
    + "/api/chat"
)

# Modelo de visión (VLM). Default qwen3-vl:8b-instruct (3090). En dev/6GB poné en
# .env qwen3-vl:4b-instruct. IMPORTANTE: usá la variante **-instruct**, NO la
# genérica (qwen3-vl:4b/:8b): esa es la variante *thinking* y se cuelga razonando
# (gasta todo el presupuesto en <think> y nunca emite la descripción). qwen-vl
# requiere Ollama actualizado (>= 0.30; el v0.5.7 lo rechaza con HTTP 412).
VLM_MODEL = str(environ("VISION_VLM_MODEL", default="qwen3-vl:8b-instruct"))

# Cada cuántos segundos mira la pantalla. Prod 3090: 2-4s. Dev 1660: 5-8s
# (GPU más lenta). Más bajo = más reactiva pero más carga y más riesgo de spamear.
INTERVAL_SECONDS = float(environ("VISION_INTERVAL_SECONDS", default=3.0))

# Ancho al que se reduce el frame antes de mandarlo al VLM. Mandar 4K es lento e
# innecesario; ~1280px conserva detalle suficiente y acelera la inferencia.
MAX_WIDTH = int(environ("VISION_MAX_WIDTH", default=1280))

# Límite de tokens de salida del VLM. Bajarlo reduce MUCHO la latencia (la prueba
# en dev pasó de 47s a 5-12s). Prod: 128. Dev: 64.
NUM_PREDICT = int(environ("VISION_NUM_PREDICT", default=128))

# Umbral de cambio de escena (0-100). Si dos capturas seguidas se parecen más que
# esto, NO se comenta (evita repetir lo mismo en una escena estática). Subir para
# ser más selectivo, bajar para reaccionar a cambios sutiles.
SCENE_CHANGE_THRESHOLD = float(environ("VISION_SCENE_THRESHOLD", default=6.0))

# Región a capturar: None = pantalla completa. Para capturar solo la ventana del
# video, poné una tupla (left, top, right, bottom) en píxeles.
REGION: Optional[Tuple[int, int, int, int]] = None

# Modo de prompt: "describe" (objetivo, 2 etapas — recomendado integrado) o
# "react" (el VLM comenta directo, 1 etapa — atajo para demos).
PROMPT_MODE = str(environ("VISION_PROMPT_MODE", default="react"))

SYSTEM_PROMPTS = {
    "react": (
        "Sos Mai-chan, una VTuber sarcástica y con humor. Te van a pasar una "
        "captura de lo que estás viendo en stream (un video, anime, juego, etc). "
        "Reaccioná con UN comentario corto y natural en español (1 oración), como "
        "lo haría una streamer. No describas la imagen como un robot; reaccioná. "
        'Respondé SOLO un JSON: {"comentario": "...", "vale_la_pena": true|false}. '
        "Poné vale_la_pena en false si no hay nada interesante que comentar."
    ),
    "describe": (
        "Sos un módulo de visión. Describí en español, objetivo y en una frase "
        "corta, qué está pasando en esta captura de pantalla. "
        'Respondé SOLO un JSON: {"descripcion": "...", "vale_la_pena": true|false}.'
    ),
}


# --- Captura ---------------------------------------------------------------


def capture_screen(
    region: Optional[Tuple[int, int, int, int]] = None,
) -> Image.Image:
    """Captura la pantalla (o una región) y la devuelve como imagen RGB."""
    img = ImageGrab.grab(bbox=region)
    return img.convert("RGB")


def downscale(img: Image.Image, max_width: int = MAX_WIDTH) -> Image.Image:
    """Reduce la imagen para que el VLM la procese rápido."""
    if img.width <= max_width:
        return img
    ratio = max_width / img.width
    new_size = (max_width, int(img.height * ratio))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def encode_image(img: Image.Image) -> str:
    """Codifica la imagen como JPEG en base64 (lo que espera Ollama)."""
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def scene_difference(a: Optional[Image.Image], b: Image.Image) -> float:
    """
    Devuelve cuánto cambió la escena entre dos frames (0 = idénticos).

    Compara miniaturas en escala de grises: barato y suficiente para saber si la
    pantalla cambió lo bastante como para valer un comentario nuevo.
    """
    if a is None:
        return 100.0
    size = (64, 36)
    ga = a.resize(size).convert("L")
    gb = b.resize(size).convert("L")
    diff = ImageChops.difference(ga, gb)
    # Media de la diferencia (banda "L", única) normalizada a 0-100.
    media = ImageStat.Stat(diff).mean[0]
    return media / 255.0 * 100.0


# --- Inferencia VLM --------------------------------------------------------


def look_at(img: Image.Image, mode: str = PROMPT_MODE) -> Optional[dict]:
    """
    Manda el frame al VLM y devuelve el JSON parseado (o None si falló).

    Sigue el mismo patrón que src/chat_ollama.ollama_completion, pero adjuntando
    la imagen en el campo `images` del mensaje (API de visión de Ollama).
    """
    system = SYSTEM_PROMPTS[mode]
    b64 = encode_image(downscale(img))

    payload = {
        "model": VLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "¿Qué ves en pantalla ahora?",
                "images": [b64],
            },
        ],
        "stream": False,
        "format": "json",
        "keep_alive": "30m",
        "options": {"temperature": 0.6, "num_predict": NUM_PREDICT},
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=(5, 120))
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"DEBUG: Error consultando al VLM: {e}")
        return None

    try:
        return json.loads(content)
    except Exception:
        # Si el modelo no devolvió JSON limpio, igual mostramos el texto crudo
        return {"comentario": content, "vale_la_pena": True}


def extract_text(result: Optional[dict]) -> str:
    """Saca el texto útil del JSON del VLM, sea modo describe o react."""
    if not result:
        return ""
    texto = result.get("comentario") or result.get("descripcion") or ""
    return str(texto).strip()


# --- Productor integrado al bot --------------------------------------------


class ScreenVision:
    """
    Productor de visión: mira la pantalla y alimenta la cola del bot.

    Es el análogo de ``LocalSTT`` pero para la vista. Corre en el mismo event
    loop; su ``watch_loop`` se arranca desde ``main.py`` junto a ``bot.start()``
    y ``stt.listen_loop()``.
    """

    def __init__(
        self,
        bot_instance,
        region: Optional[Tuple[int, int, int, int]] = REGION,
        interval: float = INTERVAL_SECONDS,
        mode: str = PROMPT_MODE,
    ):
        self.bot = bot_instance
        self.region = region
        self.interval = interval
        self.mode = mode
        self._prev: Optional[Image.Image] = None

    async def watch_loop(self) -> None:
        """Mira la pantalla en bucle e inyecta a la cola cuando la escena cambia."""
        print(
            f"DEBUG: Visión activa. modelo={VLM_MODEL} "
            f"intervalo={self.interval}s modo={self.mode}"
        )
        while True:
            start = time.time()

            # Mientras Mai-chan habla no miramos: ni tiene sentido comentar (el
            # video puede estar pausado), ni queremos encolar más audio encima.
            # Mismo criterio anti-eco que usa el micrófono con is_speaking.
            if self.bot.is_speaking:
                await asyncio.sleep(self.interval)
                continue

            try:
                # Captura e inferencia son BLOQUEANTES (ImageGrab y requests):
                # a un hilo, para no congelar el event loop (si no, twitchio y el
                # micro se frenan).
                frame = await asyncio.to_thread(capture_screen, self.region)
                change = scene_difference(self._prev, frame)

                if change >= SCENE_CHANGE_THRESHOLD:
                    result = await asyncio.to_thread(look_at, frame, self.mode)
                    self._prev = frame
                    texto = extract_text(result)
                    vale = bool(result.get("vale_la_pena", True)) if result else False
                    if vale and texto:
                        await self.bot.inject_vision_message(texto)
            except Exception as e:
                print(f"DEBUG: Error en el loop de visión: {e}")

            # Respetar el intervalo descontando lo que tardó la inferencia
            elapsed = time.time() - start
            await asyncio.sleep(max(0.0, self.interval - elapsed))


# --- Loop de demo (prototipo standalone) -----------------------------------


def _demo_loop() -> None:
    """Versión síncrona para probar la visión sin levantar el bot."""
    print("DEBUG: Módulo de visión (demo standalone). Mirando la pantalla...")
    print(
        f"DEBUG: modelo={VLM_MODEL}  intervalo={INTERVAL_SECONDS}s  modo={PROMPT_MODE}"
    )
    print("DEBUG: Poné un video en pantalla. Ctrl+C para salir.\n")

    prev: Optional[Image.Image] = None
    while True:
        start = time.time()
        frame = capture_screen(REGION)

        change = scene_difference(prev, frame)
        if change < SCENE_CHANGE_THRESHOLD:
            print(f"DEBUG: (sin cambios relevantes, dif={change:.1f}) — no comenta")
        else:
            result = look_at(frame)
            texto = extract_text(result)
            vale = bool(result.get("vale_la_pena", True)) if result else False
            if vale and texto:
                # Integrado, acá iría: bot.inject_vision_message(texto)
                print(f"\n👁️  Mai-chan: {texto}\n")
            else:
                print(f"DEBUG: (nada que comentar, dif={change:.1f})")
            prev = frame

        # Respetar el intervalo descontando lo que tardó la inferencia
        elapsed = time.time() - start
        time.sleep(max(0.0, INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    try:
        _demo_loop()
    except KeyboardInterrupt:
        print("\nDEBUG: Visión detenida.")
