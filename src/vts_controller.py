import asyncio
import json
import os

import pyvts  # type: ignore
from decouple import config as environ  # type: ignore

# Puerto de la API de VTube Studio. Por defecto VTS usa 8001, pero si ese
# puerto está ocupado (p.ej. Docker/OpenKM), configurá otro en .env: VTS_PORT=8002
VTS_PORT = int(environ("VTS_PORT", default=8001))

# Segundos tras los que la expresión vuelve a neutral, para que el personaje no
# se quede "pegado" en una emoción. Configurable en .env (EMOTION_RESET_SECONDS).
EMOTION_RESET_SECONDS = float(environ("EMOTION_RESET_SECONDS", default=5.0))

# Palabras clave para mapear cada emoción al hotkey del modelo según su nombre.
# Como cada modelo de VTube Studio usa sus propios nombres de hotkey, el mapeo se
# resuelve en cada conexión buscando estas palabras dentro de los nombres reales.
EMOTION_KEYWORDS = {
    "happy": ["happy", "smile", "joy", "heart", "love", "laugh", "grin"],
    "sad": ["sad", "cry", "tear", "depress"],
    "angry": ["angry", "anger", "mad", "rage", "annoy"],
    "surprised": ["surprise", "shock", "wow", "gasp", "amaze"],
    "neutral": ["neutral", "default", "remove", "reset", "clear", "normal"],
}


def _overrides_path() -> str:
    base_dir = os.environ.get("BASE_DIR_PATH", ".")
    return os.path.join(base_dir, "emotion_hotkeys.json")


def _load_overrides() -> dict:
    """Lee emotion_hotkeys.json: { "<modelo>": { "<emoción>": "<hotkey>" } }."""
    try:
        with open(_overrides_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"DEBUG: Error leyendo emotion_hotkeys.json ({e}). Se ignora.")
        return {}


def _save_overrides(overrides: dict) -> None:
    try:
        with open(_overrides_path(), "w", encoding="utf-8") as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2)
        print("DEBUG: emotion_hotkeys.json actualizado con el mapeo detectado.")
    except Exception as e:
        print(f"DEBUG: No se pudo escribir emotion_hotkeys.json ({e}).")


class VTSController:
    def __init__(self) -> None:
        self.plugin_info = {
            "plugin_name": "Mai-chan Bot",
            "developer": "TavaTeam",
            "authentication_token_path": "./vts_token.txt",
        }
        self.vts = pyvts.vts(plugin_info=self.plugin_info, port=VTS_PORT)
        self.connected = False
        # Cache nombre_hotkey(lower) -> hotkeyID, se llena tras conectar
        self._hotkey_map: dict = {}
        # Mapeo emoción -> nombre de hotkey, resuelto dinámicamente por modelo
        self._emotion_map: dict = {}
        self.current_model: str = ""
        # Tarea pendiente que devuelve la expresión a neutral (se cancela si
        # llega una emoción nueva antes de tiempo).
        self._reset_task = None

    async def _authenticate(self) -> bool:
        """
        Autentica el plugin. Si el token guardado está inválido/revocado,
        lo borra y pide uno nuevo (dispara el popup de autorización en VTS).
        Devuelve True solo si quedó realmente autenticado.
        """
        await self.vts.request_authenticate_token()
        authenticated = await self.vts.request_authenticate()
        if authenticated:
            return True

        # Token inválido o revocado: borrar el archivo y reintentar de cero
        print(
            "DEBUG: Token VTS inválido/revocado. Solicitando uno nuevo... "
            "Aceptá el popup 'Mai-chan Bot' en VTube Studio."
        )
        token_path = self.plugin_info.get("authentication_token_path")
        if token_path and os.path.exists(token_path):
            os.remove(token_path)
        await self.vts.request_authenticate_token()
        authenticated = await self.vts.request_authenticate()
        return bool(authenticated)

    async def connect(self):
        try:
            await self.vts.connect()
            if not await self._authenticate():
                print("DEBUG: No se pudo autenticar en VTube Studio.")
                self.connected = False
                return
            await asyncio.sleep(1.0)  # Pausa para asegurar sesión en VTS
            self.connected = True
            print("DEBUG: Autenticación completada.")

            # Validar modelo cargado
            model_request = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "CurrentModelRequest",
                "messageType": "CurrentModelRequest",
            }
            model_data = await self.vts.request(model_request)

            model_loaded = model_data.get("data", {}).get("modelLoaded", False)
            if not model_loaded:
                print("DEBUG: [AVISO] No hay ningún modelo cargado en VTube Studio.")
                self.current_model = ""
            else:
                self.current_model = model_data.get("data", {}).get(
                    "modelName", "Desconocido"
                )
                print(f"DEBUG: Modelo detectado: {self.current_model}")

            # Cargar y cachear los hotkeys una sola vez tras conectar
            await self._refresh_hotkeys()

        except Exception as e:
            print(f"DEBUG: Error al conectar/autenticar con VTube Studio: {e}")
            self.connected = False

    async def _refresh_hotkeys(self):
        """
        Pide los hotkeys del modelo actual, los cachea y resuelve emociones.
        """
        list_request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "HotkeysInCurrentModelRequest",
            "messageType": "HotkeysInCurrentModelRequest",
        }
        hotkeys_data = await self.vts.request(list_request)
        hotkey_list = hotkeys_data.get("data", {}).get("availableHotkeys", [])
        self._hotkey_map = {
            hk["name"].strip().lower(): hk["hotkeyID"]
            for hk in hotkey_list
            if hk.get("name") and hk.get("hotkeyID")
        }
        if self._hotkey_map:
            print(f"DEBUG: Hotkeys VTS cacheados: {list(self._hotkey_map.keys())}")
        else:
            print(
                "DEBUG: Lista de Hotkeys VACÍA. "
                "Verifica modelo cargado y VTS enfocado."
            )

        self._resolve_emotion_map()

    def _resolve_emotion_map(self):
        """
        Resuelve emoción -> nombre de hotkey contra los hotkeys reales del modelo.
        Prioridad:
          1. Override manual en emotion_hotkeys.json (por nombre de modelo).
          2. Heurística: primer hotkey cuyo nombre contiene una palabra clave.
        Si el modelo no está en el archivo de override, guarda el mapeo detectado
        para que se pueda editar a mano.
        """
        available = list(self._hotkey_map.keys())  # nombres en minúscula
        overrides = _load_overrides()
        model_overrides = (
            overrides.get(self.current_model, {}) if self.current_model else {}
        )

        resolved = {}
        for emotion, keywords in EMOTION_KEYWORDS.items():
            override_name = model_overrides.get(emotion)
            if override_name:
                resolved[emotion] = override_name
                continue
            match = next(
                (name for name in available if any(kw in name for kw in keywords)),
                None,
            )
            if match:
                resolved[emotion] = match

        self._emotion_map = resolved
        if resolved:
            print(f"DEBUG: Mapeo de emociones resuelto: {resolved}")
        missing = [e for e in EMOTION_KEYWORDS if e not in resolved]
        if missing:
            print(
                f"DEBUG: Sin hotkey para {missing}. "
                "Podés mapearlos a mano en emotion_hotkeys.json."
            )

        # Si este modelo no estaba en el archivo, guardar scaffold editable
        if self.current_model and self.current_model not in overrides and resolved:
            overrides[self.current_model] = resolved
            _save_overrides(overrides)

    async def trigger_emotion(self, emotion: str):
        """Dispara el hotkey correspondiente a una emoción (happy/sad/...)."""
        if not self.connected:
            await self.connect()
        hotkey_name = self._emotion_map.get(emotion)
        if not hotkey_name:
            print(f"DEBUG: Emoción '{emotion}' sin hotkey mapeado, se omite.")
            return

        # Una emoción nueva manda: cancelamos el retorno a neutral pendiente
        # (si lo había) para reiniciar el contador desde cero.
        self._cancel_neutral_reset()
        await self.trigger_hotkey(hotkey_name)

        # Si la emoción no es ya neutral, programamos la vuelta a neutral para
        # que el personaje no se quede pegado en la expresión.
        if emotion != "neutral":
            self._schedule_neutral_reset()

    def _cancel_neutral_reset(self):
        """Cancela el retorno a neutral pendiente, si existe."""
        if self._reset_task and not self._reset_task.done():
            self._reset_task.cancel()
        self._reset_task = None

    def _schedule_neutral_reset(self):
        """Programa la vuelta a la expresión neutral tras EMOTION_RESET_SECONDS."""

        async def _back_to_neutral():
            try:
                await asyncio.sleep(EMOTION_RESET_SECONDS)
                neutral = self._emotion_map.get("neutral")
                if neutral:
                    await self.trigger_hotkey(neutral)
                    print("DEBUG: Expresión devuelta a neutral.")
            except asyncio.CancelledError:
                # Llegó otra emoción antes de tiempo; no hacemos nada.
                pass

        # Guardamos la referencia fuerte: el event loop solo tiene refs débiles,
        # así que sin esto el GC podría matar la tarea antes de que dispare.
        self._reset_task = asyncio.create_task(_back_to_neutral())

    async def trigger_hotkey(self, hotkey_name: str):
        if not self.connected:
            await self.connect()

        if not self.connected:
            return

        try:
            # 1. Buscar el hotkey en el cache (nombre -> hotkeyID)
            hotkey_id = self._hotkey_map.get(hotkey_name.strip().lower())

            # Si no está en cache, refrescar (p.ej. modelo recién cargado)
            if hotkey_id is None:
                await self._refresh_hotkeys()
                hotkey_id = self._hotkey_map.get(hotkey_name.strip().lower())

            if hotkey_id:
                trigger_request = {
                    "apiName": "VTubeStudioPublicAPI",
                    "apiVersion": "1.0",
                    "requestID": "HotkeyTriggerRequest",
                    "messageType": "HotkeyTriggerRequest",
                    "data": {"hotkeyID": hotkey_id},
                }
                await self.vts.request(trigger_request)
                print(f"DEBUG: Hotkey '{hotkey_name}' activado con éxito.")
                return

            # 2. Sin hotkey: intentar activar una expresión (.exp3.json) directamente.
            #    Algunos modelos tienen expresiones pero no crearon hotkeys.
            print(f"DEBUG: Hotkey '{hotkey_name}' no encontrado. Buscando expresión...")
            if not await self._trigger_expression(hotkey_name):
                print(f"DEBUG: Tampoco se encontró expresión para '{hotkey_name}'.")
        except Exception as e:
            print(f"DEBUG: Error al activar hotkey: {e}")

    async def _trigger_expression(self, name: str) -> bool:
        """
        Intenta activar una expresión (.exp3.json) cuyo nombre o archivo coincida
        con ``name``. Útil para modelos con expresiones pero sin hotkeys.
        Devuelve True si activó alguna.
        """
        exp_request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "ExpressionStateRequest",
            "messageType": "ExpressionStateRequest",
        }
        exp_data = await self.vts.request(exp_request)
        expressions = exp_data.get("data", {}).get("expressions", [])

        target = name.strip().lower()
        exp_file = None
        nombres_exp = []
        for exp in expressions:
            exp_name = exp.get("name", "")
            exp_path = exp.get("file", "")
            nombres_exp.append(exp_name)
            # Coincidir por nombre, por archivo (sin extensión) o ignorando "ex_"
            if (
                exp_name.lower() == target
                or exp_path.lower().replace(".exp3.json", "") == target
                or exp_name.lower().replace("ex_", "") == target.replace("ex_", "")
            ):
                exp_file = exp_path
                break

        if exp_file:
            set_exp_request = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "ExpressionActivationRequest",
                "messageType": "ExpressionActivationRequest",
                "data": {"expressionFile": exp_file, "active": True},
            }
            await self.vts.request(set_exp_request)
            print(f"DEBUG: Expresión '{exp_file}' activada directamente.")
            return True

        print(f"DEBUG: Expresiones disponibles: {nombres_exp}")
        return False

    async def close(self):
        if self.connected:
            await self.vts.close()


_vts_instance = None
_vts_lock = asyncio.Lock()


async def get_vts_instance():
    global _vts_instance
    # Lock para evitar dos conexiones en paralelo si llegan emociones casi simultáneas
    async with _vts_lock:
        if _vts_instance is None:
            instance = VTSController()
            await instance.connect()
            _vts_instance = instance
    return _vts_instance
