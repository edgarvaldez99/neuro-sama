import asyncio

import pyvts  # type: ignore


class VTSController:
    def __init__(self):
        self.plugin_info = {
            "plugin_name": "Mai-chan Bot",
            "developer": "TavaTeam",
            "authentication_token_path": "./vts_token.txt",
        }
        self.vts = pyvts.vts(plugin_info=self.plugin_info)
        self.connected = False

    async def connect(self):
        try:
            await self.vts.connect()
            await self.vts.request_authenticate_token()
            await self.vts.request_authenticate()
            await asyncio.sleep(1.0)  # Pausa para asegurar sesión en VTS
            self.connected = True
            print("DEBUG: Conectado y autenticado en VTube Studio.")

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
                print("DEBUG: AVISO - No hay ningún modelo cargado en VTube Studio.")
            else:
                model_name = model_data.get("data", {}).get("modelName", "Desconocido")
                print(f"DEBUG: Modelo detectado: {model_name}")

        except Exception as e:
            print(f"DEBUG: Error al conectar con VTube Studio: {e}")
            self.connected = False

    async def trigger_hotkey(self, hotkey_name: str):
        if not self.connected:
            await self.connect()

        if self.connected:
            try:
                # Según el manual oficial de VTS: HotkeysInCurrentModelRequest
                list_request = {
                    "apiName": "VTubeStudioPublicAPI",
                    "apiVersion": "1.0",
                    "requestID": "HotkeysInCurrentModelRequest",
                    "messageType": "HotkeysInCurrentModelRequest",
                }

                hotkeys_data = await self.vts.request(list_request)
                hotkey_list = hotkeys_data.get("data", {}).get("availableHotkeys", [])

                hotkey_id = None
                for hk in hotkey_list:
                    # Buscamos por nombre exacto (insensible a espacios)
                    if (
                        hk.get("name", "").strip().lower()
                        == hotkey_name.strip().lower()
                    ):
                        hotkey_id = hk["hotkeyID"]
                        break

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
                else:
                    disponibles = [
                        hk.get("name") for hk in hotkey_list if hk.get("name")
                    ]
                    print(f"DEBUG: Hotkey '{hotkey_name}' no encontrado.")
                    if not hotkey_list:
                        print(
                            "DEBUG: Lista de Hotkeys VACÍA. "
                            "Verifica modelo cargado y VTS enfocado."
                        )
                    else:
                        print(f"DEBUG: Hotkeys encontrados en VTS: {disponibles}")
            except Exception as e:
                print(f"DEBUG: Error al activar hotkey: {e}")

    async def close(self):
        if self.connected:
            await self.vts.close()


EMOTION_TO_HOTKEY = {
    "happy": "Ex_Happy",
    "sad": "Ex_Sad",
    "angry": "Ex_Angry",
    "surprised": "Ex_Surprised",
    "neutral": "Ex_Neutral",
}

_vts_instance = None


async def get_vts_instance():
    global _vts_instance
    if _vts_instance is None:
        _vts_instance = VTSController()
        await _vts_instance.connect()
    return _vts_instance
