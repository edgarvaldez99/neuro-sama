"""
Script de diagnóstico para verificar la configuración del bot (stack local).

Comprueba que estén los archivos y variables necesarios y que los servicios
locales (Ollama y VTube Studio) estén accesibles antes de arrancar el bot.

Ejecutar desde la raíz del proyecto con:

    poetry run python -m src.check_setup
"""

import asyncio
import sys
from pathlib import Path

import requests
from decouple import config as environ  # type: ignore
from websockets import InvalidURI, WebSocketException, connect

# Servicios locales que el stack activo necesita.
OLLAMA_URL = "http://127.0.0.1:11434/api/tags"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_VTS_PORT = 8001


def check_file(filepath: str, required: bool = True) -> bool:
    """Verifica si un archivo existe."""
    if Path(filepath).exists():
        print(f"OK   {filepath} existe")
        return True
    status = "FALTA" if required else "AVISO"
    print(f"{status} {filepath} NO existe")
    return not required


def check_env_variable(var_name: str, required: bool = True) -> bool:
    """Verifica si una variable de entorno está configurada en .env."""
    value = str(environ(var_name, ""))
    if value:
        print(f"OK   {var_name} está configurado")
        return True
    status = "FALTA" if required else "AVISO"
    print(f"{status} {var_name} NO está configurado")
    return not required


def check_ollama() -> bool:
    """Comprueba que Ollama responda y tenga descargado el modelo configurado."""
    model = str(environ("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL))
    try:
        response = requests.get(OLLAMA_URL, timeout=5)
        response.raise_for_status()
        installed = [m.get("name", "") for m in response.json().get("models", [])]
    except requests.RequestException as exc:
        print(f"FALTA Ollama no responde en {OLLAMA_URL}: {exc}")
        print("      (Arrancá Ollama y descargá el modelo con: ollama pull <modelo>)")
        return False

    # Ollama lista los modelos con tag (p. ej. "qwen2.5:3b"); aceptamos coincidencia
    # exacta o por prefijo para tolerar el ":latest" implícito.
    if any(name == model or name.startswith(f"{model}:") for name in installed):
        print(f"OK   Ollama responde y el modelo '{model}' está descargado")
        return True

    print(f"FALTA Ollama responde pero el modelo '{model}' no está descargado")
    print(f"      Modelos disponibles: {installed or '(ninguno)'}")
    print(f"      Descargalo con: ollama pull {model}")
    return False


def check_vts() -> bool:
    """Intenta abrir el WebSocket de la API de VTube Studio."""
    port = int(environ("VTS_PORT", DEFAULT_VTS_PORT))
    uri = f"ws://localhost:{port}"

    async def test_connection() -> bool:
        try:
            async with connect(uri, open_timeout=3):
                print(f"OK   VTube Studio API accesible en {uri}")
                return True
        except (OSError, WebSocketException, InvalidURI, asyncio.TimeoutError) as exc:
            print(f"AVISO VTube Studio NO accesible en {uri}: {exc}")
            print("      (OK si no vas a usar avatar; activá la API en VTS si sí)")
            return False

    return asyncio.run(test_connection())


def main() -> None:
    """Corre todas las verificaciones e informa el resultado."""
    print("=" * 60)
    print("VERIFICACIÓN DE CONFIGURACIÓN DEL BOT (stack local)")
    print("=" * 60)
    print()

    issues = []

    print("Archivos requeridos...")
    if not check_file(".env"):
        issues.append("Archivo .env no existe. Copiá .env.example y configuralo")
    if not check_file("prompt_chat.txt"):
        issues.append("prompt_chat.txt no existe")
    if not check_file("filter.json"):
        issues.append("filter.json no existe")
    print()

    print("Variables de entorno...")
    if not check_env_variable("TWITCH_TOKEN"):
        issues.append("TWITCH_TOKEN no configurado")
    if not check_env_variable("TWITCH_CHANNEL"):
        issues.append("TWITCH_CHANNEL no configurado")
    check_env_variable("BOT_NAME", required=False)
    check_env_variable("OLLAMA_MODEL", required=False)
    check_env_variable("VTS_PORT", required=False)
    print()

    print("Servicio Ollama...")
    if not check_ollama():
        issues.append("Ollama no está listo (servicio o modelo)")
    print()

    print("Servicio VTube Studio (opcional)...")
    check_vts()
    print()

    print("=" * 60)
    if not issues:
        print("TODO CORRECTO. Arrancá el bot con: poetry run python main.py")
        print("=" * 60)
        return

    print("SE ENCONTRARON PROBLEMAS:")
    for i, issue in enumerate(issues, 1):
        print(f"   {i}. {issue}")
    print()
    print("Revisá SETUP.md para instrucciones detalladas")
    print("=" * 60)
    sys.exit(1)


if __name__ == "__main__":
    main()
