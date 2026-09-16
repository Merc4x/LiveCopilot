"""
LiveCopilot - Ultra-Low Latency STT Transcription & Translation Engine
Dual-mode support with automatic failover:
  - Primary (Cloud, <300ms): Groq API with Whisper-large-v3.
  - Fallback (Local): faster-whisper with CTranslate2 acceleration (CUDA/CPU).
"""

import io
import logging
import os
import time
import wave
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger("LiveCopilot.Transcriber")


class TranscriberEngine:
    """
    Speech-to-text transcription and translation engine with cloud-local redundancy.
    Ensures minimal latency and uninterrupted operation even during connectivity drops.
    """

    def __init__(
        self,
        stt_mode: str = "cloud",
        groq_api_key: Optional[str] = None,
        fallback_to_local: bool = True,
        local_model_size: str = "base",
        local_device: str = "cpu",
        local_compute_type: str = "int8",
        target_language: str = "es",
    ):
        """
        :param stt_mode: 'cloud' or 'local'.
        :param groq_api_key: Groq Cloud API key.
        :param fallback_to_local: Automatically switch to local engine if cloud request fails.
        :param local_model_size: faster-whisper model size ('tiny', 'base', 'small').
        :param local_device: 'cuda' or 'cpu'.
        :param local_compute_type: 'float16' for CUDA GPU, 'int8' for CPU.
        :param target_language: Target ISO language code ('es', 'en', etc.).
        """
        self.stt_mode = stt_mode.lower().strip()
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.fallback_to_local = fallback_to_local
        self.local_model_size = local_model_size
        self.local_device = local_device
        self.local_compute_type = local_compute_type
        self.target_language = target_language

        # Groq client
        self.groq_client = None
        if self.groq_api_key:
            self._init_groq()

        # Local faster-whisper model (lazy-loaded for instant startup)
        self.local_model = None

    def _init_groq(self):
        """Initialize the Groq API client."""
        try:
            from groq import Groq
            self.groq_client = Groq(api_key=self.groq_api_key, timeout=4.0)
            logger.info("Groq API client initialized successfully.")
        except Exception as e:
            logger.warning("Failed to initialize Groq client: %s", e)
            self.groq_client = None

    def _init_local_whisper(self) -> bool:
        """Load faster-whisper model on demand into memory."""
        if self.local_model is not None:
            return True

        try:
            from faster_whisper import WhisperModel
            import torch

            device = self.local_device
            compute_type = self.local_compute_type

            # Automatic fallback if CUDA is requested but unavailable
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA is not available on this system. Falling back to CPU.")
                device = "cpu"
                compute_type = "int8"

            logger.info(
                "Loading local faster-whisper (Model: %s, Device: %s, Compute: %s)...",
                self.local_model_size,
                device,
                compute_type,
            )
            self.local_model = WhisperModel(
                self.local_model_size,
                device=device,
                compute_type=compute_type,
                cpu_threads=4,
            )
            logger.info("Local faster-whisper model ready.")
            return True
        except Exception as e:
            logger.error("Error loading local faster-whisper: %s", e)
            return False

    @staticmethod
    def _float32_to_wav_bytes(audio_array: np.ndarray, sample_rate: int = 16000) -> bytes:
        """
        Convert a float32 audio array to in-memory WAV bytes without disk I/O.
        """
        # Normalize and convert to 16-bit signed integers (PCM16)
        clamped = np.clip(audio_array, -1.0, 1.0)
        pcm16 = (clamped * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())

        buf.seek(0)
        return buf.getvalue()

    def _transcribe_groq(self, audio_array: np.ndarray) -> str:
        """Transcribe audio using Groq Whisper Cloud."""
        if not self.groq_client:
            raise RuntimeError("Groq client not configured or API Key is missing.")

        wav_bytes = self._float32_to_wav_bytes(audio_array)
        file_payload = ("audio_stream.wav", wav_bytes, "audio/wav")

        kwargs = {
            "file": file_payload,
            "model": "whisper-large-v3",
            "response_format": "json",
            "temperature": 0.0,
        }
        if self.target_language and self.target_language.lower() not in ("auto", "none", ""):
            kwargs["language"] = self.target_language

        response = self.groq_client.audio.transcriptions.create(**kwargs)
        return response.text.strip()

    def _transcribe_local(self, audio_array: np.ndarray) -> str:
        """Transcribe audio using local faster-whisper."""
        if not self._init_local_whisper() or self.local_model is None:
            raise RuntimeError("faster-whisper model is not available.")

        # faster-whisper directly accepts normalized float32 numpy arrays
        segments, _ = self.local_model.transcribe(
            audio_array,
            language=self.target_language,
            beam_size=2,
            vad_filter=False,  # Audio is already pre-filtered by Silero VAD
            temperature=0.0,
        )
        text_parts = [segment.text.strip() for segment in segments]
        return " ".join(text_parts).strip()

    def transcribe(self, audio_array: np.ndarray) -> Tuple[str, float, str]:
        """
        Transcribe an audio chunk with automatic failover.
        :param audio_array: 1D float32 array sampled at 16000Hz.
        :return: Tuple:
            - text: Transcribed text.
            - latency_ms: Inference time in milliseconds.
            - engine: 'Groq Cloud' or 'Local Whisper'.
        """
        t_start = time.perf_counter()
        engine_used = "Unknown"
        text = ""

        # Primary attempt: Groq Cloud
        if self.stt_mode == "cloud" and self.groq_client is not None:
            try:
                text = self._transcribe_groq(audio_array)
                engine_used = "Groq Cloud (<300ms)"
            except Exception as e:
                logger.warning("Groq Cloud transcription failed: %s", e)
                if self.fallback_to_local:
                    logger.info("Triggering automatic failover to local faster-whisper...")
                    try:
                        text = self._transcribe_local(audio_array)
                        engine_used = "Local Whisper (Fallback)"
                    except Exception as local_err:
                        logger.error("Both Cloud and Local transcription failed: %s", local_err)
                        text = ""
                else:
                    text = ""
        else:
            # Enforced local mode or missing Groq credentials
            try:
                text = self._transcribe_local(audio_array)
                engine_used = "Local Whisper"
            except Exception as e:
                logger.error("Local transcription error: %s", e)
                text = ""

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        return text, latency_ms, engine_used
