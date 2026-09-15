# LiveCopilot ⚡

> **Copiloto de escritorio en tiempo real para Windows:** Escucha la salida de audio de tu PC (WASAPI Loopback), transcribe/traduce lo que dicen en vivo (reuniones, videollamadas, vídeos) y muestra sugerencias de respuesta inmediatas en un HUD flotante translúcido a 60 FPS.

---

## 🌟 Características Principales

1. **Captura Interna WASAPI Loopback (`soundcard`):**
   - Graba directamente lo que reproduce el altavoz de Windows a 16000 Hz mono (Float32).
   - Buffer no bloqueante en memoria con mitigación de acumulación de retardo.

2. **Detección de Actividad de Voz (VAD):**
   - Silero-VAD con red neuronal profunda + detector dinámico adaptativo RMS.
   - Pre-roll de audio para evitar el corte de consonantes iniciales.
   - Segmentación inteligente: solo despacha al transcriptor cuando detecta un silencio superior a 600 ms.

3. **Transcripción STT de Ultra-Baja Latencia (Dual Failover):**
   - **Primario (Cloud, <300ms):** Groq API con el modelo `whisper-large-v3` optimizado para traducir/transcribir al español.
   - **Fallback (Local):** `faster-whisper` (`base` / `small` con CUDA float16 o CPU int8).

4. **Copiloto Conversacional LLM:**
   - Groq (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`) o Google Gemini (`gemini-2.5-flash`).
   - Prompt estricto para generar 1 o 2 oraciones directas sin preámbulos.
   - Memoria deslizante de turnos recientes para entender el contexto de la reunión.

5. **HUD Flotante Minimalista (PyQt6):**
   - Ventana sin bordes, semi-transparente (`#121212` con opacidad del 88%) y siempre al frente.
   - Arrastrable desde cualquier punto de la cabecera.
   - **Bloque 1:** *"🎧 Escuchado (En vivo)"* en gris claro.
   - **Bloque 2:** *"💡 Sugerencia IA"* destacado en verde menta / cian con botón de copiado rápido.
   - Vúmetro de audio en tiempo real y métricas de latencia en milisegundos.
   - Control de pausa/reanudación y limpieza de contexto.

---

## 📁 Estructura del Proyecto

```
LiveCopilot/
├── src/
│   ├── __init__.py
│   ├── audio_capture.py    # Captura WASAPI Loopback en segundo plano
│   ├── vad_detector.py     # Silero-VAD y segmentación de habla (1800ms / flush manual)
│   ├── transcriber.py      # Transcriptor dual (Groq Whisper Cloud + faster-whisper)
│   ├── assistant.py        # Copiloto LLM con memoria conversacional y guía fonética
│   ├── settings_dialog.py  # Modal visual de configuración de audio, API Key y pausas
│   └── ui_overlay.py       # HUD flotante semi-transparente en PyQt6
├── .env.example            # Plantilla de variables de entorno y claves API
├── .gitignore              # Exclusiones seguras de git (ignora .env y venv/)
├── requirements.txt        # Dependencias de Python fijadas y probadas
├── main.py                 # Orquestador concurrente multihilo (QThread)
└── README.md               # Guía completa de uso y configuración
```

---

## 🚀 Guía de Instalación y Ejecución

### Prerrequisitos
- **Windows 10 u 11** (64 bits).
- **Python 3.10 o 3.11** instalado (Recomendado). Si no lo tienes instalado, instálalo en un segundo con:
  ```powershell
  winget install Python.Python.3.11
  ```

---

### Paso 1: Clonar / Abrir la carpeta en terminal

En **PowerShell** o **Símbolo del sistema (CMD)**:
```powershell
git clone https://github.com/Thekrownn/LiveCopilot.git
cd LiveCopilot
```

---

### Paso 2: Crear y activar el entorno virtual

#### En PowerShell:
```powershell
# 1. Crear el entorno virtual
python -m venv venv

# 2. Activar el entorno virtual
.\venv\Scripts\Activate.ps1
```

> *Nota:* Si PowerShell muestra un error de política de ejecución (`ExecutionPolicy`), ejecuta:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` y vuelve a activar.

#### En CMD:
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

---

### Paso 3: Instalar las dependencias

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

---

### Paso 4: Configurar tus claves API

Copia el archivo `.env.example` a `.env`:
```powershell
cp .env.example .env
```

Abre `.env` con el Bloc de notas o tu editor y añade tu API Key:
```env
# Clave gratuita de Groq (Recomendada para latencia ultra-baja <300ms)
# Consíguela gratis en: https://console.groq.com/keys
GROQ_API_KEY=gsk_tu_clave_aqui

# Clave de Gemini (Opcional, si usas Gemini como LLM)
# Consíguela en: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=tu_clave_gemini_aqui

STT_MODE=cloud
LLM_PROVIDER=groq
```

---

### Paso 5: Ejecutar LiveCopilot

```powershell
.\venv\Scripts\python.exe main.py
```

1. Verás aparecer el HUD flotante translúcido en la esquina inferior derecha de tu pantalla.
2. Reproduce cualquier video de YouTube, podcast, videollamada de Zoom, Google Meet o Teams.
3. El vúmetro superior reaccionará al sonido. Al terminar cada frase (>600 ms de pausa), aparecerá la transcripción en gris y la sugerencia de respuesta inmediata en verde menta.
4. Para mover la ventana, simplemente haz clic y arrastra desde la barra superior.
5. Puedes pausar temporalmente con el botón `⏸ Pausar` o cerrarla con `✕`.
