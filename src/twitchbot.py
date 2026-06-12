import asyncio
import json
from typing import List

from twitchio.ext import commands  # type: ignore

from .chat_ollama import ollama_completion
from .chattypes import ChatCompletionMessage
from .credentials import BOT_NAME, TWITCH_CHANNEL, TWITCH_TOKEN
from .filter_message import check_and_filter_user_message
from .texttospeech_edge import get_speech_by_text
from .utils import open_file, strip_cjk
from .vts_controller import EMOTION_TO_HOTKEY, get_vts_instance
from .websocket import open_websocket

CONVERSATION_LIMIT = 20


class Bot(commands.Bot):
    conversation: List[ChatCompletionMessage] = list()

    def __init__(self, speaker_bot=False, speaker_alias="Default"):
        self.system_prompt = open_file("prompt_chat.txt")
        self.speaker_bot = speaker_bot
        self.speaker_alias = speaker_alias
        self.message_queue = asyncio.Queue()
        self.worker_started = False
        super().__init__(
            token=TWITCH_TOKEN,
            prefix="!",
            initial_channels=[TWITCH_CHANNEL],
        )

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
            asyncio.create_task(self.message_worker())
            self.worker_started = True

    async def event_message(self, message):
        if message.echo:
            return

        # Poner el mensaje en la cola en lugar de procesarlo directamente
        await self.message_queue.put(message)

    async def process_message(self, message):
        if check_and_filter_user_message(message):
            return

        msg = message.content
        user = message.author.name
        user_question = msg.encode(encoding="ASCII", errors="ignore").decode()
        print("------------------------------------------------------")
        print(f"{user} say: {user_question}")

        # Inferencia en hilo separado para no bloquear el bucle
        raw_response = await asyncio.to_thread(
            ollama_completion,
            self.system_prompt,
            Bot.conversation + [{"role": "user", "content": user_question}],
        )

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

        # Activar Hotkey en VTube Studio si la emoción está mapeada
        if emotion in EMOTION_TO_HOTKEY:
            vts = await get_vts_instance()
            hotkey_name = EMOTION_TO_HOTKEY[emotion]
            # No esperamos (await) para no retrasar el audio
            asyncio.create_task(vts.trigger_hotkey(hotkey_name))

        if self.speaker_bot:
            await self.send_to_speaker_bot(bot_response)
        else:
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

    async def send_to_speaker_bot(self, message: str, verbose=False) -> None:
        """
        Sends message to speaker.bot websocket using standart setup
        @param message: the message you want to have spoken
        @param verbose: set to true if debugging info is wanted
        """

        await open_websocket(self.speaker_alias, message, verbose)
