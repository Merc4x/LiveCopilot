"""
LiveCopilot - Internal Audio Capture Module (WASAPI Loopback)
Captures default Windows speaker audio output in real time (16kHz, mono, float32)
without blocking the main user interface.
"""

import logging
import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import soundcard as sc

logger = logging.getLogger("LiveCopilot.AudioCapture")


class AudioCapture:
    """
    Loopback audio capture (WASAPI Loopback) from Windows speaker output.
    Feeds an in-memory queue with 16,000 Hz float32 audio chunks.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        block_size: int = 512,
        max_queue_size: int = 150,
        device_id: Optional[str] = None,
        on_audio_level: Optional[Callable[[float], None]] = None,
    ):
        """
        :param sample_rate: Audio sample rate (16,000 Hz optimal for Whisper and Silero-VAD).
        :param block_size: Block size per buffer read (512 samples = 32ms at 16kHz).
        :param max_queue_size: Maximum queue capacity to prevent buffer bloat.
        :param device_id: Specific loopback device ID to capture (or None for default).
        :param on_audio_level: Optional callback to stream normalized RMS audio levels (0.0 to 1.0).
        """
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.max_queue_size = max_queue_size
        self.device_id = device_id
        self.on_audio_level = on_audio_level

        self.audio_queue: queue.Queue = queue.Queue(maxsize=self.max_queue_size)
        self._is_running = threading.Event()
        self._is_paused = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def get_available_devices():
        """
        Returns all loopback-capable audio output devices available on the system
        (speakers, headphones, monitors, virtual audio cables).
        """
        devices = []
        try:
            import warnings
            warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
            try:
                default_spk = sc.default_speaker()
                default_id = default_spk.id if default_spk else ""
            except Exception:
                default_id = ""

            for mic in sc.all_microphones(include_loopback=True):
                if getattr(mic, "isloopback", False):
                    is_def = (mic.id == default_id)
                    label = f"{mic.name} (Default)" if is_def else mic.name
                    devices.append({
                        "id": mic.id,
                        "name": mic.name,
                        "label": label,
                        "is_default": is_def,
                    })
        except Exception as e:
            logger.error("Error enumerating audio devices: %s", e)
        return devices

    def set_device(self, device_id: Optional[str]):
        """Dynamically switches audio capture device without restarting the application."""
        if self.device_id == device_id:
            return
        logger.info("Switching audio device to: %s", device_id)
        self.device_id = device_id
        if self.is_running():
            was_paused = self.is_paused()
            self.stop()
            self.start()
            if was_paused:
                self.pause()

    def start(self):
        """Starts background worker thread for loopback audio recording."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Audio capture thread is already running.")
            return

        self._is_running.set()
        self._is_paused.clear()
        self._thread = threading.Thread(
            target=self._capture_worker,
            name="AudioCaptureThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("WASAPI Loopback audio capture started at %d Hz.", self.sample_rate)

    def pause(self):
        """Pauses audio ingestion without unbinding the device."""
        self._is_paused.set()
        logger.info("Audio capture paused.")

    def resume(self):
        """Resumes audio ingestion."""
        self._is_paused.clear()
        logger.info("Audio capture resumed.")

    def is_paused(self) -> bool:
        """Returns True if capture is currently paused."""
        return self._is_paused.is_set()

    def is_running(self) -> bool:
        """Returns True if the background recording thread is active."""
        return self._is_running.is_set()

    def stop(self):
        """Stops audio capture and releases hardware resources."""
        self._is_running.clear()
        self._is_paused.clear()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        logger.info("Audio capture stopped cleanly.")

    def get_chunk(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        """
        Safely retrieves a float32 audio chunk from the buffer queue.
        :return: 1D numpy array in float32 format or None if queue was empty within timeout.
        """
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _capture_worker(self):
        """Worker thread loop interfacing with Windows WASAPI Loopback recorder."""
        import warnings
        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

        loopback_mic = None
        try:
            # 1. Custom user device
            if self.device_id:
                try:
                    loopback_mic = sc.get_microphone(id=self.device_id, include_loopback=True)
                    logger.info("Using user-selected audio device: %s", loopback_mic.name)
                except Exception as e:
                    logger.warning("Failed to open selected audio device (%s): %s", self.device_id, e)

            # 2. System default speaker loopback
            if loopback_mic is None:
                speaker = sc.default_speaker()
                logger.info("Default system speaker: %s", speaker.name)
                try:
                    loopback_mic = sc.get_microphone(id=speaker.id, include_loopback=True)
                except Exception as e:
                    logger.warning("Failed to find loopback for default speaker: %s", e)

            # 3. Fallback discovery among all available microphones
            if loopback_mic is None:
                for mic in sc.all_microphones(include_loopback=True):
                    if getattr(mic, "isloopback", False):
                        loopback_mic = mic
                        logger.info("Alternative loopback device discovered: %s", mic.name)
                        break

        except Exception as e:
            logger.error("Could not initialize audio capture: %s", e)
            return

        if loopback_mic is None:
            logger.error("No WASAPI Loopback audio device found on this system.")
            return

        try:
            logger.info("Opening WASAPI Loopback recorder on: %s (%d Hz)...", loopback_mic.name, self.sample_rate)
            with loopback_mic.recorder(samplerate=self.sample_rate) as rec:
                logger.info("WASAPI Loopback connection established and active.")
                while self._is_running.is_set():
                    if self._is_paused.is_set():
                        time.sleep(0.05)
                        continue

                    # Record raw frames in worker thread
                    data = rec.record(numframes=self.block_size)

                    # Downmix multi-channel audio to mono float32
                    if data.ndim > 1 and data.shape[1] > 1:
                        mono_data = np.mean(data, axis=1, dtype=np.float32)
                    else:
                        mono_data = data.reshape(-1).astype(np.float32)

                    # Compute RMS energy for GUI VU meter
                    rms = float(np.sqrt(np.mean(np.square(mono_data)))) if mono_data.size > 0 else 0.0
                    if self.on_audio_level:
                        try:
                            # Normalized scale for meeting audio
                            normalized_level = min(1.0, rms * 25.0)
                            self.on_audio_level(normalized_level)
                        except Exception:
                            pass

                    # Non-blocking enqueue with lag mitigation
                    if self.audio_queue.full():
                        try:
                            self.audio_queue.get_nowait()  # Drop oldest frame
                        except queue.Empty:
                            pass

                    self.audio_queue.put_nowait(mono_data)

        except Exception as e:
            if self._is_running.is_set():
                logger.error("Critical error in WASAPI Loopback capture: %s", e, exc_info=True)
        finally:
            logger.info("Audio capture cycle terminated.")
