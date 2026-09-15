"""
LiveCopilot - Diálogo Visual de Configuración (PyQt6)
Permite a cualquier usuario configurar su API Key de Groq con validación en vivo,
elegir su dispositivo de salida de audio (auriculares, altavoces) y seleccionar el idioma
sin necesidad de editar archivos ni usar comandos de consola.
"""

import logging
import os
import re
import sys
from typing import Dict, List, Optional

from dotenv import load_dotenv
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.audio_capture import AudioCapture

logger = logging.getLogger("LiveCopilot.Settings")


def get_env_path() -> str:
    """Retorna la ruta al archivo .env tanto en modo script como compilado (.exe)."""
    import sys
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, ".env")


class SettingsDialog(QDialog):
    """Ventana modal de configuración con diseño dark glassmorphism."""

    # Señal emitida cuando el usuario guarda los cambios exitosamente
    settings_saved = pyqtSignal(dict)

    def __init__(self, parent=None, is_first_run: bool = False):
        super().__init__(parent)
        self.is_first_run = is_first_run

        self._init_window()
        self._init_styles()
        self._build_ui()
        self._load_current_values()

    def _init_window(self):
        """Configuración de propiedades de ventana modal."""
        self.setWindowTitle("Configuración de LiveCopilot")
        flags = Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        if self.is_first_run:
            flags = (
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowMinimizeButtonHint
            )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(500, 540)

        # Control de arrastre
        self._is_dragging = False
        self._drag_pos = None

    def showEvent(self, event):
        super().showEvent(event)
        if self.is_first_run and sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                user32 = ctypes.windll.user32
                ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_APPWINDOW)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)
            except Exception:
                pass

    def _init_styles(self):
        """Estilos CSS con paleta moderna oscura y acento verde menta."""
        self.setStyleSheet("""
            QWidget#MainContainer {
                background-color: rgba(18, 18, 18, 0.95);
                border: 1px solid rgba(0, 245, 212, 0.35);
                border-radius: 16px;
            }
            
            QFrame#HeaderBar {
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                padding-bottom: 8px;
            }
            
            QLabel#TitleLabel {
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 15px;
                font-weight: 700;
            }
            
            QLabel#SubtitleLabel {
                color: #9CA3AF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11.5px;
            }
            
            QLabel.FieldLabel {
                color: #E5E7EB;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                font-weight: 600;
                margin-top: 6px;
            }
            
            QLineEdit#ApiKeyInput {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                color: #FFFFFF;
                font-family: 'Consolas', monospace;
                font-size: 12px;
                padding: 6px 10px;
            }
            QLineEdit#ApiKeyInput:focus {
                border: 1px solid #00F5D4;
                background-color: rgba(0, 245, 212, 0.05);
            }
            
            QComboBox#DeviceCombo, QComboBox#LangCombo, QComboBox#TimeoutCombo {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                padding: 6px 10px;
            }
            QComboBox#DeviceCombo:focus, QComboBox#LangCombo:focus, QComboBox#TimeoutCombo:focus {
                border: 1px solid #00F5D4;
            }
            QComboBox QAbstractItemView {
                background-color: #1F2937;
                color: #FFFFFF;
                selection-background-color: #00F5D4;
                selection-color: #111827;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 4px;
            }
            
            QPushButton#BtnToggleEye, QPushButton#BtnVerifyKey {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                color: #E5E7EB;
                font-size: 11.5px;
                font-weight: 600;
                padding: 6px 10px;
            }
            QPushButton#BtnToggleEye:hover, QPushButton#BtnVerifyKey:hover {
                background-color: rgba(255, 255, 255, 0.16);
                color: #FFFFFF;
            }
            
            QPushButton#BtnSave {
                background-color: #00F5D4;
                border: none;
                border-radius: 8px;
                color: #0B1917;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: 700;
                padding: 8px 18px;
            }
            QPushButton#BtnSave:hover {
                background-color: #38EF7D;
            }
            
            QPushButton#BtnCancel {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                color: #9CA3AF;
                font-size: 12px;
                padding: 8px 14px;
            }
            QPushButton#BtnCancel:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
            }
            
            QLabel#StatusKeyLabel {
                font-size: 11px;
                font-weight: 600;
            }
            
            QLabel#HelpLink {
                color: #38BDF8;
                font-size: 11px;
            }
        """)

    def _build_ui(self):
        """Construye la jerarquía visual de los campos."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Contenedor con sombra perimetral
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(18, 16, 18, 16)
        container_layout.setSpacing(10)

        # -------------------------------------------------------------
        # Cabecera
        # -------------------------------------------------------------
        header_frame = QFrame(self.container)
        header_frame.setObjectName("HeaderBar")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 4)

        header_info = QVBoxLayout()
        header_info.setSpacing(2)
        title_text = "⚡ Bienvenido a LiveCopilot" if self.is_first_run else "⚙️ Configuración de LiveCopilot"
        lbl_title = QLabel(title_text, header_frame)
        lbl_title.setObjectName("TitleLabel")
        lbl_sub = QLabel("Personaliza tu API Key de Groq y tu salida de audio.", header_frame)
        lbl_sub.setObjectName("SubtitleLabel")
        header_info.addWidget(lbl_title)
        header_info.addWidget(lbl_sub)
        header_layout.addLayout(header_info)
        header_layout.addStretch()

        if not self.is_first_run:
            btn_close = QPushButton("✕", header_frame)
            btn_close.setObjectName("BtnToggleEye")
            btn_close.setFixedSize(28, 28)
            btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_close.clicked.connect(self.reject)
            header_layout.addWidget(btn_close)

        container_layout.addWidget(header_frame)

        # -------------------------------------------------------------
        # Campo 1: GROQ_API_KEY
        # -------------------------------------------------------------
        lbl_api_key = QLabel("🔑 Clave API de Groq (Gratuita):", self.container)
        lbl_api_key.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_api_key)

        key_row = QHBoxLayout()
        self.input_key = QLineEdit(self.container)
        self.input_key.setObjectName("ApiKeyInput")
        self.input_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_key.setPlaceholderText("gsk_...")
        key_row.addWidget(self.input_key)

        self.btn_eye = QPushButton("👁️", self.container)
        self.btn_eye.setObjectName("BtnToggleEye")
        self.btn_eye.setToolTip("Mostrar / Ocultar clave")
        self.btn_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_eye.clicked.connect(self._toggle_password_visibility)
        key_row.addWidget(self.btn_eye)

        self.btn_verify = QPushButton("Verificar", self.container)
        self.btn_verify.setObjectName("BtnVerifyKey")
        self.btn_verify.setToolTip("Comprobar conexión con Groq")
        self.btn_verify.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_verify.clicked.connect(self._verify_api_key)
        key_row.addWidget(self.btn_verify)

        container_layout.addLayout(key_row)

        # Estado de verificación y enlace de ayuda
        key_help_row = QHBoxLayout()
        self.lbl_key_status = QLabel("", self.container)
        self.lbl_key_status.setObjectName("StatusKeyLabel")
        key_help_row.addWidget(self.lbl_key_status)
        key_help_row.addStretch()

        lbl_link = QLabel(
            '<a style="color: #38BDF8; text-decoration: none;" href="https://console.groq.com/keys">👉 Obtener clave gratis aquí</a>',
            self.container,
        )
        lbl_link.setObjectName("HelpLink")
        lbl_link.setOpenExternalLinks(True)
        key_help_row.addWidget(lbl_link)
        container_layout.addLayout(key_help_row)

        # -------------------------------------------------------------
        # Campo 2: Dispositivo de Salida de Audio (Altavoces / Auriculares)
        # -------------------------------------------------------------
        lbl_device = QLabel("🎧 Salida de Audio a Escuchar (Reunión / Video):", self.container)
        lbl_device.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_device)

        self.combo_device = QComboBox(self.container)
        self.combo_device.setObjectName("DeviceCombo")
        container_layout.addWidget(self.combo_device)

        lbl_device_hint = QLabel(
            "Selecciona los auriculares o altavoces por donde escuchas a los demás.", self.container
        )
        lbl_device_hint.setStyleSheet("color: #6B7280; font-size: 11px;")
        container_layout.addWidget(lbl_device_hint)

        # -------------------------------------------------------------
        # Campo 3: Modo de Idioma
        # -------------------------------------------------------------
        lbl_lang = QLabel("🌐 Idioma de Entrada / Detección:", self.container)
        lbl_lang.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_lang)

        self.combo_lang = QComboBox(self.container)
        self.combo_lang.setObjectName("LangCombo")
        self.combo_lang.addItem("Autodetectar (Recomendado para clases y llamadas)", "auto")
        self.combo_lang.addItem("Forzar Inglés (Speech en inglés)", "en")
        self.combo_lang.addItem("Forzar Español (Speech en español)", "es")
        container_layout.addWidget(self.combo_lang)

        # -------------------------------------------------------------
        # Campo 4: Longitud de Frase / Tiempo de Pausa (VAD)
        # -------------------------------------------------------------
        lbl_timeout = QLabel("⏱️ Longitud del Texto Escuchado (Pausa de habla):", self.container)
        lbl_timeout.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_timeout)

        self.combo_timeout = QComboBox(self.container)
        self.combo_timeout.setObjectName("TimeoutCombo")
        self.combo_timeout.addItem("Párrafos largos / Intervenciones completas (1.8 s de pausa) [Recomendado]", "1800")
        self.combo_timeout.addItem("Modo continuo / Conferencias y clases (2.5 s de pausa)", "2500")
        self.combo_timeout.addItem("Oraciones estándar (1.4 s de pausa)", "1400")
        self.combo_timeout.addItem("Frases rápidas cortas (0.8 s de pausa)", "800")
        container_layout.addWidget(self.combo_timeout)

        lbl_timeout_hint = QLabel(
            "Un tiempo mayor permite capturar oraciones completas y párrafos antes de traducir.", self.container
        )
        lbl_timeout_hint.setStyleSheet("color: #6B7280; font-size: 11px;")
        container_layout.addWidget(lbl_timeout_hint)

        container_layout.addStretch()

        # -------------------------------------------------------------
        # Botones de Acción
        # -------------------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 10, 0, 0)
        btn_layout.addStretch()

        if not self.is_first_run:
            self.btn_cancel = QPushButton("Cancelar", self.container)
            self.btn_cancel.setObjectName("BtnCancel")
            self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_cancel.clicked.connect(self.reject)
            btn_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("✓ Guardar y Comenzar" if self.is_first_run else "✓ Guardar Cambios", self.container)
        self.btn_save.setObjectName("BtnSave")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self._save_settings)
        btn_layout.addWidget(self.btn_save)

        container_layout.addLayout(btn_layout)
        root_layout.addWidget(self.container)

    def _load_current_values(self):
        """Carga los valores actuales del archivo .env y detecta dispositivos."""
        env_path = get_env_path()
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)

        current_key = os.getenv("GROQ_API_KEY", "").strip()
        if current_key and not current_key.startswith("PEGA_AQUI"):
            self.input_key.setText(current_key)

        current_device_id = os.getenv("AUDIO_DEVICE_ID", "").strip()
        current_lang = os.getenv("TARGET_LANGUAGE", "auto").strip().lower()

        # Cargar lista de dispositivos
        devices = AudioCapture.get_available_devices()
        self.combo_device.clear()

        selected_idx = 0
        for i, dev in enumerate(devices):
            self.combo_device.addItem(dev["label"], dev["id"])
            if current_device_id and dev["id"] == current_device_id:
                selected_idx = i
            elif not current_device_id and dev["is_default"]:
                selected_idx = i

        if devices:
            self.combo_device.setCurrentIndex(selected_idx)
        else:
            self.combo_device.addItem("Altavoz / Auriculares del Sistema (Por defecto)", "")

        # Seleccionar idioma
        for idx in range(self.combo_lang.count()):
            if self.combo_lang.itemData(idx) == current_lang:
                self.combo_lang.setCurrentIndex(idx)
                break

        # Seleccionar tiempo de pausa VAD
        current_timeout = os.getenv("VAD_SILENCE_TIMEOUT_MS", "1800").strip()
        for idx in range(self.combo_timeout.count()):
            if self.combo_timeout.itemData(idx) == current_timeout:
                self.combo_timeout.setCurrentIndex(idx)
                break

    def _toggle_password_visibility(self):
        """Alterna el modo de visualización de la clave API."""
        if self.input_key.echoMode() == QLineEdit.EchoMode.Password:
            self.input_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_eye.setText("🔒")
        else:
            self.input_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_eye.setText("👁️")

    def _verify_api_key(self):
        """Valida la clave directamente con la API de Groq en tiempo real."""
        key = self.input_key.text().strip()
        if not key or not key.startswith("gsk_"):
            self.lbl_key_status.setText("❌ La clave debe empezar por 'gsk_'")
            self.lbl_key_status.setStyleSheet("color: #EF4444;")
            return

        self.lbl_key_status.setText("⏳ Verificando con Groq...")
        self.lbl_key_status.setStyleSheet("color: #FBBF24;")
        self.btn_verify.setEnabled(False)

        try:
            from groq import Groq
            client = Groq(api_key=key, timeout=4.0)
            res = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            self.lbl_key_status.setText("✓ Clave válida y lista para usar")
            self.lbl_key_status.setStyleSheet("color: #10B981;")
        except Exception as e:
            err_str = str(e)
            if "invalid_api_key" in err_str or "401" in err_str:
                self.lbl_key_status.setText("❌ Clave rechazada (no válida)")
            elif "rate_limit" in err_str or "429" in err_str:
                self.lbl_key_status.setText("✓ Clave conectada correctamente")
                self.lbl_key_status.setStyleSheet("color: #10B981;")
            else:
                self.lbl_key_status.setText(f"❌ Error al conectar: {err_str[:40]}")
            self.lbl_key_status.setStyleSheet("color: #EF4444;" if "❌" in self.lbl_key_status.text() else "color: #10B981;")
        finally:
            self.btn_verify.setEnabled(True)

    def _save_settings(self):
        """Guarda los valores en .env y emite la señal de actualización."""
        key = self.input_key.text().strip()
        if not key or not key.startswith("gsk_"):
            QMessageBox.warning(
                self,
                "Clave Requerida",
                "Por favor introduce una API Key válida de Groq (comienza con 'gsk_').\nPuedes obtenerla gratis en https://console.groq.com/keys",
            )
            return

        device_id = self.combo_device.currentData()
        target_lang = self.combo_lang.currentData()
        timeout_ms = self.combo_timeout.currentData() or "1800"

        # Guardar en archivo .env
        env_path = get_env_path()
        env_content = {}
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_content[k.strip()] = v.strip()

        # Actualizar valores
        env_content["GROQ_API_KEY"] = key
        env_content["AUDIO_DEVICE_ID"] = device_id or ""
        env_content["TARGET_LANGUAGE"] = target_lang or "auto"
        env_content["VAD_SILENCE_TIMEOUT_MS"] = str(timeout_ms)
        env_content["STT_MODE"] = "cloud"
        env_content["LLM_PROVIDER"] = "groq"

        # Escribir archivo actualizado
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("# LiveCopilot - Configuración de Variables de Entorno\n\n")
                for k, v in env_content.items():
                    f.write(f"{k}={v}\n")
            logger.info("Configuración guardada en %s", env_path)
        except Exception as e:
            logger.error("Error al guardar .env: %s", e)

        # Actualizar en variables de proceso
        os.environ["GROQ_API_KEY"] = key
        os.environ["AUDIO_DEVICE_ID"] = device_id or ""
        os.environ["TARGET_LANGUAGE"] = target_lang or "auto"
        os.environ["VAD_SILENCE_TIMEOUT_MS"] = str(timeout_ms)

        payload = {
            "groq_api_key": key,
            "device_id": device_id,
            "target_language": target_lang,
            "vad_silence_timeout_ms": timeout_ms,
        }
        self.settings_saved.emit(payload)
        self.accept()

    # Arrastre de la ventana
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._is_dragging = False
