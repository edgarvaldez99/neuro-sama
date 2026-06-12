import asyncio
import json
from typing import List

from twitchio.ext import commands  # type: ignore

from .chat_ollama import ollama_completion
from .chattypes import ChatCompletionMessage
from .credentials import BOT_NAME, TWITCH_CHANNEL, TWITCH_TOKEN
from .filter_message import check_and_filter_user_message
from .tts import get_speech_by_text
from .utils import open_file, strip_cjk
from .vts_controller import get_vts_instance

CONVERSATION_LIMIT = 20
# Máximo de mensajes en espera. Si se llena (raid/spam), descartamos los nuevos
# para no responder con minutos de retraso a mensajes viejos.
MESSAGE_QUEUE_MAXSIZE = 20


class Bot(commands.Bot):
    conversation: List[ChatCompletionMessage] = []

    def __init__(self):
        self.system_prompt = open_file("prompt_chat.txt")
        self.message_queue = asyncio.Queue(maxsize=MESSAGE_QUEUE_MAXSIZE)
        self.worker_started = False
        # Referencias fuertes a tareas en segundo plano. El event loop solo
        # guarda referencias débiles, así que sin esto el GC podría recolectar
        # la tarea antes de que termine.
        self._background_tasks = set()
        super().__init__(
            token=TWITCH_TOKEN,
            prefix="!",
            initial_channels=[TWITCH_CHANNEL],
        )

    def _spawn_background(self, coro):
        """Lanza una corrutina en segundo plano conservando su referencia."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def message_worker(self):
        """Procesa los mensajes de la cola uno por uno secuencialmente"""
        while True:
            message = await self.message_queue.get()
            try:
                await self.process_message(message)
            except Exception as e:
                print(f"Error procesando mensaje: {e}")
            finally:
                self.message_queue.task_done()

    async def event_ready(self):
        print(f"Logged in as | {self.nick}")
        # Iniciar el procesador de mensajes solo cuando el loop esté corriendo
        if not self.worker_started:
            self._spawn_background(self.message_worker())
            self.worker_started = True

    async def event_message(self, message):
        if message.echo:
            return

        # Encolar sin bloquear; si la cola está llena, descartar el mensaje
        try:
            self.message_queue.put_nowait(message)
        except asyncio.QueueFull:
            print("DEBUG: Cola llena, mensaje descartado.")

    async def process_message(self, message):
        if check_and_filter_user_message(message):
            return

        # Preservamos el texto en UTF-8: el bot es en español y necesita
        # los acentos y la ñ para entender bien al chat.
        user_question = message.content.strip()
        user = message.author.name
        print("------------------------------------------------------")
        print(f"{user} say: {user_question}")

        # Inferencia en hilo separado para no bloquear el bucle
        raw_response = await asyncio.to_thread(
            ollama_completion,
            self.system_prompt,
            Bot.conversation + [{"role": "user", "content": user_question}],
        )

        # Si Ollama falló (None), no respondemos nada por TTS
        if raw_response is None:
            print("DEBUG: Sin respuesta de Ollama, se omite el mensaje.")
            await self.handle_commands(message)
            return

        # Parsear JSON de Ollama
        try:
            # Limpiar posibles caracteres extraños antes de parsear
            clean_raw = strip_cjk(raw_response)
            response_data = json.loads(clean_raw)
            bot_response = response_data.get("response_text", clean_raw)
            emotion = response_data.get("emotion", "neutral")
        except Exception as e:
            print(f"DEBUG: Error al parsear JSON de Ollama: {e}")
            bot_response = strip_cjk(raw_response)
            emotion = "neutral"

        print(f"{BOT_NAME}:", bot_response)
        print(f"DEBUG: Emoción detectada: {emotion}")

        # Actualizar historial (guardamos solo el texto para el contexto)
        Bot.conversation.append({"role": "user", "content": user_question})
        Bot.conversation.append({"role": "assistant", "content": bot_response})

        if len(Bot.conversation) > CONVERSATION_LIMIT:
            Bot.conversation = Bot.conversation[2:]

        # Activar Hotkey de emoción en VTube Studio (resuelto por modelo)
        vts = await get_vts_instance()
        # No esperamos (await) para no retrasar el audio
        self._spawn_background(vts.trigger_emotion(emotion))

        await get_speech_by_text(user_question, bot_response)

        await self.handle_commands(message)

    @commands.command(name="hola", aliases=["op", "haupei", "alo", "buen día"])
    async def hello(self, ctx: commands.Context):
        # Here we have a command hello, we can invoke our command with our
        # prefix and command name e.g ?hello
        # We can also give our commands aliases (different names)
        # to invoke with.

        # Send a hello back!
        # Sending a reply back to the channel is easy... Below is an example.
        await ctx.send(f"Hello {ctx.author.name}!")
