"""
LiveCopilot - Módulo de Detección de Actividad de Voz (VAD)
Segmenta el flujo continuo de audio utilizando Silero-VAD (PyTorch)
o cálculo dinámico de energía RMS como fallback inteligente.
Emite segmentos completos de voz cuando el silencio supera el umbral configurado (1800 ms por defecto).
"""

import collections
import logging
from typing import Deque, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("LiveCopilot.VADDetector")


class VADDetector:
    """
    Detector de actividad de voz con buffer dinámico, pre-roll para no cortar
    consonantes iniciales y temporizador de silencio para segmentar intervenciones.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_timeout_ms: int = 1800,
        vad_threshold: float = 0.40,
        min_speech_duration_sec: float = 0.6,
        max_speech_duration_sec: float = 30.0,
    ):
        """
        :param sample_rate: Frecuencia de muestreo (16000 Hz).
        :param silence_timeout_ms: Tiempo de silencio requerido para cerrar el segmento (1800 ms por defecto para frases completas).
        :param vad_threshold: Umbral de probabilidad de habla (0.1 a 0.9).
        :param min_speech_duration_sec: Duración mínima acumulada para descartar chasquidos o ruidos breves.
        :param max_speech_duration_sec: Límite máximo para forzar corte en intervenciones ininterrumpidas.
        """
        self.sample_rate = sample_rate
        self.silence_timeout_ms = silence_timeout_ms
        self.vad_threshold = vad_threshold
        self.min_speech_duration_sec = min_speech_duration_sec
        self.max_speech_duration_sec = max_speech_duration_sec

        # Estado del VAD
        self.is_speech_active = False
        self.silence_counter_ms = 0.0
        self.speech_buffer: List[np.ndarray] = []

        # Buffer circular de pre-roll (~320 ms = 10 chunks de 32ms) para conservar el inicio del habla intacto
        self.preroll_buffer: Deque[np.ndarray] = collections.deque(maxlen=10)

        # Inicialización del modelo Silero-VAD
        self.model = None
        self.torch = None
        self.use_silero = self._init_silero()

        # Parámetros para fallback RMS dinámico
        self._ambient_rms = 0.005
        self._rms_alpha = 0.95

    def _init_silero(self) -> bool:
        """Carga el modelo Silero VAD usando PyTorch con gestión de excepciones."""
        try:
            import torch
            self.torch = torch
            # Desactivar gradientes para optimizar latencia y memoria
            torch.set_grad_enabled(False)

            logger.info("Cargando modelo Silero-VAD...")
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
                onnx=False,
            )
            model.eval()
            self.model = model
            logger.info("Silero-VAD cargado exitosamente en memoria.")
            return True
        except Exception as e:
            logger.warning(
                "No se pudo inicializar Silero-VAD (%s). Se activará el motor RMS adaptativo.", e
            )
            self.model = None
            return False

    def _predict_speech_probability(self, chunk: np.ndarray) -> float:
        """
        Evalúa si un bloque de audio contiene voz humana.
        :param chunk: Array 1D float32 de 512 muestras.
        :return: Probabilidad de habla entre 0.0 y 1.0.
        """
        if self.use_silero and self.model is not None and self.torch is not None:
            try:
                # Silero VAD requiere entrada en 16000Hz con exactamente 512 muestras
                if len(chunk) != 512:
                    if len(chunk) < 512:
                        chunk = np.pad(chunk, (0, 512 - len(chunk)))
                    else:
                        chunk = chunk[:512]

                tensor_chunk = self.torch.from_numpy(chunk).float()
                # Salida escalar de probabilidad
                prob = float(self.model(tensor_chunk, self.sample_rate).item())
                return prob
            except Exception as e:
                logger.debug("Fallo en inferencia Silero, usando RMS: %s", e)

        # Fallback inteligente: Detección adaptativa por energía RMS
        rms = float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size > 0 else 0.0

        # Actualizar piso de ruido ambiental de forma suave
        if rms < self._ambient_rms * 1.5:
            self._ambient_rms = self._rms_alpha * self._ambient_rms + (1 - self._rms_alpha) * rms

        # Relación de señal a ruido (SNR estimado)
        snr_ratio = rms / (self._ambient_rms + 1e-6)
        if snr_ratio > 3.0 and rms > 0.012:
            return 0.85
        elif snr_ratio > 2.0 and rms > 0.008:
            return 0.60
        else:
            return 0.15

    def process_chunk(self, chunk: np.ndarray) -> Tuple[Optional[np.ndarray], bool, float]:
        """
        Procesa un bloque de audio entrante y actualiza el estado de la intervención.
        :param chunk: Bloque de audio float32 (512 muestras típicas a 16kHz).
        :return: Tuple:
            - speech_segment (np.ndarray completo o None si aún no se cierra la intervención)
            - is_speaking (True si actualmente se detecta voz activa)
            - speech_prob (probabilidad de habla del bloque actual)
        """
        chunk_duration_ms = (len(chunk) / self.sample_rate) * 1000.0
        prob = self._predict_speech_probability(chunk)
        is_current_frame_speech = prob >= self.vad_threshold

        completed_segment: Optional[np.ndarray] = None

        if is_current_frame_speech:
            if not self.is_speech_active:
                # Inicio de nueva intervención: incorporar el audio previo del pre-roll
                self.is_speech_active = True
                self.speech_buffer = list(self.preroll_buffer)
                logger.debug("Inicio de intervención detectado (Prob: %.2f)", prob)

            self.speech_buffer.append(chunk)
            self.silence_counter_ms = 0.0

        else:
            if self.is_speech_active:
                # Continúa dentro de la intervención pero en pausa momentánea
                self.speech_buffer.append(chunk)
                self.silence_counter_ms += chunk_duration_ms

                # Comprobación de fin de intervención por silencio prolongado (>600ms)
                # o por límite de duración máxima
                current_duration_sec = sum(len(c) for c in self.speech_buffer) / self.sample_rate

                if (
                    self.silence_counter_ms >= self.silence_timeout_ms
                    or current_duration_sec >= self.max_speech_duration_sec
                ):
                    if current_duration_sec >= self.min_speech_duration_sec:
                        # Recortar el exceso de silencio final para que Whisper no procese 1.8s de silencio
                        # pero conservando ~350 ms de decaimiento natural
                        silence_chunks_count = int(self.silence_counter_ms / chunk_duration_ms)
                        keep_silence_chunks = min(silence_chunks_count, 11)
                        if silence_chunks_count > keep_silence_chunks:
                            trim_count = silence_chunks_count - keep_silence_chunks
                            buffer_to_send = self.speech_buffer[:-trim_count] if trim_count > 0 else self.speech_buffer
                        else:
                            buffer_to_send = self.speech_buffer

                        completed_segment = np.concatenate(buffer_to_send)
                        logger.info(
                            "Segmento de voz cerrado: %.2f s (Silencio esperado: %.0f ms).",
                            len(completed_segment) / self.sample_rate,
                            self.silence_counter_ms,
                        )

                    # Resetear estado
                    self.speech_buffer = []
                    self.is_speech_active = False
                    self.silence_counter_ms = 0.0
            else:
                # Audio sin actividad de voz: alimentar buffer circular de pre-roll
                self.preroll_buffer.append(chunk)

        return completed_segment, self.is_speech_active, prob

    def flush(self) -> Optional[np.ndarray]:
        """
        Cierra forzosamente la intervención actual al pausar y devuelve el audio
        acumulado hasta el momento (si supera ~0.35s de habla).
        """
        completed_segment = None
        buffer_to_send = list(self.speech_buffer) if self.speech_buffer else []
        if not buffer_to_send and self.preroll_buffer:
            buffer_to_send = list(self.preroll_buffer)

        if buffer_to_send:
            current_duration_sec = sum(len(c) for c in buffer_to_send) / self.sample_rate
            if current_duration_sec >= 0.35:
                completed_segment = np.concatenate(buffer_to_send)
                logger.info(
                    "Segmento de voz tomado por pausa manual: %.2f s.",
                    current_duration_sec,
                )

        self.reset()
        return completed_segment

    def reset(self):
        """Reinicia los acumuladores y buffers internos."""
        self.is_speech_active = False
        self.silence_counter_ms = 0.0
        self.speech_buffer.clear()
        self.preroll_buffer.clear()
        if self.model is not None and hasattr(self.model, "reset_states"):
            try:
                self.model.reset_states()
            except Exception:
                pass
