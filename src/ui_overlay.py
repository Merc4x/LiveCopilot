"""
LiveCopilot - Minimalist Floating Heads-Up Display (PyQt6)
Frameless, semi-transparent, pinned on top, draggable HUD
with guaranteed 60 FPS performance, dynamic multilingual response switching,
and prominent, transparent logo branding.
"""

import logging
import os
import sys
from typing import Callable, Optional

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QLinearGradient
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QProgressBar,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("LiveCopilot.UI")

# Clean, professional language list without emojis
AVAILABLE_RESPONSE_LANGUAGES = [
    ("English", "English"),
    ("Chinese (Mandarin)", "Chinese (Mandarin)"),
    ("Spanish", "Spanish"),
    ("French", "French"),
    ("German", "German"),
    ("Italian", "Italian"),
    ("Portuguese", "Portuguese"),
    ("Japanese", "Japanese"),
    ("Korean", "Korean"),
    ("Russian", "Russian"),
    ("Arabic", "Arabic"),
    ("Hindi", "Hindi"),
]


def get_app_icon() -> QIcon:
    """Load application icon from assets, prioritizing multi-resolution Windows .ico."""
    assets_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"
    )
    ico_path = os.path.join(assets_dir, "app.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)

    icon_path = os.path.join(assets_dir, "icon.png")
    if os.path.exists(icon_path):
        return QIcon(icon_path)

    # Clean geometric vector fallback
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QColor(14, 16, 20, 245))
    painter.setPen(QPen(QColor(0, 245, 212), 2))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    painter.setPen(QPen(QColor(0, 245, 212), 3))
    painter.drawLine(14, 32, 22, 18)
    painter.drawLine(22, 18, 30, 46)
    painter.drawLine(30, 46, 38, 24)
    painter.drawLine(38, 24, 44, 36)
    painter.drawLine(44, 36, 50, 32)
    painter.end()
    return QIcon(pixmap)


class FloatingHUD(QWidget):
    """
    Semi-transparent floating HUD for projecting real-time speech transcription
    and AI conversational suggestions with instant multilingual target switching.
    """

    # Signals for decoupled communication
    request_toggle_pause = pyqtSignal()
    request_clear = pyqtSignal()
    request_open_settings = pyqtSignal()
    request_change_response_language = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # Drag tracking
        self._is_dragging = False
        self._drag_position = QPoint()

        # Internal state
        self.is_paused = False
        self.always_on_top = True

        self._init_window_properties()
        self._init_styles()
        self._build_ui()

    def _init_window_properties(self):
        """Configure window flags for a frameless floating HUD visible in the Windows taskbar."""
        self.setWindowTitle("LiveCopilot")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(480, 360)
        self.resize(580, 460)

        # Position at the bottom-right corner by default (optimal for desktop co-pilots)
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = screen_geo.width() - self.width() - 40
            y = screen_geo.height() - self.height() - 60
            self.move(max(20, x), max(20, y))

    def _force_windows_taskbar(self):
        """Ensure Windows explicitly registers the frameless window in the taskbar with the custom icon."""
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_TOOLWINDOW = 0x00000080
                user32 = ctypes.windll.user32
                ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ex_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010
                )

                # Send WM_SETICON directly to HWND so Windows taskbar & Alt+Tab display the custom icon
                ico_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "app.ico"
                )
                if os.path.exists(ico_path):
                    user32.LoadImageW.argtypes = [
                        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                        ctypes.c_int, ctypes.c_int, ctypes.c_uint
                    ]
                    user32.LoadImageW.restype = ctypes.c_void_p
                    user32.SendMessageW.argtypes = [
                        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p
                    ]
                    user32.SendMessageW.restype = ctypes.c_void_p

                    # IMAGE_ICON = 1, LR_LOADFROMFILE = 0x0010
                    hicon_big = user32.LoadImageW(None, ico_path, 1, 32, 32, 0x0010)
                    hicon_small = user32.LoadImageW(None, ico_path, 1, 16, 16, 0x0010)

                    # WM_SETICON = 0x0080 (1 = ICON_BIG for taskbar/Alt-Tab, 0 = ICON_SMALL)
                    if hicon_big:
                        user32.SendMessageW(hwnd, 0x0080, 1, hicon_big)
                        if hasattr(user32, "SetClassLongPtrW"):
                            user32.SetClassLongPtrW(hwnd, -14, hicon_big)
                    if hicon_small:
                        user32.SendMessageW(hwnd, 0x0080, 0, hicon_small)
                        if hasattr(user32, "SetClassLongPtrW"):
                            user32.SetClassLongPtrW(hwnd, -34, hicon_small)
            except Exception as e:
                logger.debug("Error enforcing Windows taskbar presence: %s", e)

    def showEvent(self, event):
        super().showEvent(event)
        self._force_windows_taskbar()

    def _init_styles(self):
        """CSS stylesheets featuring modern dark glassmorphism, clean typography, and neon cyan accents."""
        self.setStyleSheet("""
            QWidget#MainContainer {
                background-color: rgba(14, 16, 20, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 14px;
            }
            
            /* Header Bar */
            QFrame#HeaderBar {
                background: transparent;
                border-bottom: 1px solid rgba(255, 255, 255, 0.06);
                padding: 2px 2px 8px 2px;
            }
            
            QLabel#AppTitle {
                color: #FFFFFF;
                font-family: 'Segoe UI', 'Inter', -apple-system, sans-serif;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 1.5px;
            }
            
            /* Hardware/State LED Indicator */
            QLabel#StatusIndicator {
                min-width: 7px;
                max-width: 7px;
                min-height: 7px;
                max-height: 7px;
                border-radius: 3px;
                background-color: #00F5D4;
            }
            
            QLabel#StatusText {
                color: #8E95A5;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 10.5px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            
            /* Header Action Buttons */
            QPushButton.HeaderBtn {
                background-color: rgba(255, 255, 255, 0.04);
                color: #B5BCC9;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 5px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.6px;
                padding: 4px 9px;
            }
            QPushButton.HeaderBtn:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
                border-color: rgba(255, 255, 255, 0.16);
            }
            QPushButton#BtnPause {
                color: #00F5D4;
                border-color: rgba(0, 245, 212, 0.25);
            }
            QPushButton#BtnPause:hover {
                background-color: rgba(0, 245, 212, 0.15);
            }
            QPushButton#BtnMinimize:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
            }
            QPushButton#CloseBtn:hover {
                background-color: rgba(239, 68, 68, 0.85);
                color: #FFFFFF;
                border-color: rgba(239, 68, 68, 0.9);
            }
            
            /* Content Cards */
            QFrame#CardHeard {
                background-color: rgba(22, 25, 31, 0.75);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 9px;
                padding: 8px 12px;
            }
            
            QFrame#CardSuggestion {
                background-color: rgba(0, 245, 212, 0.04);
                border: 1px solid rgba(0, 245, 212, 0.28);
                border-radius: 9px;
                padding: 10px 12px;
            }
            
            QLabel#LabelHeardTag {
                color: #7E8695;
                font-family: 'Segoe UI', sans-serif;
                font-size: 9.5px;
                font-weight: 800;
                letter-spacing: 1.0px;
            }
            
            QLabel#TextHeardContent {
                color: #E6E8EC;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                line-height: 1.45;
            }
            
            QLabel#TextHeardTrans {
                color: #7DD3FC;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                font-style: italic;
                margin-top: 3px;
            }
            
            QLabel#LabelSugTag {
                color: #00F5D4;
                font-family: 'Segoe UI', sans-serif;
                font-size: 9.5px;
                font-weight: 800;
                letter-spacing: 1.0px;
            }
            
            /* Language Switcher Selector in Suggestion Header */
            QComboBox#ComboRespLang {
                background-color: rgba(0, 245, 212, 0.09);
                border: 1px solid rgba(0, 245, 212, 0.32);
                border-radius: 5px;
                color: #00F5D4;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10.5px;
                font-weight: 700;
                padding: 2px 8px;
                min-width: 100px;
            }
            QComboBox#ComboRespLang:hover {
                background-color: rgba(0, 245, 212, 0.18);
                border: 1px solid rgba(0, 245, 212, 0.55);
            }
            QComboBox#ComboRespLang QAbstractItemView {
                background-color: #12141A;
                color: #FFFFFF;
                selection-background-color: #00F5D4;
                selection-color: #0A1014;
                border: 1px solid rgba(0, 245, 212, 0.35);
                border-radius: 6px;
                padding: 4px;
            }
            
            QLabel#TextSugContent {
                color: #00F5D4;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14.5px;
                font-weight: 700;
                line-height: 1.4;
            }
            
            QLabel#TextSugPron {
                color: #FACC15;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                font-weight: 700;
                font-style: italic;
                background-color: rgba(250, 204, 21, 0.07);
                border: 1px solid rgba(250, 204, 21, 0.20);
                border-radius: 5px;
                padding: 4px 8px;
                margin-top: 3px;
            }
            
            QLabel#TextSugEs {
                color: #9CA3AF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11.5px;
                margin-top: 2px;
            }
            
            /* Audio VU Meter */
            QProgressBar#AudioMeter {
                background-color: rgba(255, 255, 255, 0.06);
                border-radius: 2px;
                border: none;
                max-height: 2px;
            }
            QProgressBar#AudioMeter::chunk {
                background-color: #00F5D4;
                border-radius: 2px;
            }
            
            /* Footer Metrics */
            QLabel#FooterMetrics {
                color: #5A6272;
                font-family: 'Consolas', monospace;
                font-size: 9.5px;
            }
            
            QPushButton#CopyBtn {
                background-color: rgba(0, 245, 212, 0.10);
                color: #00F5D4;
                border: 1px solid rgba(0, 245, 212, 0.25);
                border-radius: 4px;
                font-size: 9.5px;
                font-weight: 700;
                letter-spacing: 0.5px;
                padding: 2px 7px;
            }
            QPushButton#CopyBtn:hover {
                background-color: rgba(0, 245, 212, 0.22);
                color: #FFFFFF;
            }
        """)

    def _build_ui(self):
        """Construct visual component hierarchy for the HUD."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Outer container with drop shadow
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 190))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(14, 12, 14, 12)
        container_layout.setSpacing(8)

        # -------------------------------------------------------------
        # 1. Top Header Bar (Branding, State LED & Window Controls)
        # -------------------------------------------------------------
        self.header_frame = QFrame(self.container)
        self.header_frame.setObjectName("HeaderBar")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(8)

        # Brand Layout: Prominent Logo + Crisp Title
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(8)

        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png"
        )
        if os.path.exists(logo_path):
            self.lbl_logo = QLabel(self.header_frame)
            pix = QPixmap(logo_path).scaled(
                32, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_logo.setPixmap(pix)
            self.lbl_logo.setFixedSize(32, 26)
            brand_layout.addWidget(self.lbl_logo)

        self.title_label = QLabel("LIVECOPILOT", self.header_frame)
        self.title_label.setObjectName("AppTitle")
        brand_layout.addWidget(self.title_label)

        # Status Layout: Hardware LED + Text
        status_layout = QHBoxLayout()
        status_layout.setSpacing(5)
        self.status_dot = QLabel(self.header_frame)
        self.status_dot.setObjectName("StatusIndicator")
        self.status_label = QLabel("LISTENING", self.header_frame)
        self.status_label.setObjectName("StatusText")
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_label)

        header_layout.addLayout(brand_layout)
        header_layout.addSpacing(6)
        header_layout.addLayout(status_layout)
        header_layout.addStretch()

        # Pause / Resume Button
        self.btn_pause = QPushButton("PAUSE", self.header_frame)
        self.btn_pause.setObjectName("BtnPause")
        self.btn_pause.setProperty("class", "HeaderBtn")
        self.btn_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pause.clicked.connect(self._toggle_pause_action)

        # Clear Button
        self.btn_clear = QPushButton("CLEAR", self.header_frame)
        self.btn_clear.setObjectName("BtnClear")
        self.btn_clear.setProperty("class", "HeaderBtn")
        self.btn_clear.setToolTip("Clear current display")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_content)

        # Settings Button
        self.btn_settings = QPushButton("SETTINGS", self.header_frame)
        self.btn_settings.setObjectName("BtnSettings")
        self.btn_settings.setProperty("class", "HeaderBtn")
        self.btn_settings.setToolTip("Configure API keys and audio device")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.request_open_settings.emit)

        # Minimize Button
        self.btn_minimize = QPushButton("—", self.header_frame)
        self.btn_minimize.setObjectName("BtnMinimize")
        self.btn_minimize.setProperty("class", "HeaderBtn")
        self.btn_minimize.setToolTip("Minimize to taskbar")
        self.btn_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimize.clicked.connect(self.showMinimized)

        # Close Button
        self.btn_close = QPushButton("✕", self.header_frame)
        self.btn_close.setObjectName("CloseBtn")
        self.btn_close.setProperty("class", "HeaderBtn")
        self.btn_close.setToolTip("Exit LiveCopilot")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)

        header_layout.addWidget(self.btn_pause)
        header_layout.addWidget(self.btn_clear)
        header_layout.addWidget(self.btn_settings)
        header_layout.addWidget(self.btn_minimize)
        header_layout.addWidget(self.btn_close)

        container_layout.addWidget(self.header_frame)

        # Ultra-slim Audio VU Level Meter
        self.audio_meter = QProgressBar(self.container)
        self.audio_meter.setObjectName("AudioMeter")
        self.audio_meter.setRange(0, 100)
        self.audio_meter.setValue(0)
        self.audio_meter.setTextVisible(False)
        container_layout.addWidget(self.audio_meter)

        # -------------------------------------------------------------
        # 2. Block 1: Heard Speech (Original & Translation)
        # -------------------------------------------------------------
        self.card_heard = QFrame(self.container)
        self.card_heard.setObjectName("CardHeard")
        layout_heard = QVBoxLayout(self.card_heard)
        layout_heard.setContentsMargins(10, 8, 10, 8)
        layout_heard.setSpacing(4)

        heard_tag_layout = QHBoxLayout()
        self.label_heard_tag = QLabel("INCOMING AUDIO · TRANSCRIPTION", self.card_heard)
        self.label_heard_tag.setObjectName("LabelHeardTag")
        heard_tag_layout.addWidget(self.label_heard_tag)
        heard_tag_layout.addStretch()

        self.text_heard = QLabel("Waiting for system audio stream...", self.card_heard)
        self.text_heard.setObjectName("TextHeardContent")
        self.text_heard.setWordWrap(True)
        self.text_heard.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.text_heard_trans = QLabel("", self.card_heard)
        self.text_heard_trans.setObjectName("TextHeardTrans")
        self.text_heard_trans.setWordWrap(True)
        self.text_heard_trans.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_heard_trans.setVisible(False)

        layout_heard.addLayout(heard_tag_layout)
        layout_heard.addWidget(self.text_heard)
        layout_heard.addWidget(self.text_heard_trans)
        container_layout.addWidget(self.card_heard)

        # -------------------------------------------------------------
        # 3. Block 2: AI Suggestion (Response + Phonetics + Meaning)
        # -------------------------------------------------------------
        self.card_sug = QFrame(self.container)
        self.card_sug.setObjectName("CardSuggestion")
        layout_sug = QVBoxLayout(self.card_sug)
        layout_sug.setContentsMargins(10, 8, 10, 8)
        layout_sug.setSpacing(5)

        sug_tag_layout = QHBoxLayout()
        sug_tag_layout.setSpacing(6)

        self.label_sug_tag = QLabel("SUGGESTED RESPONSE", self.card_sug)
        self.label_sug_tag.setObjectName("LabelSugTag")

        # Instant target response language selector
        self.combo_resp_lang = QComboBox(self.card_sug)
        self.combo_resp_lang.setObjectName("ComboRespLang")
        self.combo_resp_lang.setToolTip("Select target response language")
        for label, lang_value in AVAILABLE_RESPONSE_LANGUAGES:
            self.combo_resp_lang.addItem(label, lang_value)
        self.combo_resp_lang.currentIndexChanged.connect(self._on_response_language_changed)

        self.btn_copy = QPushButton("COPY", self.card_sug)
        self.btn_copy.setObjectName("CopyBtn")
        self.btn_copy.setToolTip("Copy suggested phrase to clipboard")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy_suggestion_to_clipboard)

        sug_tag_layout.addWidget(self.label_sug_tag)
        sug_tag_layout.addWidget(self.combo_resp_lang)
        sug_tag_layout.addStretch()
        sug_tag_layout.addWidget(self.btn_copy)

        # 1. Suggested phrase to speak
        self.text_sug = QLabel("Response suggestions will appear here...", self.card_sug)
        self.text_sug.setObjectName("TextSugContent")
        self.text_sug.setWordWrap(True)
        self.text_sug.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # 2. Phonetic pronunciation guide
        self.text_sug_pron = QLabel("", self.card_sug)
        self.text_sug_pron.setObjectName("TextSugPron")
        self.text_sug_pron.setWordWrap(True)
        self.text_sug_pron.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_sug_pron.setVisible(False)

        # 3. Meaning / translation in native language
        self.text_sug_es = QLabel("", self.card_sug)
        self.text_sug_es.setObjectName("TextSugEs")
        self.text_sug_es.setWordWrap(True)
        self.text_sug_es.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_sug_es.setVisible(False)

        layout_sug.addLayout(sug_tag_layout)
        layout_sug.addWidget(self.text_sug)
        layout_sug.addWidget(self.text_sug_pron)
        layout_sug.addWidget(self.text_sug_es)
        container_layout.addWidget(self.card_sug)

        # -------------------------------------------------------------
        # 4. Footer Status & Latency Metrics
        # -------------------------------------------------------------
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(2, 2, 2, 0)
        self.footer_metrics = QLabel("STT: -- ms | LLM: -- ms", self.container)
        self.footer_metrics.setObjectName("FooterMetrics")
        footer_layout.addWidget(self.footer_metrics)
        footer_layout.addStretch()

        # Window resize grip (bottom right)
        self.size_grip = QSizeGrip(self.container)
        self.size_grip.setStyleSheet("width: 12px; height: 12px;")
        footer_layout.addWidget(self.size_grip)

        container_layout.addLayout(footer_layout)
        root_layout.addWidget(self.container)

    # -----------------------------------------------------------------
    # Language Selection Slot
    # -----------------------------------------------------------------
    def _on_response_language_changed(self, index: int):
        """Triggered when the user changes the response language dropdown."""
        lang_value = self.combo_resp_lang.itemData(index)
        if lang_value:
            logger.info("User switched response language to: %s", lang_value)
            self.request_change_response_language.emit(lang_value)

    def set_active_response_language(self, lang_value: str):
        """Set the active response language in the dropdown programmatically."""
        for idx in range(self.combo_resp_lang.count()):
            data = self.combo_resp_lang.itemData(idx)
            if data and data.lower() == lang_value.lower():
                self.combo_resp_lang.blockSignals(True)
                self.combo_resp_lang.setCurrentIndex(idx)
                self.combo_resp_lang.blockSignals(False)
                break

    # -----------------------------------------------------------------
    # Window Drag Management
    # -----------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() < 60:
                self._is_dragging = True
                self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._is_dragging = False

    # -----------------------------------------------------------------
    # Slots & UI Updates
    # -----------------------------------------------------------------
    def update_transcription(self, text: str, latency_ms: float = 0.0, engine_name: str = ""):
        """Update Block 1 with the transcribed audio and prepare translation state."""
        if not text:
            return
        self.text_heard.setText(text)
        self.text_heard_trans.setText("Translating...")
        self.text_heard_trans.setVisible(True)
        if latency_ms > 0:
            self._update_footer(stt_ms=latency_ms, engine=engine_name)

    def update_suggestion(self, data, latency_ms: float = 0.0, provider_name: str = ""):
        """
        Update Block 2 with the suggested response, phonetic pronunciation,
        and meaning, while updating the translation in Block 1.
        """
        if not data:
            return

        if isinstance(data, dict):
            # 1. Translation of what was heard
            heard_trans = (data.get("heard_trans") or data.get("trad_escuchado", "")).strip()
            if heard_trans:
                self.text_heard_trans.setText(f"Translation: {heard_trans}")
                self.text_heard_trans.setVisible(True)
            else:
                self.text_heard_trans.setVisible(False)

            # 2. Suggested phrase to speak
            response = (data.get("response") or data.get("respuesta", "")).strip()
            if response:
                self.text_sug.setText(response)

            # 3. Phonetic pronunciation guide
            pron = (data.get("pronunciation") or data.get("pronunciacion", "")).strip()
            if pron:
                self.text_sug_pron.setText(f"Pronounce: \"{pron}\"")
                self.text_sug_pron.setVisible(True)
            else:
                self.text_sug_pron.setVisible(False)

            # 4. Meaning of the response
            meaning = (data.get("meaning") or data.get("trad_respuesta", "")).strip()
            if meaning:
                self.text_sug_es.setText(f"Meaning: {meaning}")
                self.text_sug_es.setVisible(True)
            else:
                self.text_sug_es.setVisible(False)

        else:
            self.text_sug.setText(str(data))
            self.text_sug_pron.setVisible(False)
            self.text_sug_es.setVisible(False)

        if latency_ms > 0:
            self._update_footer(llm_ms=latency_ms, provider=provider_name)

    def update_audio_level(self, level: float):
        """Update audio VU meter bar value (0.0 to 1.0)."""
        val = int(min(1.0, max(0.0, level)) * 100)
        self.audio_meter.setValue(val)

    def set_status(self, status: str, state_type: str = "active"):
        """
        Update visual status indicator:
        state_type: 'active' (cyan), 'processing' (amber), 'paused' (gray), 'error' (red)
        """
        self.status_label.setText(status.upper())
        if state_type == "active":
            self.status_dot.setStyleSheet("background-color: #00F5D4;")
            self.status_label.setStyleSheet("color: #00F5D4;")
        elif state_type == "processing":
            self.status_dot.setStyleSheet("background-color: #F59E0B;")
            self.status_label.setStyleSheet("color: #F59E0B;")
        elif state_type == "paused":
            self.status_dot.setStyleSheet("background-color: #6B7280;")
            self.status_label.setStyleSheet("color: #6B7280;")
        elif state_type == "error":
            self.status_dot.setStyleSheet("background-color: #EF4444;")
            self.status_label.setStyleSheet("color: #EF4444;")

    def _update_footer(
        self,
        stt_ms: Optional[float] = None,
        llm_ms: Optional[float] = None,
        engine: str = "",
        provider: str = "",
    ):
        """Update inference performance metrics in milliseconds."""
        current = self.footer_metrics.text()
        stt_part = f"STT: {int(stt_ms)}ms ({engine})" if stt_ms is not None else ""
        llm_part = f"LLM: {int(llm_ms)}ms ({provider})" if llm_ms is not None else ""

        parts = []
        if stt_part:
            parts.append(stt_part)
        if llm_part:
            parts.append(llm_part)

        if parts:
            self.footer_metrics.setText(" | ".join(parts))

    def _toggle_pause_action(self):
        """Toggle audio listening pause state."""
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.setText("RESUME")
            self.btn_pause.setStyleSheet("color: #10B981; border-color: rgba(16, 185, 129, 0.4);")
            self.set_status("Paused", "paused")
        else:
            self.btn_pause.setText("PAUSE")
            self.btn_pause.setStyleSheet("")
            self.set_status("Listening", "active")

        self.request_toggle_pause.emit()

    def _clear_content(self):
        """Clear all content text cards."""
        self.text_heard.setText("Waiting for system audio stream...")
        self.text_heard_trans.setText("")
        self.text_heard_trans.setVisible(False)

        self.text_sug.setText("Response suggestions will appear here...")
        self.text_sug_pron.setText("")
        self.text_sug_pron.setVisible(False)
        self.text_sug_es.setText("")
        self.text_sug_es.setVisible(False)

        self.request_clear.emit()

    def _copy_suggestion_to_clipboard(self):
        """Copy active response suggestion to Windows clipboard."""
        text = self.text_sug.text().strip()
        if text and text != "Response suggestions will appear here...":
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.btn_copy.setText("COPIED")
            QTimer.singleShot(1500, lambda: self.btn_copy.setText("COPY"))
