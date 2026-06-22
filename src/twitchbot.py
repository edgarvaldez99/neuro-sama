import asyncio
import json
from collections import deque
from typing import Deque, List

from decouple import config as environ  # type: ignore
from twitchio.ext import commands  # type: ignore

from . import memory
from .chat_ollama import ollama_completion
from .chattypes import ChatCompletionMessage
from .credentials import BOT_NAME, TWITCH_CHANNEL, TWITCH_TOKEN
from .filter_message import check_and_filter_user_message
from .media_controller import MediaController
from .tts import get_speech_by_text
from .utils import open_file, strip_cjk
from .vts_controller import get_vts_instance

COMMAND_PREFIX = "!"
CONVERSATION_LIMIT = 20
MESSAGE_QUEUE_MAXSIZE = 20
# Cuántas frases recientes de Mai-chan se le recuerdan en el prompt para que no
# se repita. Es un buffer aparte del historial (que se recorta a 20 e incluye lo
# que dicen los demás): acá guardamos SOLO lo que ella dijo, como lista de "no
# repitas esto". Ver _anti_repeat_directive.
RECENT_SAID_LIMIT = 8

# Modos de atención (docs/plan_vision_general.md §7): cada modo define QUÉ
# prioridad recibe cada fuente (chat / micro / visión / director) en la cola.
# Número menor = se atiende antes. El micro (el dueño del stream) va siempre
# primero; el director (acciones proactivas en silencio) siempre último, para que
# solo rellene cuando no hay nada más. Lo que cambia entre modos es si pesa más el
# chat o el video. Configurable por .env (ATTENTION_MODE) y en vivo con "!mode".
ATTENTION_MODES = {
    "VIDEO_FIRST": {"mic": 0, "vision": 1, "chat": 2, "director": 3},
    "CHAT_FIRST": {"mic": 0, "chat": 1, "vision": 2, "director": 3},
    "HYBRID": {"mic": 0, "chat": 1, "vision": 1, "director": 3},
}
DEFAULT_ATTENTION_MODE = str(environ("ATTENTION_MODE", default="HYBRID")).upper()

# Director loop (autonomía, §9): en silencio, encola acciones proactivas. Apagado
# por defecto (es intrusivo); activable por .env.
DIRECTOR_ENABLED = environ("DIRECTOR_ENABLED", default=False, cast=bool)
DIRECTOR_INTERVAL = float(environ("DIRECTOR_INTERVAL_SECONDS", default=45.0))

# Variedad para el director: si siempre se le manda EL MISMO pedido, el LLM (con
# temperatura baja) converge a la misma frase y suena robótico. Rotamos entre
# semillas concretas y distintas; cada una empuja a Mai-chan a un tipo de
# intervención diferente, así sus rellenos de silencio no se repiten.
DIRECTOR_HINTS = [
    "(Hay un silencio en el stream. Hacele una pregunta directa y concreta al "
    "chat —sobre comida, juegos, planes del finde, lo que sea— para que "
    "respondan.)",
    "(Hay un silencio en el stream. Contá en tu personaje una anécdota corta y "
    "medio absurda, como si te hubiera pasado a vos recién.)",
    "(Hay un silencio en el stream. Tirá una opinión random tuya, divertida e "
    "inofensiva, para generar charla.)",
    "(Hay un silencio en el stream. Quejate en broma de que nadie escribe y "
    "desafiá al chat a decir algo.)",
    "(Hay un silencio en el stream. Proponé un mini-juego o una pregunta tipo "
    "'¿esto o aquello?' al chat.)",
    "(Hay un silencio en el stream. Comentá algo curioso o random que se te venga "
    "a la cabeza en este momento, en tu personaje.)",
]

# Coletilla anti-repetición: se agrega a CUALQUIER pedido del director (incluido
# el de la agenda) para que no calque una respuesta que ya dio hace poco.
DIRECTOR_NO_REPEAT = (
    " No repitas lo que ya dijiste antes en el stream; decí algo distinto y fresco."
)

# Alias amigables para el comando "!mode".
_MODE_ALIASES = {
    "video": "VIDEO_FIRST",
    "chat": "CHAT_FIRST",
    "hybrid": "HYBRID",
    "hibrido": "HYBRID",
}


class FakeAuthor:
    def __init__(self, name):
        self.name = name


class FakeMessage:
    def __init__(self, content, author_name):
        self.content = content
        self.author = FakeAuthor(author_name)
        self.echo = False
        self.tags = {}  # Atributos mínimos para compatibilidad con twitchio


class Bot(commands.Bot):
    conversation: List[ChatCompletionMessage] = []

    def __init__(self):
        # Memoria persistente (SQLite). El brief de sesión (capa B del plan §9:
        # resúmenes de streams pasados + agenda de hoy) se antepone al prompt para
        # dar continuidad entre sesiones, sin que nadie tipee nada en vivo.
        memory.init_db()
        self.system_prompt = self._with_session_brief(open_file("prompt_chat.txt"))
        # Cola PRIORITARIA: chat, micro, visión y director compiten según el modo
        # de atención. Guarda tuplas (prioridad, secuencia, mensaje); ver _enqueue.
        self.message_queue = asyncio.PriorityQueue(maxsize=MESSAGE_QUEUE_MAXSIZE)
        self.attention_mode = (
            DEFAULT_ATTENTION_MODE
            if DEFAULT_ATTENTION_MODE in ATTENTION_MODES
            else "HYBRID"
        )
        self._seq = 0  # desempate FIFO dentro de una misma prioridad
        self._director_idx = 0  # rota las semillas del director (anti-repetición)
        # Últimas frases que dijo Mai-chan (anti-repetición). Buffer corto que se
        # le recuerda en cada prompt; sobrevive al recorte del historial.
        self._recent_said: Deque[str] = deque(maxlen=RECENT_SAID_LIMIT)
        self.worker_started = False
        self.is_speaking = False  # Flag para indicar si el bot está hablando
        # Pausa/baja el video mientras Mai-chan habla (Nivel 1). Apagado por
        # defecto; se configura por .env (ver src/media_controller.py).
        self.media = MediaController()
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

    def _enqueue(self, message, source: str) -> None:
        """Encola un mensaje con la prioridad que su fuente tiene en el modo actual.

        La cola es prioritaria: chat, micro y visión compiten según
        `attention_mode`. El contador `_seq` desempata por orden de llegada (FIFO)
        dentro de una misma prioridad y, además, evita que PriorityQueue intente
        comparar los mensajes entre sí (no son comparables).
        """
        prio = ATTENTION_MODES[self.attention_mode].get(source, 1)
        self._seq += 1
        try:
            self.message_queue.put_nowait((prio, self._seq, message))
        except asyncio.QueueFull:
            print(f"DEBUG: Cola llena, mensaje ({source}) descartado.")

    def _anti_repeat_directive(self) -> str:
        """Bloque para el prompt con las últimas frases de Mai-chan a NO repetir.

        Devuelve "" si todavía no dijo nada. Se concatena al system prompt en cada
        llamada (no se guarda en el historial), para darle una orden explícita de
        variar en vez de depender de que "se acuerde" del contexto.
        """
        if not self._recent_said:
            return ""
        lineas = "\n".join(f"- {t}" for t in self._recent_said)
        return (
            "\n\n[EVITÁ REPETIRTE] Ya dijiste estas frases hace muy poco. NO las "
            "repitas ni digas algo casi igual (ni la misma idea con otras "
            "palabras); cambiá de tema, enfoque o chiste:\n" + lineas
        )

    @staticmethod
    def _with_session_brief(base_prompt: str) -> str:
        """Antepone al prompt un brief con la memoria episódica + la agenda de hoy.

        Es la "capa B" del plan (§9): auto-generada desde lo que ya hay en SQLite,
        para que Mai-chan arranque con continuidad ("ayer con Pedro vimos Akira",
        "hoy toca reaccionar al video X") sin que el admin escriba nada en vivo.
        """
        partes = []
        resumenes = memory.get_recent_summaries(3)
        if resumenes:
            partes.append(
                "Contexto de streams anteriores (para dar continuidad):\n"
                + "\n".join(f"- {s}" for s in resumenes)
            )
        agenda = memory.get_agenda()
        if agenda:
            partes.append(
                "Tu plan para el stream de hoy:\n" + "\n".join(f"- {a}" for a in agenda)
            )
        if not partes:
            return base_prompt
        return base_prompt + "\n\n" + "\n\n".join(partes)

    async def save_stream_summary(self) -> None:
        """Genera con el LLM un resumen del stream y lo persiste (memoria episódica).

        Se llama al apagar el bot. Si no hubo conversación o Ollama no responde, no
        guarda nada (best-effort, nunca rompe el apagado).
        """
        if not Bot.conversation:
            return
        transcripcion = "\n".join(
            f"{m['role']}: {m['content']}" for m in Bot.conversation
        )
        instruccion = (
            "Resumí en 1-2 frases en español, en tercera persona, lo más "
            "destacado de este stream (temas, invitados, promesas hechas al "
            "chat). Devolvé solo el resumen, sin comillas ni JSON."
        )
        resumen = await asyncio.to_thread(
            ollama_completion,
            instruccion,
            [{"role": "user", "content": transcripcion}],
            json_mode=False,
        )
        if resumen:
            await asyncio.to_thread(memory.save_summary, strip_cjk(resumen).strip())
            print(f"DEBUG: Resumen del stream guardado: {resumen.strip()}")

    async def director_loop(self) -> None:
        """Autonomía (§9): en silencio, encola acciones proactivas de baja prioridad.

        Si no hay nada en la cola y Mai-chan no está hablando, mete un evento del
        "[DIRECTOR]" para que retome su plan del día o suelte un comentario, así el
        stream no se queda mudo. Compite en la cola con prioridad mínima, de modo
        que cualquier chat/voz/visión real lo desplaza.
        """
        print(f"DEBUG: Director loop activo (cada {DIRECTOR_INTERVAL}s en silencio).")
        while True:
            await asyncio.sleep(DIRECTOR_INTERVAL)
            # Solo rellenar el silencio: si hay actividad, no interrumpir.
            if self.is_speaking or not self.message_queue.empty():
                continue
            agenda = memory.get_agenda()
            if agenda:
                hint = (
                    "(Hay un silencio en el stream. Retomá tu plan de hoy: "
                    f"'{agenda[0]}'. Decí algo natural al respecto.)"
                )
            else:
                # Round-robin sobre las semillas: garantiza que dos rellenos
                # seguidos nunca parten del mismo pedido (mejor que aleatorio,
                # que podría repetir).
                hint = DIRECTOR_HINTS[self._director_idx % len(DIRECTOR_HINTS)]
                self._director_idx += 1
            msg = FakeMessage(hint + DIRECTOR_NO_REPEAT, "[DIRECTOR]")
            self._enqueue(msg, "director")

    async def message_worker(self):
        """Procesa los mensajes de la cola uno por uno secuencialmente"""
        while True:
            # La cola entrega tuplas (prioridad, secuencia, mensaje).
            _prio, _seq, message = await self.message_queue.get()
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

        # Los comandos (!mode, !hola...) se atienden aparte y NO entran al
        # pipeline de Ollama: si no, "!mode video" se interpretaría como algo a
        # lo que reaccionar en vez de ejecutarse.
        if (message.content or "").startswith(COMMAND_PREFIX):
            await self.handle_commands(message)
            return

        self._enqueue(message, "chat")

    async def process_message(self, message):
        if check_and_filter_user_message(message):
            return

        # Silenciamos el micro durante TODO el procesamiento, no solo la
        # reproducción: mientras Ollama piensa y mientras suena el audio, el STT
        # ignora la entrada para no captar la propia voz del bot ni al streamer
        # encimándose. Se restaura en el finally pase lo que pase.
        self.is_speaking = True
        try:
            await self._generate_and_speak(message)
        finally:
            self.is_speaking = False

    async def _generate_and_speak(self, message):
        # Preservamos el texto en UTF-8: el bot es en español y necesita
        # los acentos y la ñ para entender bien al chat.
        user_question = message.content.strip()
        user = message.author.name
        print("------------------------------------------------------")
        print(f"{user} say: {user_question}")

        # Memoria (capa 1): registrar al viewer real (no mic/visión/director). Si
        # es su primera vez, le damos la pista al LLM para que lo salude.
        if not isinstance(message, FakeMessage):
            uid = str(getattr(message.author, "id", None) or user)
            info = await asyncio.to_thread(memory.record_viewer, uid, user)
            if info["nuevo"]:
                user_question = (
                    f"[{user} escribe por primera vez en tu chat] {user_question}"
                )

        # Inferencia en hilo separado para no bloquear el bucle. Al system prompt
        # le sumamos (solo para esta llamada) la lista de "no repitas esto".
        raw_response = await asyncio.to_thread(
            ollama_completion,
            self.system_prompt + self._anti_repeat_directive(),
            Bot.conversation + [{"role": "user", "content": user_question}],
        )

        # Si Ollama falló (None), no respondemos nada por TTS
        if raw_response is None:
            print("DEBUG: Sin respuesta de Ollama, se omite el mensaje.")
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
        # Registrar lo que dijo para el anti-repetición del próximo turno.
        self._recent_said.append(bot_response)

        if len(Bot.conversation) > CONVERSATION_LIMIT:
            Bot.conversation = Bot.conversation[2:]

        # Activar Hotkey de emoción en VTube Studio (resuelto por modelo)
        vts = await get_vts_instance()
        # No esperamos (await) para no retrasar el audio
        self._spawn_background(vts.trigger_emotion(emotion))

        # Pausamos/bajamos el video JUSTO antes de que suene la voz (no antes de
        # generar: mientras Ollama piensa el video puede seguir). Se restaura en
        # el finally pase lo que pase, para no dejar el video pausado/silenciado.
        self.media.antes_de_hablar()
        try:
            await get_speech_by_text(user_question, bot_response)
        finally:
            self.media.al_terminar()

    async def inject_mic_message(self, text: str):
        """Inyecta un mensaje de voz (micro del streamer) en la cola del bot."""
        message = FakeMessage(content=text, author_name="Streamer")
        self._enqueue(message, "mic")

    async def inject_vision_message(self, descripcion: str):
        """
        Inyecta lo que Mai-chan ve en pantalla como un evento más de la cola.

        Etapa 2 de la arquitectura de visión (ver docs/plan_vision_general.md
        §5.3): el VLM ya describió la escena; acá la metemos al MISMO pipeline que
        chat y micro, envuelta en contexto para que el LLM de personalidad sepa
        que es algo que VE (no algo que alguien le dijo) y reaccione en carácter.
        """
        content = f"(En pantalla estás viendo: {descripcion})"
        message = FakeMessage(content=content, author_name="[VISIÓN]")
        self._enqueue(message, "vision")

    @commands.command(name="mode")
    async def set_mode(self, ctx: commands.Context):
        """Cambia el modo de atención en vivo. Solo el dueño del canal.

        Uso: !mode video | chat | hybrid
        """
        if not getattr(ctx.author, "is_broadcaster", False):
            return
        parts = (ctx.message.content or "").split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""
        nuevo = _MODE_ALIASES.get(arg)
        if not nuevo:
            await ctx.send(
                f"Uso: !mode video | chat | hybrid (actual: {self.attention_mode})"
            )
            return
        self.attention_mode = nuevo
        await ctx.send(f"Modo de atención: {nuevo}")

    @commands.command(name="agenda")
    async def agenda_cmd(self, ctx: commands.Context):
        """Gestiona el plan del día (memoria). Solo el dueño del canal.

        `!agenda` lista lo pendiente; `!agenda <texto>` agrega una tarea/idea.
        """
        if not getattr(ctx.author, "is_broadcaster", False):
            return
        parts = (ctx.message.content or "").split(maxsplit=1)
        if len(parts) < 2:
            pendientes = memory.get_agenda()
            if pendientes:
                await ctx.send("Plan de hoy: " + " | ".join(pendientes))
            else:
                await ctx.send("Hoy no hay nada agendado. Uso: !agenda <qué hacer>")
            return
        tarea = parts[1].strip()
        await asyncio.to_thread(memory.add_agenda, tarea, None, ctx.author.name or "")
        await ctx.send(f"Agendado para hoy: {tarea}")

    @commands.command(name="hola", aliases=["op", "haupei", "alo", "buen día"])
    async def hello(self, ctx: commands.Context):
        # Here we have a command hello, we can invoke our command with our
        # prefix and command name e.g ?hello
        # We can also give our commands aliases (different names)
        # to invoke with.

        # Send a hello back!
        # Sending a reply back to the channel is easy... Below is an example.
        await ctx.send(f"Hello {ctx.author.name}!")
