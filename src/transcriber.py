"""
LiveCopilot - Motor de Transcripción y Traducción STT de Ultra-Baja Latencia
Soporte dual con conmutación automática:
  - Primario (Nube, <300ms): Groq API con Whisper-large-v3.
  - Fallback (Local): faster-whisper con aceleración CTranslate2 (CUDA/CPU).
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
    Motor de transcripción/traducción de voz a texto con redundancia nube-local.
    Garantiza latencia mínima y funcionamiento continuo incluso sin internet.
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
        :param stt_mode: 'cloud' o 'local'.
        :param groq_api_key: Clave API de Groq Cloud.
        :param fallback_to_local: Conmutar a local automáticamente si la nube falla.
        :param local_model_size: Tamaño del modelo faster-whisper ('tiny', 'base', 'small').
        :param local_device: 'cuda' o 'cpu'.
        :param local_compute_type: 'float16' para GPU CUDA, 'int8' para CPU.
        :param target_language: Idioma objetivo ('es' para español).
        """
        self.stt_mode = stt_mode.lower().strip()
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.fallback_to_local = fallback_to_local
        self.local_model_size = local_model_size
        self.local_device = local_device
        self.local_compute_type = local_compute_type
        self.target_language = target_language

        # Cliente Groq
        self.groq_client = None
        if self.groq_api_key:
            self._init_groq()

        # Modelo local faster-whisper (Carga perezosa para inicio instantáneo)
        self.local_model = None

    def _init_groq(self):
        """Inicializa el cliente de Groq API."""
        try:
            from groq import Groq
            self.groq_client = Groq(api_key=self.groq_api_key, timeout=4.0)
            logger.info("Cliente Groq API inicializado correctamente.")
        except Exception as e:
            logger.warning("No se pudo inicializar el cliente Groq: %s", e)
            self.groq_client = None

    def _init_local_whisper(self) -> bool:
        """Carga el modelo faster-whisper bajo demanda en memoria."""
        if self.local_model is not None:
            return True

        try:
            from faster_whisper import WhisperModel
            import torch

            device = self.local_device
            compute_type = self.local_compute_type

            # Ajuste automático de CUDA si está disponible
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA no disponible en el sistema. Cambiando a CPU.")
                device = "cpu"
                compute_type = "int8"

            logger.info(
                "Cargando faster-whisper en local (Modelo: %s, Dispositivo: %s, Cómputo: %s)...",
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
            logger.info("Modelo local faster-whisper listo.")
            return True
        except Exception as e:
            logger.error("Error al cargar faster-whisper local: %s", e)
            return False

    @staticmethod
    def _float32_to_wav_bytes(audio_array: np.ndarray, sample_rate: int = 16000) -> bytes:
        """
        Convierte un array float32 de audio en bytes WAV en memoria sin escribir en disco.
        """
        # Normalizar y convertir a enteros con signo de 16 bits (PCM16)
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
        """Transcribe utilizando Groq Whisper Cloud."""
        if not self.groq_client:
            raise RuntimeError("Cliente Groq no configurado o API Key ausente.")

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
        """Transcribe utilizando faster-whisper local."""
        if not self._init_local_whisper() or self.local_model is None:
            raise RuntimeError("El modelo faster-whisper no se encuentra disponible.")

        # faster-whisper acepta directamente el array numpy float32 normalizado
        segments, _ = self.local_model.transcribe(
            audio_array,
            language=self.target_language,
            beam_size=2,
            vad_filter=False,  # Ya filtramos previamente con Silero
            temperature=0.0,
        )
        text_parts = [segment.text.strip() for segment in segments]
        return " ".join(text_parts).strip()

    def transcribe(self, audio_array: np.ndarray) -> Tuple[str, float, str]:
        """
        Transcribe el fragmento de audio con failover automático.
        :param audio_array: Array 1D float32 a 16000Hz.
        :return: Tuple:
            - text: Texto transcrito/traducido.
            - latency_ms: Tiempo de inferencia en milisegundos.
            - engine: 'Groq Cloud' o 'Local Whisper'.
        """
        t_start = time.perf_counter()
        engine_used = "Desconocido"
        text = ""

        # Intento primario
        if self.stt_mode == "cloud" and self.groq_client is not None:
            try:
                text = self._transcribe_groq(audio_array)
                engine_used = "Groq Cloud (<300ms)"
            except Exception as e:
                logger.warning("Fallo en transcripción en la nube Groq: %s", e)
                if self.fallback_to_local:
                    logger.info("Activando conmutación por error a faster-whisper local...")
                    try:
                        text = self._transcribe_local(audio_array)
                        engine_used = "Local Whisper (Fallback)"
                    except Exception as local_err:
                        logger.error("Fallo tanto en Cloud como en Local: %s", local_err)
                        text = ""
                else:
                    text = ""
        else:
            # Modo local forzado o sin credenciales de Groq
            try:
                text = self._transcribe_local(audio_array)
                engine_used = "Local Whisper"
            except Exception as e:
                logger.error("Error en transcripción local: %s", e)
                text = ""

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        return text, latency_ms, engine_used
