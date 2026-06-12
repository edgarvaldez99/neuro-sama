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
            print("DEBUG: Conexión establecida con VTube Studio. Autenticando...")
            await self.vts.request_authenticate_token()
            await self.vts.request_authenticate()
            await asyncio.sleep(2.0)  # Aumentamos pausa para asegurar sesión
            self.connected = True
            print("DEBUG: Autenticación completada.")

            # Validar modelo cargado usando el constructor de pyvts
            model_request = self.vts.vts_request.requestCurrentModel()
            model_data = await self.vts.request(model_request)
            
            model_loaded = model_data.get("data", {}).get("modelLoaded", False)
            if not model_loaded:
                print("DEBUG: [AVISO] No hay ningún modelo cargado en VTube Studio.")
            else:
                model_name = model_data.get("data", {}).get("modelName", "Desconocido")
                print(f"DEBUG: Modelo detectado: {model_name}")

        except Exception as e:
            print(f"DEBUG: Error al conectar/autenticar con VTube Studio: {e}")
            self.connected = False

    async def trigger_hotkey(self, hotkey_name: str):
        if not self.connected:
            await self.connect()

        if self.connected:
            try:
                # 1. Intentar por Hotkey primero (método tradicional)
                list_request = self.vts.vts_request.requestHotkeysInCurrentModel()
                hotkeys_data = await self.vts.request(list_request)
                hotkey_list = hotkeys_data.get("data", {}).get("availableHotkeys", [])

                hotkey_id = None
                for hk in hotkey_list:
                    if hk.get("name", "").strip().lower() == hotkey_name.strip().lower():
                        hotkey_id = hk["hotkeyID"]
                        break

                if hotkey_id:
                    trigger_request = self.vts.vts_request.requestTriggerHotkey(hotkey_id)
                    await self.vts.request(trigger_request)
                    print(f"DEBUG: Hotkey '{hotkey_name}' activado.")
                    return

                # 2. Si no hay hotkey, intentar activar expresión directamente
                # A veces el usuario tiene archivos .exp3.json pero no creó hotkeys
                print(f"DEBUG: Hotkey '{hotkey_name}' no encontrado. Buscando expresión...")
                
                exp_request = {
                    "apiName": "VTubeStudioPublicAPI",
                    "apiVersion": "1.0",
                    "requestID": "ExpressionStateRequest",
                    "messageType": "ExpressionStateRequest"
                }
                exp_data = await self.vts.request(exp_request)
                expressions = exp_data.get("data", {}).get("expressions", [])
                
                exp_file = None
                nombres_exp = []
                for exp in expressions:
                    name = exp.get("name", "")
                    file = exp.get("file", "")
                    nombres_exp.append(name)
                    # Comparar con nombre o nombre de archivo (sin extensión)
                    if (name.lower() == hotkey_name.lower() or 
                        file.lower().replace(".exp3.json", "") == hotkey_name.lower() or
                        name.lower().replace("ex_", "") == hotkey_name.lower().replace("ex_", "")):
                        exp_file = file
                        break
                
                if exp_file:
                    set_exp_request = {
                        "apiName": "VTubeStudioPublicAPI",
                        "apiVersion": "1.0",
                        "requestID": "ExpressionActivationRequest",
                        "messageType": "ExpressionActivationRequest",
                        "data": {
                            "expressionFile": exp_file,
                            "active": True
                        }
                    }
                    await self.vts.request(set_exp_request)
                    print(f"DEBUG: Expresión '{exp_file}' activada directamente.")
                else:
                    print(f"DEBUG: Tampoco se encontró expresión para '{hotkey_name}'.")
                    print(f"DEBUG: Expresiones disponibles: {nombres_exp}")
                    if not hotkey_list and not expressions:
                        print("DEBUG: [ERROR] El modelo no tiene ni Hotkeys ni Expresiones cargadas.")

            except Exception as e:
                print(f"DEBUG: Excepción en trigger_hotkey: {e}")

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
