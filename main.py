"""
LiveCopilot - Punto de Entrada Principal y Orquestador de Concurrencia
Coordina la captura WASAPI Loopback, el motor VAD, la transcripción STT (Groq/Whisper)
y la generación LLM en hilos de trabajo desacoplados (QThread) garantizando
60 FPS fluidos en la interfaz gráfica de PyQt6.
"""

import logging
import os
import signal
import sys
from typing import Optional

from dotenv import load_dotenv
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

# Configurar logging con formato legible y marcas de tiempo
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LiveCopilot.Main")

# Configurar AppUserModelID para integración completa con la barra de tareas de Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("livecopilot.ai.hud.v1")
    except Exception:
        pass

# Importación de módulos del sistema
from src.vad_detector import VADDetector
from src.transcriber import TranscriberEngine
from src.assistant import LiveAssistant
from src.ui_overlay import FloatingHUD, get_app_icon
from src.settings_dialog import SettingsDialog


class LivePipelineWorker(QThread):
    """
    Hilo de trabajo dedicado que procesa el flujo de audio en tiempo real,
    evalúa la actividad vocal (VAD), despacha la transcripción y consulta
    al asistente conversacional sin congelar la interfaz.
    """

    # Señales Qt hacia el hilo principal de la UI
    sig_transcription = pyqtSignal(str, float, str)     # texto, latencia_ms, motor
    sig_suggestion = pyqtSignal(object, float, str)    # diccionario con fonética/traducción, latencia_ms, proveedor
    sig_audio_level = pyqtSignal(float)                # nivel RMS (0.0 a 1.0)
    sig_status = pyqtSignal(str, str)                  # mensaje_estado, tipo_estado ('active', 'processing', etc.)
    sig_error = pyqtSignal(str)                        # mensaje de error

    def __init__(self):
        super().__init__()
        self._is_running = True
        self._is_paused = False
        self._request_flush_and_pause = False

        # Parámetros desde variables de entorno
        self.stt_mode = os.getenv("STT_MODE", "cloud").strip().lower()
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.llm_provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
        self.target_lang = os.getenv("TARGET_LANGUAGE", "es").strip()

        vad_timeout = int(os.getenv("VAD_SILENCE_TIMEOUT_MS", "1800"))
        vad_threshold = float(os.getenv("VAD_THRESHOLD", "0.4"))
        min_speech_sec = float(os.getenv("MIN_SPEECH_DURATION_SEC", "0.6"))

        local_model_size = os.getenv("LOCAL_WHISPER_MODEL", "base").strip()
        local_device = os.getenv("LOCAL_DEVICE", "cpu").strip()
        local_compute = os.getenv("LOCAL_COMPUTE_TYPE", "int8").strip()
        audio_device_id = os.getenv("AUDIO_DEVICE_ID", "").strip() or None

        # 1. Inicialización de AudioCapture con callback para el vúmetro
        from src.audio_capture import AudioCapture
        self.audio_capture = AudioCapture(
            sample_rate=16000,
            block_size=512,
            device_id=audio_device_id,
            on_audio_level=self._handle_audio_level,
        )

        # 2. Detector VAD (Silero + RMS adaptativo)
        self.vad_detector = VADDetector(
            sample_rate=16000,
            silence_timeout_ms=vad_timeout,
            vad_threshold=vad_threshold,
            min_speech_duration_sec=min_speech_sec,
        )

        # 3. Motor STT con conmutación inteligente
        self.transcriber = TranscriberEngine(
            stt_mode=self.stt_mode,
            groq_api_key=self.groq_api_key,
            fallback_to_local=True,
            local_model_size=local_model_size,
            local_device=local_device,
            local_compute_type=local_compute,
            target_language=self.target_lang,
        )

        # 4. Copiloto LLM en vivo
        self.assistant = LiveAssistant(
            provider=self.llm_provider,
            groq_api_key=self.groq_api_key,
            gemini_api_key=self.gemini_api_key,
        )

    def _handle_audio_level(self, level: float):
        """Reenvía la señal de nivel de audio al hilo de la UI si no está pausado."""
        if not self._is_paused and self._is_running:
            self.sig_audio_level.emit(level)

    def run(self):
        """Bucle continuo de ingestión, segmentación y despacho."""
        logger.info("Pipeline de procesamiento de audio en vivo iniciado.")
        self.audio_capture.start()
        self.sig_status.emit("Escuchando...", "active")

        while self._is_running:
            # Si el usuario pausó, tomar inmediatamente lo que se haya escuchado hasta ese momento
            if self._request_flush_and_pause:
                self._request_flush_and_pause = False
                self.audio_capture.pause()

                # Drenar los últimos bloques que queden en la cola de audio
                while True:
                    remaining_chunk = self.audio_capture.get_chunk(timeout=0.01)
                    if remaining_chunk is None:
                        break
                    self.vad_detector.process_chunk(remaining_chunk)

                # Tomar todo lo escuchado hasta el momento de presionar Pausa
                speech_segment = self.vad_detector.flush()
                self._is_paused = True
                self.sig_audio_level.emit(0.0)

                if speech_segment is not None:
                    logger.info("Pausado: Procesando lo escuchado hasta el momento...")
                    self._process_completed_segment(speech_segment)

                self.sig_status.emit("Pausado", "paused")
                continue

            if self._is_paused:
                self.msleep(60)
                continue

            # Obtener bloque de audio de 512 muestras (32 ms)
            chunk = self.audio_capture.get_chunk(timeout=0.1)
            if chunk is None:
                continue

            # Procesamiento VAD
            try:
                speech_segment, is_speaking, _ = self.vad_detector.process_chunk(chunk)
            except Exception as e:
                logger.error("Error en procesamiento VAD: %s", e)
                continue

            # Si el VAD detecta que la persona terminó de hablar (silencio completado)
            if speech_segment is not None:
                self._process_completed_segment(speech_segment)

        # Limpieza al detener
        self.audio_capture.stop()
        logger.info("Pipeline de audio finalizado.")

    def _process_completed_segment(self, audio_segment):
        """
        Ejecuta la transcripción STT y de inmediato consulta la sugerencia al LLM.
        """
        self.sig_status.emit("Transcribiendo...", "processing")
        try:
            # 1. Transcripción / Traducción
            text, stt_latency, engine = self.transcriber.transcribe(audio_segment)

            if not text or len(text.strip()) < 2:
                self.sig_status.emit("Escuchando...", "active")
                return

            logger.info("Transcrito [%s | %.1f ms]: %s", engine, stt_latency, text)
            self.sig_transcription.emit(text, stt_latency, engine)

            # 2. Generación de Sugerencia con LLM
            self.sig_status.emit("Generando sugerencia...", "processing")
            sug_data, llm_latency, provider = self.assistant.get_suggestion(text)

            if sug_data:
                preview = sug_data.get("respuesta", "") if isinstance(sug_data, dict) else str(sug_data)
                logger.info("Sugerencia [%s | %.1f ms]: %s", provider, llm_latency, preview)
                self.sig_suggestion.emit(sug_data, llm_latency, provider)

            self.sig_status.emit("Escuchando...", "active")

        except Exception as e:
            logger.error("Error al procesar el segmento de audio: %s", e, exc_info=True)
            self.sig_status.emit("Error de procesamiento", "error")

    def toggle_pause(self):
        """Pausa o reanuda el procesamiento de audio."""
        if not self._is_paused:
            logger.info("Solicitud de pausa recibida: extrayendo audio escuchado hasta ahora...")
            self._request_flush_and_pause = True
        else:
            self._is_paused = False
            self.audio_capture.resume()
            self.sig_status.emit("Escuchando...", "active")
            logger.info("Pipeline reanudado por el usuario.")

    def update_config(self, config: dict):
        """Aplica la nueva configuración sin reiniciar la aplicación."""
        if "groq_api_key" in config and config["groq_api_key"]:
            self.groq_api_key = config["groq_api_key"]
            self.transcriber.groq_api_key = self.groq_api_key
            self.transcriber._init_groq()
            self.assistant.groq_api_key = self.groq_api_key
            self.assistant._init_providers()

        if "device_id" in config:
            self.audio_capture.set_device(config["device_id"])

        if "target_language" in config:
            self.target_lang = config["target_language"]
            self.transcriber.target_language = self.target_lang

        if "vad_silence_timeout_ms" in config:
            self.vad_detector.silence_timeout_ms = int(config["vad_silence_timeout_ms"])
            logger.info("VAD silence timeout actualizado a %s ms", config["vad_silence_timeout_ms"])

        logger.info("Configuración del pipeline actualizada en tiempo real.")

    def clear_history(self):
        """Limpia el buffer conversacional del asistente."""
        self.assistant.clear_history()
        self.vad_detector.reset()

    def stop(self):
        """Detiene el hilo de trabajo de forma segura."""
        self._is_running = False
        self.wait(1500)


def get_env_path() -> str:
    """Retorna la ruta al archivo .env tanto en modo script como congelado (.exe)."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, ".env")


def main():
    """Función principal de inicio de la aplicación."""
    # Cargar variables de entorno desde archivo .env local si existe
    env_path = get_env_path()
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        # Intentar cargar .env.example si .env no fue creado aún
        app_dir = os.path.dirname(env_path)
        example_env = os.path.join(app_dir, ".env.example")
        if os.path.exists(example_env):
            load_dotenv(example_env)

    # Inicializar aplicación PyQt6 en el hilo principal
    app = QApplication(sys.argv)
    app.setApplicationName("LiveCopilot")
    app.setWindowIcon(get_app_icon())

    # Permitir interrupción limpia con Ctrl+C en consola
    signal.signal(signal.SIGINT, lambda *args: app.quit())

    # Comprobar si es la primera ejecución (sin clave válida de Groq)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    is_first_run = (not groq_key or groq_key.startswith("PEGA_AQUI") or not groq_key.startswith("gsk_"))

    if is_first_run:
        logger.info("Primera ejecución detectada. Abriendo asistente de bienvenida y configuración...")
        welcome_dlg = SettingsDialog(is_first_run=True)
        if welcome_dlg.exec() != SettingsDialog.DialogCode.Accepted:
            logger.info("Configuración cancelada por el usuario. Saliendo...")
            sys.exit(0)
        # Recargar variables tras guardar
        load_dotenv(env_path, override=True)

    # Crear ventana HUD flotante
    hud = FloatingHUD()

    # Iniciar hilo de procesamiento desacoplado
    pipeline_worker = LivePipelineWorker()

    # Conectar señales del worker hacia la interfaz
    pipeline_worker.sig_transcription.connect(hud.update_transcription)
    pipeline_worker.sig_suggestion.connect(hud.update_suggestion)
    pipeline_worker.sig_audio_level.connect(hud.update_audio_level)
    pipeline_worker.sig_status.connect(hud.set_status)

    # Conectar controles de la interfaz hacia el worker
    hud.request_toggle_pause.connect(pipeline_worker.toggle_pause)
    hud.request_clear.connect(pipeline_worker.clear_history)

    # Conectar botón de ajustes ⚙️ del HUD
    def open_settings_modal():
        dlg = SettingsDialog(hud, is_first_run=False)
        dlg.settings_saved.connect(pipeline_worker.update_config)
        dlg.exec()

    hud.request_open_settings.connect(open_settings_modal)

    # Limpieza al cerrar la aplicación
    def on_exit():
        logger.info("Cerrando LiveCopilot...")
        pipeline_worker.stop()

    app.aboutToQuit.connect(on_exit)

    # Iniciar pipeline y mostrar HUD
    pipeline_worker.start()
    hud.show()

    logger.info("LiveCopilot HUD listo en pantalla. Presiona Ctrl+C en terminal o el botón ✕ para cerrar.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
