# 🤖 Estado del Proyecto - Mai-chan Bot

## 🚀 Funcionalidades Activas (No tocar/revertir)
- **Voz Limpia**: Mai-chan NO debe leer emojis ni símbolos (implementado en `src/utils.py` y `src/texttospeech_piper.py`).
- **Limpieza de Audio**: Se mantiene un máximo de **3 audios** en la carpeta raíz (limpieza rotativa en `src/generate_audio.py`).
- **Boca (Lipsync)**: El movimiento de la boca en VTube Studio ya funciona mediante la ruta de audio.
- **IA Local**: Uso de Ollama con temperatura 0.5 y formato JSON para emociones.

## ⚠️ Tareas Pendientes Prioritarias
- **Expresiones VTS**: El bot se conecta pero los ojos y la cara no cambian porque la lista de hotkeys regresa vacía `[]`.
- **Permisos VTS**: Es necesario forzar o verificar el permiso de "máscara/carita" (expresiones) en la lista de plugins de VTube Studio v1.35.7.
- **Launcher Visual**: Crear una interfaz sencilla para encender el bot sin usar comandos de consola.

## 📝 Reglas de Desarrollo
- Mantener siempre la arquitectura 100% local (Ollama + Piper).
- No revertir la limpieza de emojis a menos que se pida explícitamente.
- Las respuestas del LLM deben seguir siendo en JSON para que el sistema de emociones funcione.
