"""
LiveCopilot - Main Application Entry Point & Concurrency Orchestrator
Coordinates WASAPI Loopback capture, VAD voice activity detection, STT transcription (Groq/Whisper),
and LLM response generation across decoupled worker threads (QThread) to ensure
a silky-smooth 60 FPS floating HUD interface in PyQt6.
"""

import logging
import os
import signal
import sys
from typing import Optional

from dotenv import load_dotenv
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

# Configure structured logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LiveCopilot.Main")

# Set explicit AppUserModelID for proper Windows taskbar grouping and branding
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("livecopilot.ai.hud.v1")
    except Exception:
        pass

# Import core modules
from src.vad_detector import VADDetector
from src.transcriber import TranscriberEngine
from src.assistant import LiveAssistant
from src.ui_overlay import FloatingHUD, get_app_icon
from src.settings_dialog import SettingsDialog


class LivePipelineWorker(QThread):
    """
    Dedicated worker thread that consumes the real-time audio stream,
    evaluates voice activity (VAD), dispatches transcription (STT),
    and queries the conversational co-pilot without blocking the GUI.
    """

    # Qt signals to the main UI thread
    sig_transcription = pyqtSignal(str, float, str)     # text, latency_ms, engine
    sig_suggestion = pyqtSignal(object, float, str)    # structured dict (response, phonetics, translation), latency_ms, provider
    sig_audio_level = pyqtSignal(float)                # RMS level (0.0 to 1.0)
    sig_status = pyqtSignal(str, str)                  # status_text, state_type ('active', 'processing', etc.)
    sig_error = pyqtSignal(str)                        # error message

    def __init__(self):
        super().__init__()
        self._is_running = True
        self._is_paused = False
        self._request_flush_and_pause = False

        # Load environment configuration
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

        # 1. Initialize AudioCapture with volume meter callback
        from src.audio_capture import AudioCapture
        self.audio_capture = AudioCapture(
            sample_rate=16000,
            block_size=512,
            device_id=audio_device_id,
            on_audio_level=self._handle_audio_level,
        )

        # 2. VAD Voice Activity Detector (Silero + adaptive energy gating)
        self.vad_detector = VADDetector(
            sample_rate=16000,
            silence_timeout_ms=vad_timeout,
            vad_threshold=vad_threshold,
            min_speech_duration_sec=min_speech_sec,
        )

        # 3. Speech-to-Text Engine with automatic cloud/local failover
        self.transcriber = TranscriberEngine(
            stt_mode=self.stt_mode,
            groq_api_key=self.groq_api_key,
            fallback_to_local=True,
            local_model_size=local_model_size,
            local_device=local_device,
            local_compute_type=local_compute,
            target_language=self.target_lang,
        )

        # 4. Conversational Assistant Engine (Groq / Gemini)
        self.assistant = LiveAssistant(
            provider=self.llm_provider,
            groq_api_key=self.groq_api_key,
            gemini_api_key=self.gemini_api_key,
        )

    def _handle_audio_level(self, level: float):
        """Emit audio RMS level to UI thread when listening is active."""
        if not self._is_paused and self._is_running:
            self.sig_audio_level.emit(level)

    def run(self):
        """Continuous pipeline loop for ingestion, VAD segmentation, and dispatch."""
        logger.info("Real-time live audio pipeline worker started.")
        self.audio_capture.start()
        self.sig_status.emit("Listening...", "active")

        while self._is_running:
            # When user pauses, immediately flush and process audio captured up to that point
            if self._request_flush_and_pause:
                self._request_flush_and_pause = False
                self.audio_capture.pause()

                # Drain remaining audio blocks from queue
                while True:
                    remaining_chunk = self.audio_capture.get_chunk(timeout=0.01)
                    if remaining_chunk is None:
                        break
                    self.vad_detector.process_chunk(remaining_chunk)

                # Flush speech up to the exact pause moment
                speech_segment = self.vad_detector.flush()
                self._is_paused = True
                self.sig_audio_level.emit(0.0)

                if speech_segment is not None:
                    logger.info("Paused: Processing audio captured up to pause point...")
                    self._process_completed_segment(speech_segment)

                self.sig_status.emit("Paused", "paused")
                continue

            if self._is_paused:
                self.msleep(60)
                continue

            # Read 512-sample audio chunk (32ms at 16kHz)
            chunk = self.audio_capture.get_chunk(timeout=0.1)
            if chunk is None:
                continue

            # VAD segmentation
            try:
                speech_segment, is_speaking, _ = self.vad_detector.process_chunk(chunk)
            except Exception as e:
                logger.error("VAD processing error: %s", e)
                continue

            # If silence timeout triggered a completed speech segment
            if speech_segment is not None:
                self._process_completed_segment(speech_segment)

        # Cleanup on stop
        self.audio_capture.stop()
        logger.info("Live audio pipeline worker stopped.")

    def _process_completed_segment(self, audio_segment):
        """
        Execute STT transcription and immediately request response suggestion from LLM.
        """
        self.sig_status.emit("Transcribing...", "processing")
        try:
            # 1. Speech-to-Text Transcription
            text, stt_latency, engine = self.transcriber.transcribe(audio_segment)

            if not text or len(text.strip()) < 2:
                self.sig_status.emit("Listening...", "active")
                return

            logger.info("Transcribed [%s | %.1f ms]: %s", engine, stt_latency, text)
            self.sig_transcription.emit(text, stt_latency, engine)

            # 2. Conversational LLM Suggestion
            self.sig_status.emit("Generating suggestion...", "processing")
            sug_data, llm_latency, provider = self.assistant.get_suggestion(text)

            if sug_data:
                preview = (
                    (sug_data.get("response") or sug_data.get("respuesta", ""))
                    if isinstance(sug_data, dict)
                    else str(sug_data)
                )
                logger.info("Suggestion [%s | %.1f ms]: %s", provider, llm_latency, preview)
                self.sig_suggestion.emit(sug_data, llm_latency, provider)

            self.sig_status.emit("Listening...", "active")

        except Exception as e:
            logger.error("Error processing audio speech segment: %s", e, exc_info=True)
            self.sig_status.emit("Processing error", "error")

    def toggle_pause(self):
        """Toggle pause state for audio listening."""
        if not self._is_paused:
            logger.info("Pause request received: flushing audio buffer...")
            self._request_flush_and_pause = True
        else:
            self._is_paused = False
            self.audio_capture.resume()
            self.sig_status.emit("Listening...", "active")
            logger.info("Audio pipeline resumed by user.")

    def update_config(self, config: dict):
        """Apply dynamic configuration changes without restarting the app."""
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
            logger.info("VAD silence timeout updated to %s ms", config["vad_silence_timeout_ms"])

        logger.info("Pipeline configuration updated in real-time.")

    def clear_history(self):
        """Clear conversational context buffer and reset VAD state."""
        self.assistant.clear_history()
        self.vad_detector.reset()

    def stop(self):
        """Gracefully terminate worker thread."""
        self._is_running = False
        self.wait(1500)


def get_env_path() -> str:
    """Return the path to the .env file in both source and frozen executable modes."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, ".env")


def main():
    """Main application entry point."""
    # Load environment variables from .env if present
    env_path = get_env_path()
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        # Fallback to .env.example if .env has not been created yet
        app_dir = os.path.dirname(env_path)
        example_env = os.path.join(app_dir, ".env.example")
        if os.path.exists(example_env):
            load_dotenv(example_env)

    # Initialize PyQt6 application on main GUI thread
    app = QApplication(sys.argv)
    app.setApplicationName("LiveCopilot")
    app.setWindowIcon(get_app_icon())

    # Enable clean terminal exit with Ctrl+C
    signal.signal(signal.SIGINT, lambda *args: app.quit())

    # Check for first-time run (no valid Groq API key configured)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    is_first_run = (
        not groq_key
        or groq_key.startswith("PEGA_AQUI")
        or groq_key.startswith("PASTE_YOUR")
        or not groq_key.startswith("gsk_")
    )

    if is_first_run:
        logger.info("First run detected. Launching setup wizard...")
        welcome_dlg = SettingsDialog(is_first_run=True)
        if welcome_dlg.exec() != SettingsDialog.DialogCode.Accepted:
            logger.info("Setup wizard dismissed by user. Exiting...")
            sys.exit(0)
        # Reload environment variables after saving
        load_dotenv(env_path, override=True)

    # Create minimalist floating HUD window
    hud = FloatingHUD()

    # Initialize background worker thread
    pipeline_worker = LivePipelineWorker()

    # Connect worker signals to UI
    pipeline_worker.sig_transcription.connect(hud.update_transcription)
    pipeline_worker.sig_suggestion.connect(hud.update_suggestion)
    pipeline_worker.sig_audio_level.connect(hud.update_audio_level)
    pipeline_worker.sig_status.connect(hud.set_status)

    # Connect HUD UI actions to worker
    hud.request_toggle_pause.connect(pipeline_worker.toggle_pause)
    hud.request_clear.connect(pipeline_worker.clear_history)

    # Connect settings button ⚙️
    def open_settings_modal():
        dlg = SettingsDialog(hud, is_first_run=False)
        dlg.settings_saved.connect(pipeline_worker.update_config)
        dlg.exec()

    hud.request_open_settings.connect(open_settings_modal)

    # Clean shutdown on application quit
    def on_exit():
        logger.info("Shutting down LiveCopilot...")
        pipeline_worker.stop()

    app.aboutToQuit.connect(on_exit)

    # Launch pipeline worker and display HUD
    pipeline_worker.start()
    hud.show()

    logger.info("LiveCopilot HUD ready. Press Ctrl+C in terminal or click ✕ to exit.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
