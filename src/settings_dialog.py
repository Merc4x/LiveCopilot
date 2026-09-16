"""
LiveCopilot - Visual Settings Dialog (PyQt6)
Enables users to configure their Groq API Key with real-time live validation,
select their audio output device (headphones, speakers), and choose primary native language
and response language without editing files or running terminal commands.
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

SUPPORTED_NATIVE_LANGUAGES = [
    ("🇪🇸 Spanish (Español) - Default", "Spanish"),
    ("🇺🇸 English", "English"),
    ("🇧🇷 Portuguese (Português)", "Portuguese"),
    ("🇫🇷 French (Français)", "French"),
    ("🇩🇪 German (Deutsch)", "German"),
    ("🇮🇹 Italian (Italiano)", "Italian"),
    ("🇯🇵 Japanese (日本語)", "Japanese"),
    ("🇨🇳 Chinese (中文)", "Chinese"),
]

SUPPORTED_RESPONSE_LANGUAGES = [
    ("🇺🇸 English - Default", "English"),
    ("🇨🇳 Chinese (Mandarin)", "Chinese (Mandarin)"),
    ("🇪🇸 Spanish", "Spanish"),
    ("🇫🇷 French", "French"),
    ("🇩🇪 German", "German"),
    ("🇮🇹 Italian", "Italian"),
    ("🇵🇹 Portuguese", "Portuguese"),
    ("🇯🇵 Japanese", "Japanese"),
    ("🇰🇷 Korean", "Korean"),
    ("🇷🇺 Russian", "Russian"),
    ("🇸🇦 Arabic", "Arabic"),
]


def get_env_path() -> str:
    """Return the absolute path to the .env file in both development and frozen executable modes."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, ".env")


class SettingsDialog(QDialog):
    """Configuration modal window with a dark glassmorphism design."""

    # Signal emitted when settings are saved successfully
    settings_saved = pyqtSignal(dict)

    def __init__(self, parent=None, is_first_run: bool = False):
        super().__init__(parent)
        self.is_first_run = is_first_run

        self._init_window()
        self._init_styles()
        self._build_ui()
        self._load_current_values()

    def _init_window(self):
        """Configure modal window properties and behavior."""
        self.setWindowTitle("LiveCopilot Settings")
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
        self.setFixedSize(520, 620)

        # Drag tracking
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
        """CSS stylesheets featuring dark glassmorphism and mint green accent."""
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
                font-size: 11.5px;
                font-weight: 600;
                margin-top: 4px;
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
            
            QComboBox {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11.5px;
                padding: 5px 9px;
            }
            QComboBox:focus {
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
        """Construct visual controls and field layout."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Main frame with perimeter shadow
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(18, 14, 18, 14)
        container_layout.setSpacing(8)

        # -------------------------------------------------------------
        # Header
        # -------------------------------------------------------------
        header_frame = QFrame(self.container)
        header_frame.setObjectName("HeaderBar")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 4)

        header_info = QVBoxLayout()
        header_info.setSpacing(2)
        title_text = "⚡ Welcome to LiveCopilot" if self.is_first_run else "⚙️ LiveCopilot Settings"
        lbl_title = QLabel(title_text, header_frame)
        lbl_title.setObjectName("TitleLabel")
        lbl_sub = QLabel("Configure your Groq API Key, audio device, and multilingual preferences.", header_frame)
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
        # Field 1: GROQ_API_KEY
        # -------------------------------------------------------------
        lbl_api_key = QLabel("🔑 Groq API Key (Free):", self.container)
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
        self.btn_eye.setToolTip("Show / Hide API Key")
        self.btn_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_eye.clicked.connect(self._toggle_password_visibility)
        key_row.addWidget(self.btn_eye)

        self.btn_verify = QPushButton("Verify", self.container)
        self.btn_verify.setObjectName("BtnVerifyKey")
        self.btn_verify.setToolTip("Test connection with Groq")
        self.btn_verify.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_verify.clicked.connect(self._verify_api_key)
        key_row.addWidget(self.btn_verify)

        container_layout.addLayout(key_row)

        # Key verification status & assistance link
        key_help_row = QHBoxLayout()
        self.lbl_key_status = QLabel("", self.container)
        self.lbl_key_status.setObjectName("StatusKeyLabel")
        key_help_row.addWidget(self.lbl_key_status)
        key_help_row.addStretch()

        lbl_link = QLabel(
            '<a style="color: #38BDF8; text-decoration: none;" href="https://console.groq.com/keys">👉 Get free API key here</a>',
            self.container,
        )
        lbl_link.setObjectName("HelpLink")
        lbl_link.setOpenExternalLinks(True)
        key_help_row.addWidget(lbl_link)
        container_layout.addLayout(key_help_row)

        # -------------------------------------------------------------
        # Field 2: Audio Output Device (Speakers / Headphones Loopback)
        # -------------------------------------------------------------
        lbl_device = QLabel("🎧 Audio Output to Capture (Meetings / Calls / Video):", self.container)
        lbl_device.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_device)

        self.combo_device = QComboBox(self.container)
        self.combo_device.setObjectName("DeviceCombo")
        container_layout.addWidget(self.combo_device)

        # -------------------------------------------------------------
        # Field 3: User Native / Primary Language (You Understand)
        # -------------------------------------------------------------
        lbl_native_lang = QLabel("🗣️ Your Native / Primary Language (You Understand):", self.container)
        lbl_native_lang.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_native_lang)

        self.combo_native_lang = QComboBox(self.container)
        self.combo_native_lang.setObjectName("NativeLangCombo")
        for label, val in SUPPORTED_NATIVE_LANGUAGES:
            self.combo_native_lang.addItem(label, val)
        container_layout.addWidget(self.combo_native_lang)

        # -------------------------------------------------------------
        # Field 4: Default Response Language (You Speak Back In)
        # -------------------------------------------------------------
        lbl_resp_lang = QLabel("🌐 Default Target Response Language (You Speak):", self.container)
        lbl_resp_lang.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_resp_lang)

        self.combo_resp_lang = QComboBox(self.container)
        self.combo_resp_lang.setObjectName("RespLangCombo")
        for label, val in SUPPORTED_RESPONSE_LANGUAGES:
            self.combo_resp_lang.addItem(label, val)
        container_layout.addWidget(self.combo_resp_lang)

        # -------------------------------------------------------------
        # Field 5: Speech Pause Duration (VAD Silence Timeout)
        # -------------------------------------------------------------
        lbl_timeout = QLabel("⏱️ Speech Pause Duration (VAD Silence Timeout):", self.container)
        lbl_timeout.setProperty("class", "FieldLabel")
        container_layout.addWidget(lbl_timeout)

        self.combo_timeout = QComboBox(self.container)
        self.combo_timeout.setObjectName("TimeoutCombo")
        self.combo_timeout.addItem("Long paragraphs / Full speech (1.8s pause) [Recommended]", "1800")
        self.combo_timeout.addItem("Continuous mode / Lectures & webinars (2.5s pause)", "2500")
        self.combo_timeout.addItem("Standard sentences (1.4s pause)", "1400")
        self.combo_timeout.addItem("Short fast phrases (0.8s pause)", "800")
        container_layout.addWidget(self.combo_timeout)

        container_layout.addStretch()

        # -------------------------------------------------------------
        # Action Buttons
        # -------------------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.addStretch()

        if not self.is_first_run:
            self.btn_cancel = QPushButton("Cancel", self.container)
            self.btn_cancel.setObjectName("BtnCancel")
            self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_cancel.clicked.connect(self.reject)
            btn_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("✓ Save & Launch" if self.is_first_run else "✓ Save Changes", self.container)
        self.btn_save.setObjectName("BtnSave")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self._save_settings)
        btn_layout.addWidget(self.btn_save)

        container_layout.addLayout(btn_layout)
        root_layout.addWidget(self.container)

    def _load_current_values(self):
        """Load current configuration values from .env file and scan audio devices."""
        env_path = get_env_path()
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)

        current_key = os.getenv("GROQ_API_KEY", "").strip()
        if current_key and not current_key.startswith("PASTE_YOUR"):
            self.input_key.setText(current_key)

        current_device_id = os.getenv("AUDIO_DEVICE_ID", "").strip()
        current_native_lang = os.getenv("USER_NATIVE_LANG", "Spanish").strip()
        current_resp_lang = os.getenv("RESPONSE_LANG", "English").strip()

        # Populate audio output devices
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
            self.combo_device.addItem("Default System Audio (WASAPI Loopback)", "")

        # Select native language
        for idx in range(self.combo_native_lang.count()):
            if self.combo_native_lang.itemData(idx).lower() == current_native_lang.lower():
                self.combo_native_lang.setCurrentIndex(idx)
                break

        # Select response language
        for idx in range(self.combo_resp_lang.count()):
            data = self.combo_resp_lang.itemData(idx)
            if data and (data.lower() == current_resp_lang.lower() or current_resp_lang.lower() in data.lower()):
                self.combo_resp_lang.setCurrentIndex(idx)
                break

        # Select VAD timeout option
        current_timeout = os.getenv("VAD_SILENCE_TIMEOUT_MS", "1800").strip()
        for idx in range(self.combo_timeout.count()):
            if self.combo_timeout.itemData(idx) == current_timeout:
                self.combo_timeout.setCurrentIndex(idx)
                break

    def _toggle_password_visibility(self):
        """Toggle API key visibility mode."""
        if self.input_key.echoMode() == QLineEdit.EchoMode.Password:
            self.input_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_eye.setText("🔒")
        else:
            self.input_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_eye.setText("👁️")

    def _verify_api_key(self):
        """Validate the Groq API key in real-time."""
        key = self.input_key.text().strip()
        if not key or not key.startswith("gsk_"):
            self.lbl_key_status.setText("❌ Key must start with 'gsk_'")
            self.lbl_key_status.setStyleSheet("color: #EF4444;")
            return

        self.lbl_key_status.setText("⏳ Verifying with Groq...")
        self.lbl_key_status.setStyleSheet("color: #FBBF24;")
        self.btn_verify.setEnabled(False)

        try:
            from groq import Groq
            client = Groq(api_key=key, timeout=4.0)
            client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            self.lbl_key_status.setText("✓ Key verified and ready to use")
            self.lbl_key_status.setStyleSheet("color: #10B981;")
        except Exception as e:
            err_str = str(e)
            if "invalid_api_key" in err_str or "401" in err_str:
                self.lbl_key_status.setText("❌ Key rejected (invalid API key)")
            elif "rate_limit" in err_str or "429" in err_str:
                self.lbl_key_status.setText("✓ Key connected successfully")
                self.lbl_key_status.setStyleSheet("color: #10B981;")
            else:
                self.lbl_key_status.setText(f"❌ Connection error: {err_str[:40]}")
            self.lbl_key_status.setStyleSheet("color: #EF4444;" if "❌" in self.lbl_key_status.text() else "color: #10B981;")
        finally:
            self.btn_verify.setEnabled(True)

    def _save_settings(self):
        """Save updated values into .env and emit settings_saved signal."""
        key = self.input_key.text().strip()
        if not key or not key.startswith("gsk_"):
            QMessageBox.warning(
                self,
                "API Key Required",
                "Please enter a valid Groq API Key (starts with 'gsk_').\nYou can obtain one for free at https://console.groq.com/keys",
            )
            return

        device_id = self.combo_device.currentData()
        native_lang = self.combo_native_lang.currentData() or "Spanish"
        resp_lang = self.combo_resp_lang.currentData() or "English"
        timeout_ms = self.combo_timeout.currentData() or "1800"

        # Update or create .env file
        env_path = get_env_path()
        env_content = {}
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_content[k.strip()] = v.strip()

        # Update values
        env_content["GROQ_API_KEY"] = key
        env_content["AUDIO_DEVICE_ID"] = device_id or ""
        env_content["USER_NATIVE_LANG"] = native_lang
        env_content["RESPONSE_LANG"] = resp_lang
        env_content["TARGET_LANGUAGE"] = "auto"
        env_content["VAD_SILENCE_TIMEOUT_MS"] = str(timeout_ms)
        env_content["STT_MODE"] = "cloud"
        env_content["LLM_PROVIDER"] = "groq"

        # Write updated file
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("# LiveCopilot - Environment Configuration\n\n")
                for k, v in env_content.items():
                    f.write(f"{k}={v}\n")
            logger.info("Configuration saved successfully to %s", env_path)
        except Exception as e:
            logger.error("Failed to save .env: %s", e)

        # Update active process environment
        os.environ["GROQ_API_KEY"] = key
        os.environ["AUDIO_DEVICE_ID"] = device_id or ""
        os.environ["USER_NATIVE_LANG"] = native_lang
        os.environ["RESPONSE_LANG"] = resp_lang
        os.environ["TARGET_LANGUAGE"] = "auto"
        os.environ["VAD_SILENCE_TIMEOUT_MS"] = str(timeout_ms)

        payload = {
            "groq_api_key": key,
            "device_id": device_id,
            "user_native_lang": native_lang,
            "response_lang": resp_lang,
            "target_language": "auto",
            "vad_silence_timeout_ms": timeout_ms,
        }
        self.settings_saved.emit(payload)
        self.accept()

    # Drag window handlers
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
