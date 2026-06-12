# 🤖 Estado del Proyecto - Mai-chan Bot

## 🚀 Funcionalidades Activas (No tocar/revertir)
- **Voz de Alta Calidad**: Se ha integrado **Edge TTS** para una voz natural, manteniendo la limpieza de emojis y símbolos (`src/utils.py`, `src/texttospeech_edge.py`).
- **Limpieza de Audio**: Se mantiene un máximo de **3 audios** en la carpeta raíz (limpieza rotativa en `src/generate_audio.py`).
- **Boca (Lipsync)**: El movimiento de la boca en VTube Studio ya funciona mediante la ruta de audio.
- **IA Local**: Uso de Ollama con temperatura 0.5 y formato JSON para emociones.
- **Expresiones VTS (Dual)**: Soporte para Hotkeys y activación directa de expresiones (.exp3.json) en `src/vts_controller.py`.

## ⚠️ Tareas Pendientes Prioritarias
- **Permisos VTS**: Si el bot no cambia de expresión, el usuario debe marcar "Allow Hotkey Triggering" en la configuración de Plugins de VTube Studio.
- **Launcher Visual**: Crear una interfaz sencilla para encender el bot sin usar comandos de consola.

## 📝 Reglas de Desarrollo
- Priorizar arquitectura local siempre que sea posible, pero usar Edge TTS para la voz por preferencia del usuario.
- No revertir la limpieza de emojis a menos que se pida explícitamente.
- Las respuestas del LLM deben seguir siendo en JSON para que el sistema de emociones funcione.
