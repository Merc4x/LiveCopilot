"""
LiveCopilot - Módulo de Captura de Audio Interno (WASAPI Loopback)
Captura la salida de audio predeterminada de Windows en tiempo real (16kHz, mono, float32)
sin bloquear el hilo principal.
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
    Captura de audio en bucle (WASAPI Loopback) desde el altavoz predeterminado de Windows.
    Alimenta una cola en memoria con bloques de audio de 16000 Hz en formato float32.
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
        :param sample_rate: Frecuencia de muestreo (16000 Hz óptima para Whisper y Silero-VAD).
        :param block_size: Tamaño de bloque por muestra (512 muestras = 32ms a 16kHz).
        :param max_queue_size: Tamaño máximo de la cola para prevenir buffer bloat.
        :param device_id: ID específico del dispositivo loopback a capturar (o None para el predeterminado).
        :param on_audio_level: Callback opcional para transmitir el nivel RMS del audio (0.0 a 1.0).
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
        Retorna la lista de todos los dispositivos de audio loopback disponibles en la PC
        (altavoces, auriculares, monitores, cables virtuales).
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
                    label = f"{mic.name} (Por defecto)" if is_def else mic.name
                    devices.append({
                        "id": mic.id,
                        "name": mic.name,
                        "label": label,
                        "is_default": is_def,
                    })
        except Exception as e:
            logger.error("Error al enumerar dispositivos de audio: %s", e)
        return devices

    def set_device(self, device_id: Optional[str]):
        """Cambia dinámicamente el dispositivo de captura de audio sin reiniciar la app."""
        if self.device_id == device_id:
            return
        logger.info("Cambiando dispositivo de audio a: %s", device_id)
        self.device_id = device_id
        if self.is_running():
            was_paused = self.is_paused()
            self.stop()
            self.start()
            if was_paused:
                self.pause()

    def start(self):
        """Inicia el hilo en segundo plano para la captura de audio."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("El hilo de captura de audio ya se encuentra en ejecución.")
            return

        self._is_running.set()
        self._is_paused.clear()
        self._thread = threading.Thread(
            target=self._capture_worker,
            name="AudioCaptureThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("Captura de audio WASAPI Loopback iniciada a %d Hz.", self.sample_rate)

    def pause(self):
        """Pausa la captura de audio sin desconectar el dispositivo."""
        self._is_paused.set()
        logger.info("Captura de audio pausada.")

    def resume(self):
        """Reanuda la captura de audio."""
        self._is_paused.clear()
        logger.info("Captura de audio reanudada.")

    def is_paused(self) -> bool:
        """Verifica si la captura está pausada."""
        return self._is_paused.is_set()

    def is_running(self) -> bool:
        """Verifica si el hilo de captura sigue activo."""
        return self._is_running.is_set()

    def stop(self):
        """Detiene la captura de audio y libera los recursos del hardware."""
        self._is_running.clear()
        self._is_paused.clear()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        logger.info("Captura de audio detenida correctamente.")

    def get_chunk(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        """
        Obtiene un bloque de audio de la cola de forma segura.
        :return: Array 1D numpy en float32 o None si no hay datos disponibles en el tiempo límite.
        """
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _capture_worker(self):
        """Hilo de trabajo que gestiona la conexión con el altavoz predeterminado vía WASAPI Loopback."""
        import warnings
        # Suprimir advertencias de buffer no críticas de soundcard
        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

        loopback_mic = None
        try:
            # 1. Si el usuario configuró un dispositivo específico
            if self.device_id:
                try:
                    loopback_mic = sc.get_microphone(id=self.device_id, include_loopback=True)
                    logger.info("Usando dispositivo de audio seleccionado por el usuario: %s", loopback_mic.name)
                except Exception as e:
                    logger.warning("Fallo al abrir dispositivo de audio seleccionado (%s): %s", self.device_id, e)

            # 2. Si no hay seleccionado o falló, usar el altavoz predeterminado
            if loopback_mic is None:
                speaker = sc.default_speaker()
                logger.info("Dispositivo de salida predeterminado: %s", speaker.name)
                try:
                    loopback_mic = sc.get_microphone(id=speaker.id, include_loopback=True)
                except Exception as e:
                    logger.warning("Fallo al buscar loopback por id de altavoz: %s", e)

            # 3. Fallback: Buscar en la lista de todos los micrófonos con loopback habilitado
            if loopback_mic is None:
                for mic in sc.all_microphones(include_loopback=True):
                    if getattr(mic, "isloopback", False):
                        loopback_mic = mic
                        logger.info("Dispositivo loopback alternativo encontrado: %s", mic.name)
                        break

        except Exception as e:
            logger.error("No se pudo inicializar la captura de audio: %s", e)
            return

        if loopback_mic is None:
            logger.error("No fue posible encontrar ningún dispositivo WASAPI Loopback en el sistema.")
            return

        try:
            logger.info("Abriendo grabador WASAPI Loopback en: %s (%d Hz)...", loopback_mic.name, self.sample_rate)
            with loopback_mic.recorder(samplerate=self.sample_rate) as rec:
                logger.info("Conexión WASAPI Loopback establecida y activa.")
                while self._is_running.is_set():
                    if self._is_paused.is_set():
                        time.sleep(0.05)
                        continue

                    # Grabación en el hilo dedicado
                    data = rec.record(numframes=self.block_size)

                    # Si el dispositivo devuelve múltiples canales, convertir a mono promedio
                    if data.ndim > 1 and data.shape[1] > 1:
                        mono_data = np.mean(data, axis=1, dtype=np.float32)
                    else:
                        mono_data = data.reshape(-1).astype(np.float32)

                    # Cálculo dinámico del nivel RMS para el vúmetro de la UI
                    rms = float(np.sqrt(np.mean(np.square(mono_data)))) if mono_data.size > 0 else 0.0
                    if self.on_audio_level:
                        try:
                            # Factor de escala adaptado para reuniones (0.0 a 1.0)
                            normalized_level = min(1.0, rms * 25.0)
                            self.on_audio_level(normalized_level)
                        except Exception:
                            pass

                    # Inserción en cola no bloqueante con mitigación de lag
                    if self.audio_queue.full():
                        try:
                            self.audio_queue.get_nowait()  # Descartar bloque más antiguo
                        except queue.Empty:
                            pass

                    self.audio_queue.put_nowait(mono_data)

        except Exception as e:
            if self._is_running.is_set():
                logger.error("Error crítico durante la captura de audio en bucle: %s", e, exc_info=True)
        finally:
            logger.info("Ciclo de captura finalizado.")
