"""
LiveCopilot - Voice Activity Detection Module (VAD)
Segments continuous audio streams using deep-learning Silero-VAD (PyTorch)
with dynamic RMS energy calculation as an intelligent fallback.
Emits complete speech segments when silence exceeds the configured threshold (default: 1800 ms).
"""

import collections
import logging
from typing import Deque, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("LiveCopilot.VADDetector")


class VADDetector:
    """
    Voice activity detector with dynamic buffering, pre-roll to prevent clipping
    initial consonants, and silence timing for sentence/paragraph segmentation.
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
        :param sample_rate: Audio sample rate in Hz (16,000 Hz).
        :param silence_timeout_ms: Silence duration required to close segment (1800 ms default for full sentences).
        :param vad_threshold: Voice probability threshold (0.1 to 0.9).
        :param min_speech_duration_sec: Minimum speech duration to filter out clicks or noise bursts.
        :param max_speech_duration_sec: Upper bound to force segmentation during uninterrupted monologues.
        """
        self.sample_rate = sample_rate
        self.silence_timeout_ms = silence_timeout_ms
        self.vad_threshold = vad_threshold
        self.min_speech_duration_sec = min_speech_duration_sec
        self.max_speech_duration_sec = max_speech_duration_sec

        # VAD State
        self.is_speech_active = False
        self.silence_counter_ms = 0.0
        self.speech_buffer: List[np.ndarray] = []

        # Circular pre-roll buffer (~320 ms = 10 chunks of 32ms) to preserve initial speech consonants
        self.preroll_buffer: Deque[np.ndarray] = collections.deque(maxlen=10)

        # Initialize Silero-VAD deep learning model
        self.model = None
        self.torch = None
        self.use_silero = self._init_silero()

        # Parameters for adaptive RMS fallback
        self._ambient_rms = 0.005
        self._rms_alpha = 0.95

    def _init_silero(self) -> bool:
        """Loads the Silero-VAD PyTorch model with graceful exception handling."""
        try:
            import torch
            self.torch = torch
            # Disable autograd gradients for optimized latency and zero memory overhead
            torch.set_grad_enabled(False)

            logger.info("Loading Silero-VAD model...")
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
                onnx=False,
            )
            model.eval()
            self.model = model
            logger.info("Silero-VAD loaded successfully into memory.")
            return True
        except Exception as e:
            logger.warning(
                "Could not initialize Silero-VAD (%s). Engaging adaptive RMS fallback engine.", e
            )
            self.model = None
            return False

    def _predict_speech_probability(self, chunk: np.ndarray) -> float:
        """
        Evaluates whether an audio chunk contains human voice activity.
        :param chunk: 1D float32 array of 512 samples.
        :return: Speech probability between 0.0 and 1.0.
        """
        if self.use_silero and self.model is not None and self.torch is not None:
            try:
                # Silero-VAD requires exactly 512 samples at 16,000 Hz
                if len(chunk) != 512:
                    if len(chunk) < 512:
                        chunk = np.pad(chunk, (0, 512 - len(chunk)))
                    else:
                        chunk = chunk[:512]

                tensor_chunk = self.torch.from_numpy(chunk).float()
                prob = float(self.model(tensor_chunk, self.sample_rate).item())
                return prob
            except Exception as e:
                logger.debug("Silero inference fallback to RMS: %s", e)

        # Intelligent Fallback: Adaptive RMS energy detection
        rms = float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size > 0 else 0.0

        # Smoothly track background ambient noise floor
        if rms < self._ambient_rms * 1.5:
            self._ambient_rms = self._rms_alpha * self._ambient_rms + (1 - self._rms_alpha) * rms

        # Estimated Signal-to-Noise Ratio (SNR)
        snr_ratio = rms / (self._ambient_rms + 1e-6)
        if snr_ratio > 3.0 and rms > 0.012:
            return 0.85
        elif snr_ratio > 2.0 and rms > 0.008:
            return 0.60
        else:
            return 0.15

    def process_chunk(self, chunk: np.ndarray) -> Tuple[Optional[np.ndarray], bool, float]:
        """
        Processes an incoming audio chunk and updates speech activity state.
        :param chunk: float32 audio chunk (typically 512 samples at 16kHz).
        :return: Tuple:
            - speech_segment (complete np.ndarray or None if utterance is still ongoing)
            - is_speaking (True if currently in active speech)
            - speech_prob (speech probability for the current block)
        """
        chunk_duration_ms = (len(chunk) / self.sample_rate) * 1000.0
        prob = self._predict_speech_probability(chunk)
        is_current_frame_speech = prob >= self.vad_threshold

        completed_segment: Optional[np.ndarray] = None

        if is_current_frame_speech:
            if not self.is_speech_active:
                # Start of a new utterance: prepend pre-roll audio
                self.is_speech_active = True
                self.speech_buffer = list(self.preroll_buffer)
                logger.debug("Speech start detected (Prob: %.2f)", prob)

            self.speech_buffer.append(chunk)
            self.silence_counter_ms = 0.0

        else:
            if self.is_speech_active:
                # Currently within an ongoing utterance during a momentary breath/pause
                self.speech_buffer.append(chunk)
                self.silence_counter_ms += chunk_duration_ms

                # Check if silence threshold or maximum duration is reached
                current_duration_sec = sum(len(c) for c in self.speech_buffer) / self.sample_rate

                if (
                    self.silence_counter_ms >= self.silence_timeout_ms
                    or current_duration_sec >= self.max_speech_duration_sec
                ):
                    if current_duration_sec >= self.min_speech_duration_sec:
                        # Trim excess trailing silence to save inference time while keeping natural decay (~350ms)
                        silence_chunks_count = int(self.silence_counter_ms / chunk_duration_ms)
                        keep_silence_chunks = min(silence_chunks_count, 11)
                        if silence_chunks_count > keep_silence_chunks:
                            trim_count = silence_chunks_count - keep_silence_chunks
                            buffer_to_send = self.speech_buffer[:-trim_count] if trim_count > 0 else self.speech_buffer
                        else:
                            buffer_to_send = self.speech_buffer

                        completed_segment = np.concatenate(buffer_to_send)
                        logger.info(
                            "Speech segment completed: %.2f s (Silence: %.0f ms).",
                            len(completed_segment) / self.sample_rate,
                            self.silence_counter_ms,
                        )

                    # Reset internal state
                    self.speech_buffer = []
                    self.is_speech_active = False
                    self.silence_counter_ms = 0.0
            else:
                # Non-speech audio: feed circular pre-roll buffer
                self.preroll_buffer.append(chunk)

        return completed_segment, self.is_speech_active, prob

    def flush(self) -> Optional[np.ndarray]:
        """
        Forcibly closes the current speech buffer upon manual pause and returns
        the audio accumulated so far (if >= 0.35s).
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
                    "Speech segment flushed on manual pause: %.2f s.",
                    current_duration_sec,
                )

        self.reset()
        return completed_segment

    def reset(self):
        """Resets accumulators, state counters, and internal buffers."""
        self.is_speech_active = False
        self.silence_counter_ms = 0.0
        self.speech_buffer.clear()
        self.preroll_buffer.clear()
        if self.model is not None and hasattr(self.model, "reset_states"):
            try:
                self.model.reset_states()
            except Exception:
                pass
