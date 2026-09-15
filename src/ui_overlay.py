"""
LiveCopilot - Interfaz de Usuario (HUD Flotante Minimalista en PyQt6)
Ventana sin bordes, semi-transparente, fijada al frente, arrastrable y
con rendimiento a 60 FPS garantizado.
"""

import logging
import sys
from typing import Callable, Optional

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QLinearGradient
from PyQt6.QtWidgets import (
    QApplication,
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


def get_app_icon() -> QIcon:
    """Genera un icono nítido de alta resolución para la barra de tareas de Windows."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fondo redondeado oscuro con borde cian brillante
    painter.setBrush(QColor(18, 18, 18, 240))
    painter.setPen(QPen(QColor(0, 245, 212), 2))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    # Símbolo ⚡
    painter.setPen(QPen(QColor(0, 245, 212)))
    font = QFont("Segoe UI Emoji", 26)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "⚡")
    painter.end()
    return QIcon(pixmap)


class FloatingHUD(QWidget):
    """
    HUD Flotante semi-transparente para proyección de transcripciones
    y sugerencias de IA en tiempo real.
    """

    # Señales para comunicación desacoplada
    request_toggle_pause = pyqtSignal()
    request_clear = pyqtSignal()
    request_open_settings = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Control de arrastre
        self._is_dragging = False
        self._drag_position = QPoint()

        # Estado interno
        self.is_paused = False
        self.always_on_top = True

        self._init_window_properties()
        self._init_styles()
        self._build_ui()

    def _init_window_properties(self):
        """Configuración de flags para HUD flotante visible en la barra de tareas de Windows."""
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

        # Ubicar en la esquina inferior derecha por defecto (típico para copilotos)
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = screen_geo.width() - self.width() - 40
            y = screen_geo.height() - self.height() - 60
            self.move(max(20, x), max(20, y))

    def _force_windows_taskbar(self):
        """Asegura que Windows registre la ventana frameless explícitamente en la barra de tareas."""
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
            except Exception as e:
                logger.debug(f"Error forzando presencia en barra de tareas: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        self._force_windows_taskbar()

    def _init_styles(self):
        """Estilos CSS con paleta moderna oscura, acento cian/menta y glassmorphism."""
        self.setStyleSheet("""
            QWidget#MainContainer {
                background-color: rgba(18, 18, 18, 0.90);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 16px;
            }
            
            /* Barra Superior */
            QFrame#HeaderBar {
                background: transparent;
                border-bottom: 1px solid rgba(255, 255, 255, 0.07);
                padding: 2px 4px 6px 4px;
            }
            
            QLabel#AppTitle {
                color: #FFFFFF;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            
            QLabel#StatusDot {
                font-size: 11px;
            }
            
            QLabel#StatusText {
                color: #A0A0A0;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 11px;
                font-weight: 500;
            }
            
            /* Botones de Cabecera */
            QPushButton.HeaderBtn {
                background-color: rgba(255, 255, 255, 0.05);
                color: #CCCCCC;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                padding: 4px 8px;
                font-weight: bold;
            }
            QPushButton.HeaderBtn:hover {
                background-color: rgba(255, 255, 255, 0.14);
                color: #FFFFFF;
            }
            QPushButton#BtnMinimize:hover {
                background-color: rgba(0, 245, 212, 0.20);
                color: #00F5D4;
                border: 1px solid rgba(0, 245, 212, 0.4);
            }
            QPushButton#CloseBtn:hover {
                background-color: rgba(239, 68, 68, 0.8);
                color: #FFFFFF;
                border: 1px solid rgba(239, 68, 68, 0.9);
            }
            
            /* Bloques de Contenido */
            QFrame#CardHeard {
                background-color: rgba(25, 28, 32, 0.70);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 10px;
                padding: 8px 12px;
            }
            
            QFrame#CardSuggestion {
                background-color: rgba(0, 245, 212, 0.05);
                border: 1px solid rgba(0, 245, 212, 0.30);
                border-radius: 10px;
                padding: 10px 12px;
            }
            
            QLabel#LabelHeardTag {
                color: #9CA3AF;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }
            
            QLabel#TextHeardContent {
                color: #F3F4F6;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                line-height: 1.4;
            }
            
            QLabel#TextHeardTrans {
                color: #93C5FD;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                font-style: italic;
                margin-top: 3px;
            }
            
            QLabel#LabelSugTag {
                color: #00F5D4;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10px;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }
            
            QLabel#TextSugContent {
                color: #00F5D4;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14.5px;
                font-weight: 700;
                line-height: 1.4;
            }
            
            QLabel#TextSugPron {
                color: #FDE047;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12.5px;
                font-weight: 700;
                font-style: italic;
                background-color: rgba(253, 224, 71, 0.08);
                border: 1px solid rgba(253, 224, 71, 0.22);
                border-radius: 6px;
                padding: 4px 8px;
                margin-top: 4px;
            }
            
            QLabel#TextSugEs {
                color: #D1D5DB;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11.5px;
                margin-top: 2px;
            }
            
            /* Medidor de audio */
            QProgressBar#AudioMeter {
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 2px;
                border: none;
                max-height: 3px;
            }
            QProgressBar#AudioMeter::chunk {
                background-color: #00F5D4;
                border-radius: 2px;
            }
            
            /* Pie de estado */
            QLabel#FooterMetrics {
                color: #6B7280;
                font-family: 'Consolas', monospace;
                font-size: 10px;
            }
            
            QPushButton#CopyBtn {
                background-color: rgba(0, 245, 212, 0.12);
                color: #00F5D4;
                border: 1px solid rgba(0, 245, 212, 0.25);
                border-radius: 5px;
                font-size: 10px;
                font-weight: 600;
                padding: 2px 6px;
            }
            QPushButton#CopyBtn:hover {
                background-color: rgba(0, 245, 212, 0.25);
                color: #FFFFFF;
            }
        """)

    def _build_ui(self):
        """Construye la jerarquía visual del HUD."""
        # Layout raíz
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Contenedor con efecto de sombra perimetral
        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(14, 12, 14, 12)
        container_layout.setSpacing(8)

        # -------------------------------------------------------------
        # 1. Barra Superior (Header & Controls)
        # -------------------------------------------------------------
        self.header_frame = QFrame(self.container)
        self.header_frame.setObjectName("HeaderBar")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(8)

        # Título y LED de estado
        self.status_dot = QLabel("🟢", self.header_frame)
        self.status_dot.setObjectName("StatusDot")

        self.title_label = QLabel("⚡ LiveCopilot", self.header_frame)
        self.title_label.setObjectName("AppTitle")

        self.status_label = QLabel("Escuchando...", self.header_frame)
        self.status_label.setObjectName("StatusText")

        header_layout.addWidget(self.status_dot)
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()

        # Botón de Pausa / Reanudar
        self.btn_pause = QPushButton("⏸ Pausar", self.header_frame)
        self.btn_pause.setObjectName("BtnPause")
        self.btn_pause.setProperty("class", "HeaderBtn")
        self.btn_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pause.clicked.connect(self._toggle_pause_action)

        # Botón Limpiar
        self.btn_clear = QPushButton("🧹", self.header_frame)
        self.btn_clear.setObjectName("BtnClear")
        self.btn_clear.setProperty("class", "HeaderBtn")
        self.btn_clear.setToolTip("Limpiar texto actual")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_content)

        # Botón Ajustes
        self.btn_settings = QPushButton("⚙️", self.header_frame)
        self.btn_settings.setObjectName("BtnSettings")
        self.btn_settings.setProperty("class", "HeaderBtn")
        self.btn_settings.setToolTip("Configuración (API Key y Dispositivo de Audio)")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.request_open_settings.emit)

        # Botón Minimizar
        self.btn_minimize = QPushButton("🗕", self.header_frame)
        self.btn_minimize.setObjectName("BtnMinimize")
        self.btn_minimize.setProperty("class", "HeaderBtn")
        self.btn_minimize.setToolTip("Minimizar a la barra de tareas")
        self.btn_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimize.clicked.connect(self.showMinimized)

        # Botón Cerrar
        self.btn_close = QPushButton("✕", self.header_frame)
        self.btn_close.setObjectName("CloseBtn")
        self.btn_close.setProperty("class", "HeaderBtn")
        self.btn_close.setToolTip("Cerrar LiveCopilot")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)

        header_layout.addWidget(self.btn_pause)
        header_layout.addWidget(self.btn_clear)
        header_layout.addWidget(self.btn_settings)
        header_layout.addWidget(self.btn_minimize)
        header_layout.addWidget(self.btn_close)

        container_layout.addWidget(self.header_frame)

        # Mini Vúmetro de Audio
        self.audio_meter = QProgressBar(self.container)
        self.audio_meter.setObjectName("AudioMeter")
        self.audio_meter.setRange(0, 100)
        self.audio_meter.setValue(0)
        self.audio_meter.setTextVisible(False)
        container_layout.addWidget(self.audio_meter)

        # -------------------------------------------------------------
        # 2. Bloque 1: Escuchado (Gris Claro) + Traducción
        # -------------------------------------------------------------
        self.card_heard = QFrame(self.container)
        self.card_heard.setObjectName("CardHeard")
        layout_heard = QVBoxLayout(self.card_heard)
        layout_heard.setContentsMargins(10, 8, 10, 8)
        layout_heard.setSpacing(4)

        heard_tag_layout = QHBoxLayout()
        self.label_heard_tag = QLabel("🎧 ESCUCHADO (ORIGINAL & TRADUCCIÓN)", self.card_heard)
        self.label_heard_tag.setObjectName("LabelHeardTag")
        heard_tag_layout.addWidget(self.label_heard_tag)
        heard_tag_layout.addStretch()

        self.text_heard = QLabel("Esperando audio del sistema (WASAPI)...", self.card_heard)
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
        # 3. Bloque 2: Sugerencia IA (Inglés + Fonética + Significado)
        # -------------------------------------------------------------
        self.card_sug = QFrame(self.container)
        self.card_sug.setObjectName("CardSuggestion")
        layout_sug = QVBoxLayout(self.card_sug)
        layout_sug.setContentsMargins(10, 8, 10, 8)
        layout_sug.setSpacing(5)

        sug_tag_layout = QHBoxLayout()
        self.label_sug_tag = QLabel("💡 CÓMO RESPONDER (INGLÉS & PRONUNCIACIÓN)", self.card_sug)
        self.label_sug_tag.setObjectName("LabelSugTag")

        self.btn_copy = QPushButton("Copiar", self.card_sug)
        self.btn_copy.setObjectName("CopyBtn")
        self.btn_copy.setToolTip("Copiar frase en inglés al portapapeles")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy_suggestion_to_clipboard)

        sug_tag_layout.addWidget(self.label_sug_tag)
        sug_tag_layout.addStretch()
        sug_tag_layout.addWidget(self.btn_copy)

        # 1. Frase en inglés para decir
        self.text_sug = QLabel("Las respuestas rápidas aparecerán aquí...", self.card_sug)
        self.text_sug.setObjectName("TextSugContent")
        self.text_sug.setWordWrap(True)
        self.text_sug.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # 2. Guía fonética aproximada
        self.text_sug_pron = QLabel("", self.card_sug)
        self.text_sug_pron.setObjectName("TextSugPron")
        self.text_sug_pron.setWordWrap(True)
        self.text_sug_pron.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_sug_pron.setVisible(False)

        # 3. Significado en español
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
        # 4. Pie de estado y métricas de latencia
        # -------------------------------------------------------------
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(2, 2, 2, 0)
        self.footer_metrics = QLabel("STT: -- ms | LLM: -- ms", self.container)
        self.footer_metrics.setObjectName("FooterMetrics")
        footer_layout.addWidget(self.footer_metrics)
        footer_layout.addStretch()

        # Agarre para redimensionar libremente la ventana con el ratón
        self.size_grip = QSizeGrip(self.container)
        self.size_grip.setStyleSheet("width: 12px; height: 12px;")
        footer_layout.addWidget(self.size_grip)

        container_layout.addLayout(footer_layout)
        root_layout.addWidget(self.container)

    # -----------------------------------------------------------------
    # Gestión de Arrastre de Ventana (Drag & Drop desde cualquier punto del header)
    # -----------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Arrastrable desde cualquier zona superior o fondo del contenedor
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
    # Slots y Actualizaciones de la Interfaz
    # -----------------------------------------------------------------
    def update_transcription(self, text: str, latency_ms: float = 0.0, engine_name: str = ""):
        """Actualiza el Bloque 1 con el audio escuchado y prepara la traducción."""
        if not text:
            return
        self.text_heard.setText(text)
        self.text_heard_trans.setText("🌐 Traduciendo...")
        self.text_heard_trans.setVisible(True)
        if latency_ms > 0:
            self._update_footer(stt_ms=latency_ms, engine=engine_name)

    def update_suggestion(self, data, latency_ms: float = 0.0, provider_name: str = ""):
        """
        Actualiza el Bloque 2 con la respuesta sugerida, la pronunciación fonética
        y el significado, además de actualizar la traducción en el Bloque 1.
        """
        if not data:
            return

        if isinstance(data, dict):
            # 1. Traducción al español de lo que se escuchó
            trad_escuchado = data.get("trad_escuchado", "").strip()
            if trad_escuchado:
                self.text_heard_trans.setText(f"🌐 Trad: {trad_escuchado}")
                self.text_heard_trans.setVisible(True)
            else:
                self.text_heard_trans.setVisible(False)

            # 2. Frase para responder en inglés
            respuesta = data.get("respuesta", "").strip()
            if respuesta:
                self.text_sug.setText(respuesta)

            # 3. Guía de pronunciación fonética en español
            pron = data.get("pronunciacion", "").strip()
            if pron:
                self.text_sug_pron.setText(f"🗣️ Pronuncia: \"{pron}\"")
                self.text_sug_pron.setVisible(True)
            else:
                self.text_sug_pron.setVisible(False)

            # 4. Significado en español de lo que va a responder
            trad_resp = data.get("trad_respuesta", "").strip()
            if trad_resp:
                self.text_sug_es.setText(f"🌐 Significado: {trad_resp}")
                self.text_sug_es.setVisible(True)
            else:
                self.text_sug_es.setVisible(False)

        else:
            # Fallback si llega string simple
            self.text_sug.setText(str(data))
            self.text_sug_pron.setVisible(False)
            self.text_sug_es.setVisible(False)

        if latency_ms > 0:
            self._update_footer(llm_ms=latency_ms, provider=provider_name)

    def update_audio_level(self, level: float):
        """Actualiza el valor del medidor VU de audio (0.0 a 1.0)."""
        # Suavizado en escala porcentual 0-100
        val = int(min(1.0, max(0.0, level)) * 100)
        self.audio_meter.setValue(val)

    def set_status(self, status: str, state_type: str = "active"):
        """
        Actualiza el estado visual:
        state_type: 'active' (verde), 'processing' (ámbar), 'paused' (gris)
        """
        self.status_label.setText(status)
        if state_type == "active":
            self.status_dot.setText("🟢")
            self.status_label.setStyleSheet("color: #00F5D4;")
        elif state_type == "processing":
            self.status_dot.setText("🟡")
            self.status_label.setStyleSheet("color: #F59E0B;")
        elif state_type == "paused":
            self.status_dot.setText("⏸️")
            self.status_label.setStyleSheet("color: #9CA3AF;")
        elif state_type == "error":
            self.status_dot.setText("🔴")
            self.status_label.setStyleSheet("color: #EF4444;")

    def _update_footer(
        self,
        stt_ms: Optional[float] = None,
        llm_ms: Optional[float] = None,
        engine: str = "",
        provider: str = "",
    ):
        """Actualiza las métricas de rendimiento en milisegundos."""
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
        """Alterna el estado de pausa de la escucha."""
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.setText("▶ Reanudar")
            self.btn_pause.setStyleSheet("color: #10B981; border-color: rgba(16, 185, 129, 0.4);")
            self.set_status("Pausado", "paused")
        else:
            self.btn_pause.setText("⏸ Pausar")
            self.btn_pause.setStyleSheet("")
            self.set_status("Escuchando...", "active")

        self.request_toggle_pause.emit()

    def _clear_content(self):
        """Limpia las tarjetas de texto."""
        self.text_heard.setText("Esperando audio del sistema...")
        self.text_heard_trans.setText("")
        self.text_heard_trans.setVisible(False)

        self.text_sug.setText("Las respuestas rápidas aparecerán aquí...")
        self.text_sug_pron.setText("")
        self.text_sug_pron.setVisible(False)
        self.text_sug_es.setText("")
        self.text_sug_es.setVisible(False)

        self.request_clear.emit()

    def _copy_suggestion_to_clipboard(self):
        """Copia la sugerencia activa al portapapeles de Windows."""
        text = self.text_sug.text().strip()
        if text and text != "Las respuestas rápidas aparecerán aquí...":
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.btn_copy.setText("✓ Copiado")
            QTimer.singleShot(1500, lambda: self.btn_copy.setText("Copiar"))
