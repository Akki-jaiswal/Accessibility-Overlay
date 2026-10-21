import sys
import os
import io
import wave
import json
import threading
import time
import re
import ctypes
from ctypes import wintypes
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QScrollArea, QFrame, QTextBrowser,
    QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect, QInputDialog,
    QSizePolicy, QSlider
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject, QTimer, QBuffer, QIODevice, QEvent
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QGuiApplication, QAction, QCursor
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PIL import Image

try:
    from markdown_it import MarkdownIt
    md_parser = MarkdownIt()
except ImportError:
    md_parser = None

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_AVAILABLE = True
except ImportError:
    SPEECH_AVAILABLE = False

try:
    import pyaudiowpatch as pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    try:
        import pyaudio
        PYAUDIO_AVAILABLE = True
    except ImportError:
        pyaudio = None
        PYAUDIO_AVAILABLE = False

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LOCAL_SERVER_NAME = "AuraAssistantSingleInstanceServer"


def load_config():
    defaults = {
        "GEMINI_API_KEY": "",
        "PERSONA": "I am Akshay, a 3rd year BTech Computer Science student focusing on backend architecture, data analysis, and building AI tools. When answering, be direct, concise, and structured.",
        "TRANSPARENCY": 65,
        "AUDIO_SOURCE": "dual"
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")


class WorkerSignals(QObject):
    stream_chunk = pyqtSignal(str)
    stream_finished = pyqtSignal()
    voice_transcribed = pyqtSignal(str, object)
    voice_status_signal = pyqtSignal(str, str)
    voice_finished_signal = pyqtSignal()
    show_window_signal = pyqtSignal()
    toggle_window_signal = pyqtSignal()
    trigger_camera_signal = pyqtSignal()
    trigger_voice_signal = pyqtSignal()
    trigger_transparency_signal = pyqtSignal()
    trigger_type_through_signal = pyqtSignal()
    transparency_toggled_signal = pyqtSignal(bool)
    type_through_toggled_signal = pyqtSignal(bool)


# --- Precision Painted Toggle Switch with Animated Knob ---
class CompactToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, label_text, is_checked=False, parent=None):
        super().__init__(parent)
        self.is_checked = is_checked
        self.label_text = label_text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(68, 34)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
            event.accept()
        else:
            super().mousePressEvent(event)

    def toggle(self):
        self.is_checked = not self.is_checked
        self.update()
        self.toggled.emit(self.is_checked)

    def set_checked(self, checked):
        if self.is_checked != checked:
            self.is_checked = checked
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pill_w, pill_h = 28, 14
        pill_x = (self.width() - pill_w) // 2
        pill_y = 2

        if self.is_checked:
            # Active Blue Pill
            painter.setBrush(QColor("#2563eb"))
            painter.setPen(QColor("#3b82f6"))
            painter.drawRoundedRect(pill_x, pill_y, pill_w, pill_h, 7, 7)

            # White Knob on Right
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(pill_x + pill_w - 12, pill_y + 2, 10, 10)

            # Label Text (Sky Blue)
            painter.setPen(QColor("#38bdf8"))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        else:
            # Inactive Slate Pill
            painter.setBrush(QColor("#334155"))
            painter.setPen(QColor("#475569"))
            painter.drawRoundedRect(pill_x, pill_y, pill_w, pill_h, 7, 7)

            # White Knob on Left
            painter.setBrush(QColor("#cbd5e1"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(pill_x + 2, pill_y + 2, 10, 10)

            # Label Text (Muted Slate)
            painter.setPen(QColor("#94a3b8"))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Medium))

        text_rect = self.rect().adjusted(0, 18, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.label_text)
        painter.end()


# --- Floating Quick Action Tooltip (Explain / What / How) ---
class SelectionActionPopup(QFrame):
    action_triggered = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QPushButton {
                background: transparent;
                border: none;
                color: #334155;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                color: #0284c7;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        self.selected_text = ""

        self.btn_explain = QPushButton("ℹ Explain")
        self.btn_explain.clicked.connect(lambda: self.on_click("Explain this in detail:"))
        layout.addWidget(self.btn_explain)

        self.btn_what = QPushButton("? What?")
        self.btn_what.clicked.connect(lambda: self.on_click("What does this mean?"))
        layout.addWidget(self.btn_what)

        self.btn_how = QPushButton("⁝≡ How?")
        self.btn_how.clicked.connect(lambda: self.on_click("How does this work step-by-step?"))
        layout.addWidget(self.btn_how)

    def show_at(self, pos, text):
        self.selected_text = text
        self.move(pos)
        self.show()

    def on_click(self, prompt_prefix):
        self.hide()
        full_prompt = f"{prompt_prefix}\n\n\"{self.selected_text}\""
        self.action_triggered.emit(prompt_prefix, full_prompt)


# --- Modern In-App Auto Mode Confirmation Popup ---
class AutoModeConfirmDialog(QFrame):
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame#AutoDialogCard {
                background-color: #0b1329;
                border: 1px solid #334155;
                border-radius: 14px;
            }
        """)
        self.setObjectName("AutoDialogCard")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header with icon
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        
        icon_label = QLabel("🎙️")
        icon_label.setStyleSheet("font-size: 18px; background: transparent; border: none;")
        header_layout.addWidget(icon_label)
        
        title_label = QLabel("Enable Auto Meeting Mode?")
        title_label.setStyleSheet("color: #ffffff; font-size: 13.5px; font-weight: bold; background: transparent; border: none;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Body description
        desc_label = QLabel(
            "Aura will continuously listen to your meeting/system audio in the background and automatically generate real-time answers when technical or interview questions are heard.<br><br>"
            "💡 <b>Quick Control:</b> Click the center <b>Mic button</b> (🎙️) at any time to pause or resume listening."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #cbd5e1; font-size: 12px; line-height: 1.45; background: transparent; border: none;")
        layout.addWidget(desc_label)

        # Buttons layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1e293b;
                color: #f8fafc;
                border-color: #475569;
            }
        """)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("Enable Auto Mode")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_confirm.clicked.connect(self._on_confirm)
        btn_layout.addWidget(self.btn_confirm)

        layout.addLayout(btn_layout)

    def show_centered(self, parent_widget):
        self.setParent(parent_widget)
        card_w = min(390, max(300, parent_widget.width() - 36))
        self.setFixedWidth(card_w)
        self.adjustSize()
        x = (parent_widget.width() - self.width()) // 2
        y = (parent_widget.height() - self.height()) // 2 - 20
        self.move(max(10, x), max(10, y))
        self.show()
        self.raise_()

    def _on_confirm(self):
        self.hide()
        self.confirmed.emit()

    def _on_cancel(self):
        self.hide()
        self.cancelled.emit()


# --- Hover-Style Auto-Hide Transparency Slider ---
class HoverSliderBox(QFrame):
    def __init__(self, parent_assistant=None):
        super().__init__(parent_assistant)
        self.parent_assistant = parent_assistant
        self.setMouseTracking(True)
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 41, 59, 0.90);
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 1px 6px;
            }
        """)
        slider_inner = QHBoxLayout(self)
        slider_inner.setContentsMargins(4, 1, 4, 1)
        slider_inner.setSpacing(6)

        self.slider_icon = QLabel("◐")
        self.slider_icon.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent; border: none;")
        slider_inner.addWidget(self.slider_icon)

        self.trans_slider = QSlider(Qt.Orientation.Horizontal)
        self.trans_slider.setRange(0, 100)
        self.trans_slider.setValue(65)
        self.trans_slider.setFixedWidth(80)
        self.trans_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #475569;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }
        """)
        slider_inner.addWidget(self.trans_slider)

        self.percent_label = QLabel("65%")
        self.percent_label.setStyleSheet("color: #f8fafc; font-size: 10px; font-weight: bold; min-width: 24px; background: transparent; border: none;")
        slider_inner.addWidget(self.percent_label)

    def enterEvent(self, event):
        if self.parent_assistant:
            self.parent_assistant.on_slider_hover_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.parent_assistant:
            self.parent_assistant.on_slider_hover_leave()
        super().leaveEvent(event)


# --- Adaptive Static & Responsive Message Bubble ---
class MessageBubble(QWidget):
    def __init__(self, text="", is_user=False, is_image=False, pixmap=None, parent_assistant=None):
        super().__init__(parent_assistant)
        self.parent_assistant = parent_assistant
        self.raw_text = text
        self.is_user = is_user
        self.is_image = is_image
        
        # Outer container layout
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(0, 3, 0, 3)
        outer_layout.setSpacing(0)
        
        # Inner Card
        self.card = QFrame()
        self.card.setObjectName("BubbleCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)
        
        if is_image and pixmap:
            self.img_label = QLabel()
            scaled_pixmap = pixmap.scaledToWidth(220, Qt.TransformationMode.SmoothTransformation)
            
            badge_pixmap = QPixmap(scaled_pixmap.size())
            badge_pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(badge_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            from PyQt6.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(0, 0, scaled_pixmap.width(), scaled_pixmap.height(), 8, 8)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled_pixmap)
            painter.setClipping(False)
            
            painter.setPen(QColor("#334155"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(0, 0, scaled_pixmap.width() - 1, scaled_pixmap.height() - 1, 8, 8)
            
            badge_size = 20
            badge_x = scaled_pixmap.width() - badge_size - 6
            badge_y = scaled_pixmap.height() - badge_size - 6
            painter.setBrush(QColor("#10b981"))
            painter.setPen(QColor("#059669"))
            painter.drawEllipse(badge_x, badge_y, badge_size, badge_size)
            
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(badge_x, badge_y, badge_size, badge_size, Qt.AlignmentFlag.AlignCenter, "✓")
            painter.end()
            
            self.img_label.setPixmap(badge_pixmap)
            self.img_label.setStyleSheet("background: transparent; border: none;")
            card_layout.addWidget(self.img_label)

        self.text_browser = QTextBrowser()
        self.text_browser.setFrameShape(QFrame.Shape.NoFrame)
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setReadOnly(True)
        self.text_browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.viewport().setAutoFillBackground(False)
        self.text_browser.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.text_browser.document().setDocumentMargin(0)
        self.text_browser.selectionChanged.connect(self.on_selection_changed)
        self.text_browser.document().contentsChanged.connect(self.adjust_height)
        
        card_layout.addWidget(self.text_browser)

        # 3 Clean Follow-Up Action Chips (Explain More, Give Example, Simplify)
        if not is_user and not is_image:
            self.chips_widget = QWidget()
            chips_layout = QHBoxLayout(self.chips_widget)
            chips_layout.setContentsMargins(0, 4, 0, 0)
            chips_layout.setSpacing(6)
            chips_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

            chip_style = """
                QPushButton {
                    background-color: #1e293b;
                    color: #94a3b8;
                    border: 1px solid #334155;
                    border-radius: 9px;
                    padding: 3px 10px;
                    font-size: 11px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #334155;
                    color: #ffffff;
                    border-color: #475569;
                }
            """

            self.btn_more = QPushButton("Explain More")
            self.btn_more.setStyleSheet(chip_style)
            self.btn_more.clicked.connect(lambda: self.on_chip_clicked("Explain More"))
            chips_layout.addWidget(self.btn_more)

            self.btn_example = QPushButton("Give Example")
            self.btn_example.setStyleSheet(chip_style)
            self.btn_example.clicked.connect(lambda: self.on_chip_clicked("Give Example"))
            chips_layout.addWidget(self.btn_example)

            self.btn_simplify = QPushButton("Simplify")
            self.btn_simplify.setStyleSheet(chip_style)
            self.btn_simplify.clicked.connect(lambda: self.on_chip_clicked("Simplify"))
            chips_layout.addWidget(self.btn_simplify)

            card_layout.addWidget(self.chips_widget)
            self.chips_widget.hide()
        else:
            self.chips_widget = None

        if is_user:
            outer_layout.addStretch()
            outer_layout.addWidget(self.card)
        else:
            outer_layout.addWidget(self.card)
            outer_layout.addStretch()

        self.apply_transparency(parent_assistant.is_transparent_mode if parent_assistant else False)
        
        # Hide bubble initially if empty so no phantom box appears before text
        if not text and not is_image:
            self.hide()
            self.text_browser.setFixedHeight(0)
        else:
            self.update_content(text)

    def show_action_chips(self):
        if self.chips_widget and not self.is_user and not self.is_image:
            self.chips_widget.show()
            self.adjust_height()

    def on_chip_clicked(self, chip_type):
        if not self.parent_assistant:
            return
        if chip_type == "Give Example":
            prompt = "Give me a concrete walkthrough example of this."
        elif chip_type == "Explain More":
            prompt = "Can you explain this in more depth and detail?"
        else:
            prompt = "Simplify this into 1-2 clear, punchy spoken sentences."
        self.parent_assistant.on_selection_action(chip_type, prompt)

    def apply_transparency(self, is_transparent):
        if is_transparent:
            # Unified high-contrast dark card backdrop for all message bubbles
            self.card.setStyleSheet("""
                background-color: rgba(10, 15, 29, 0.92);
                border: 1px solid rgba(51, 65, 85, 0.55);
                border-radius: 12px;
            """)
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #ffffff;
                    font-size: 13px;
                    font-weight: 500;
                    font-family: 'Segoe UI', -apple-system, sans-serif;
                }
            """)
        else:
            # Unified solid dark card in standard mode
            self.card.setStyleSheet("""
                background-color: #0b1329;
                border: 1px solid #1e293b;
                border-radius: 12px;
            """)
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #f8fafc;
                    font-size: 13px;
                    font-family: 'Segoe UI', -apple-system, sans-serif;
                }
            """)
        if self.raw_text:
            self.text_browser.setHtml(self._render_html(self.raw_text, is_transparent))
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        self.card.update()
        self.adjust_height()

    def on_selection_changed(self):
        selected = self.text_browser.textCursor().selectedText().strip()
        if selected and len(selected) > 2 and self.parent_assistant:
            self.parent_assistant.clear_all_text_selections(except_browser=self.text_browser)
            cursor_pos = QCursor.pos()
            self.parent_assistant.selection_popup.show_at(QPoint(cursor_pos.x() - 60, cursor_pos.y() - 35), selected)
        elif self.parent_assistant:
            self.parent_assistant.selection_popup.hide()

    def _format_math(self, text):
        if not text:
            return ""
        
        # 1. Replace common LaTeX tokens with clean readable Unicode symbols
        replacements = [
            (r"\\times", "×"),
            (r"\\cdot", "·"),
            (r"\\leq", "≤"),
            (r"\\le\b", "≤"),
            (r"\\geq", "≥"),
            (r"\\ge\b", "≥"),
            (r"\\approx", "≈"),
            (r"\\neq", "≠"),
            (r"\\ne\b", "≠"),
            (r"\\pm", "±"),
            (r"\\infty", "∞"),
            (r"\\dots", "…"),
            (r"\\cdots", "⋯"),
            (r"\\ldots", "…"),
            (r"\\theta", "θ"),
            (r"\\Theta", "Θ"),
            (r"\\omega", "ω"),
            (r"\\Omega", "Ω"),
            (r"\\alpha", "α"),
            (r"\\beta", "β"),
            (r"\\gamma", "γ"),
            (r"\\lambda", "λ"),
            (r"\\pi", "π"),
            (r"\\sqrt\{([^}]+)\}", r"√(\1)"),
            (r"\\frac\{([^}]+)\}\{([^}]+)\}", r"(\1 / \2)"),
            (r"\\left\(", "("),
            (r"\\right\)", ")"),
            (r"\\left\[", "["),
            (r"\\right\]", "]"),
            (r"\\left\\{", "{"),
            (r"\\right\\}", "}"),
            (r"\\mathcal\{([A-Za-z])\}", r"\1"),
            (r"\\mathbf\{([^}]+)\}", r"**\1**"),
            (r"\\textbf\{([^}]+)\}", r"**\1**"),
            (r"\\textit\{([^}]+)\}", r"*\1*"),
            (r"\\text\{([^}]+)\}", r"\1"),
            (r"\\mathrm\{([^}]+)\}", r"\1"),
            (r"\\mathit\{([^}]+)\}", r"\1"),
            (r"\\log_2", "log₂"),
            (r"\\log", "log"),
            (r"\\ln", "ln"),
        ]
        for pat, repl in replacements:
            text = re.sub(pat, repl, text)

        # 2. Exponents to clean Unicode superscripts (e.g. M^2 -> M², 2^N -> 2ᴺ)
        sup_dict = {
            '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
            '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
            'n': 'ⁿ', 'N': 'ᴺ', 'k': 'ᵏ', 'K': 'ᴷ', 'm': 'ᵐ',
            'M': 'ᴹ', 'x': 'ˣ', 'i': 'ⁱ', 't': 'ᵗ', '+': '⁺', '-': '⁻'
        }
        def sup_replace(m):
            val = m.group(1) if m.group(1) is not None else m.group(2)
            return ''.join(sup_dict.get(c, c) for c in val)

        text = re.sub(r"\^\{([0-9a-zA-Z\+\-\(\)]+)\}", sup_replace, text)
        text = re.sub(r"\^([0-9a-zA-Z])\b", sup_replace, text)

        # 3. Clean inline & block math delimiters ($...$ / $$...$$)
        def math_delim_replace(m):
            inner = m.group(1).strip()
            if not inner:
                return ""
            # If it's a Big-O / Theta / Omega expression, format as bold
            if re.match(r"^[OΘΩ]\s*\(", inner):
                return f"**{inner}**"
            return inner

        text = re.sub(r"\$\$(.+?)\$\$", math_delim_replace, text, flags=re.DOTALL)
        text = re.sub(r"\$([^\$\n]+?)\$", math_delim_replace, text)
        text = text.replace(r"\$", "$")

        return text

    def _render_html(self, text, is_transparent=False):
        if not text:
            return ""
        
        # Convert raw LaTeX formulas into clean, human-readable Unicode & bold markdown
        clean_text = self._format_math(text)
        
        if md_parser:
            html = md_parser.render(clean_text)
        else:
            html = f"<p>{clean_text}</p>"
        
        text_color = "#ffffff" if is_transparent else "#f8fafc"
        code_bg = "rgba(0, 0, 0, 0.65)" if is_transparent else "#030712"
        pre_bg = "rgba(0, 0, 0, 0.75)" if is_transparent else "#030712"
        pre_border = "1px solid rgba(51, 65, 85, 0.50)" if is_transparent else "1px solid #1e293b"

        styled_html = f"""
        <style>
            body {{ color: {text_color}; font-family: 'Segoe UI', -apple-system, sans-serif; font-size: 13px; line-height: 1.45; margin: 0; padding: 0; word-wrap: break-word; }}
            p {{ margin: 0 0 4px 0; }}
            strong {{ color: #ffffff; font-weight: 700; }}
            h1, h2, h3, h4 {{ color: #ffffff; margin: 4px 0 2px 0; font-size: 13.5px; font-weight: bold; }}
            ul, ol {{ margin: 0 0 4px 14px; padding: 0; }}
            li {{ margin-bottom: 2px; }}
            code {{ background-color: {code_bg}; color: #7dd3fc; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace; font-size: 12px; }}
            pre {{ background-color: {pre_bg}; padding: 6px; border-radius: 6px; border: {pre_border}; margin: 4px 0; white-space: pre-wrap; word-wrap: break-word; }}
        </style>
        {html}
        """
        return styled_html

    def update_content(self, text):
        self.raw_text = text
        is_trans = self.parent_assistant.is_transparent_mode if self.parent_assistant else False
        if self.raw_text or self.is_image:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.card.setMinimumSize(0, 0)
            self.card.setMaximumSize(16777215, 16777215)
            self.show()
        self.apply_transparency(is_trans)
        self.text_browser.setHtml(self._render_html(text, is_trans))
        self.adjust_height()

    def append_text(self, new_text):
        was_empty = not self.raw_text
        self.raw_text += new_text
        is_trans = self.parent_assistant.is_transparent_mode if self.parent_assistant else False
        if was_empty and (self.raw_text or self.is_image):
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.card.setMinimumSize(0, 0)
            self.card.setMaximumSize(16777215, 16777215)
            self.show()
            self.apply_transparency(is_trans)
        self.text_browser.setHtml(self._render_html(self.raw_text, is_trans))
        self.adjust_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_height()

    def adjust_height(self):
        if not self.raw_text and not self.is_image:
            self.hide()
            return

        if self.parent_assistant and hasattr(self.parent_assistant, 'scroll_area'):
            vp_w = self.parent_assistant.scroll_area.viewport().width()
        else:
            vp_w = 540

        if vp_w <= 0:
            vp_w = 540

        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.card.setMinimumSize(0, 0)
        self.card.setMaximumSize(16777215, 16777215)

        if self.is_user:
            max_w = max(180, int(vp_w * 0.78))
            self.text_browser.document().setTextWidth(-1)
            ideal_w = int(self.text_browser.document().idealWidth()) + 18
            actual_text_w = min(max_w - 24, max(40, ideal_w))
            self.text_browser.setFixedWidth(actual_text_w)
            self.text_browser.document().setTextWidth(actual_text_w)
            doc_h = self.text_browser.document().documentLayout().documentSize().height()
            self.text_browser.setFixedHeight(int(doc_h) + 6)
            self.card.setFixedWidth(actual_text_w + 24)
        else:
            max_w = max(240, vp_w - 24)
            self.text_browser.document().setTextWidth(-1)
            ideal_w = int(self.text_browser.document().idealWidth()) + 24
            actual_card_w = min(max_w, max(120, ideal_w))
            actual_text_w = max(40, actual_card_w - 24)
            self.text_browser.setFixedWidth(actual_text_w)
            self.text_browser.document().setTextWidth(actual_text_w)
            doc_h = self.text_browser.document().documentLayout().documentSize().height()
            self.text_browser.setFixedHeight(int(doc_h) + 6)
            self.card.setFixedWidth(actual_card_w)

        chips_h = self.chips_widget.sizeHint().height() if (self.chips_widget and self.chips_widget.isVisible()) else 0
        img_h = self.img_label.height() if (self.is_image and hasattr(self, 'img_label')) else 0
        total_card_h = int(doc_h) + chips_h + img_h + 20
        self.card.setFixedHeight(total_card_h)
        self.setFixedHeight(total_card_h + 6)
        self.updateGeometry()


class NativeAssistant(QMainWindow):
    SIZES = [
        (600, 620),  # Stage 0: Standard Proportion (Matches Desktop Photos)
        (740, 780),  # Stage 1: Expanded
        (480, 520)   # Stage 2: Compact
    ]

    def __init__(self):
        super().__init__()
        self.drag_position = None
        self.is_transparent_mode = False
        self.is_click_through = False
        self.is_listening = False
        self.manual_voice_stop_requested = False
        self.active_voice_src = None
        self.is_auto_running = False
        self.is_auto_listening_paused = False
        self.auto_confirm_dialog = None
        self.is_generating = False
        self.stream_chunk_buffer = ""
        self.current_size_index = 0
        self.signals = WorkerSignals()
        self.current_ai_bubble = None
        self.config = load_config()
        self.client = None
        self.active_model_name = "gemini-flash-lite-latest"
        self.current_mode = "manual"
        self.opacity_val = self.config.get("TRANSPARENCY", 65)
        self.conversation_history = []

        # Smooth 45ms batch timer for streaming chunks (prevents flicker / glitches)
        self.stream_render_timer = QTimer(self)
        self.stream_render_timer.setInterval(45)
        self.stream_render_timer.timeout.connect(self._flush_stream_buffer)

        # 6-Second Auto-Hide Timer for the Slider
        self.slider_timer = QTimer(self)
        self.slider_timer.setInterval(6000)
        self.slider_timer.setSingleShot(True)
        self.slider_timer.timeout.connect(self.hide_slider_on_timeout)

        self.selection_popup = SelectionActionPopup()
        self.selection_popup.action_triggered.connect(self.on_selection_action)

        self._native_transparent_active = False
        self.type_through_timer = QTimer(self)
        self.type_through_timer.setInterval(40)
        self.type_through_timer.timeout.connect(self._poll_type_through_hover)

        self.init_ai()
        self.init_ui()
        self.init_tray()
        self.setup_hotkeys()

        # Connect signals
        self.signals.stream_chunk.connect(self.on_stream_chunk)
        self.signals.stream_finished.connect(self.on_stream_finished)
        self.signals.voice_transcribed.connect(self.on_voice_transcribed)
        self.signals.voice_status_signal.connect(self.on_voice_status)
        self.signals.voice_finished_signal.connect(self.on_voice_finished)
        self.signals.show_window_signal.connect(self.show_and_activate)
        self.signals.toggle_window_signal.connect(self.toggle_visibility)
        self.signals.trigger_camera_signal.connect(self.capture_screen_and_analyze)
        self.signals.trigger_voice_signal.connect(self.on_voice_button_clicked)
        self.signals.trigger_transparency_signal.connect(self.toggle_transparency)
        self.signals.trigger_type_through_signal.connect(self.toggle_type_through_global)
        self.signals.transparency_toggled_signal.connect(self.set_transparency)
        self.signals.type_through_toggled_signal.connect(self.set_type_through)

    def showEvent(self, event):
        super().showEvent(event)
        self._enforce_taskbar_hidden()

    def _enforce_taskbar_hidden(self):
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = wintypes.HWND(int(self.winId()))
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def init_ai(self):
        api_key = self.config.get("GEMINI_API_KEY", "")
        if api_key and GENAI_AVAILABLE:
            try:
                self.client = genai.Client(api_key=api_key)
                self.ai_ready = True
            except Exception as e:
                print(f"Failed to init Gemini API: {e}")
                self.ai_ready = False
        else:
            self.ai_ready = False

    def init_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        
        w, h = self.SIZES[0]
        self.resize(w, h)
        self.setMinimumSize(420, 480)

        self.main_container = QWidget(self)
        self.main_container.setObjectName("MainContainer")
        self.main_container.setMouseTracking(True)
        self.apply_container_style()

        # Shadow effect (disabled during transparent mode to prevent dark murky boxes)
        self.shadow_effect = QGraphicsDropShadowEffect(self)
        self.shadow_effect.setBlurRadius(24)
        self.shadow_effect.setColor(QColor(0, 0, 0, 220))
        self.shadow_effect.setOffset(0, 6)
        self.main_container.setGraphicsEffect(self.shadow_effect)

        container_layout = QVBoxLayout(self.main_container)
        container_layout.setContentsMargins(14, 10, 14, 12)
        container_layout.setSpacing(6)

        # ==========================================
        # 1. TOP HEADER BAR
        # ==========================================
        self.header = QWidget()
        self.header.setObjectName("HeaderWidget")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        # Bold Back Arrow (Clear conversation & reset context)
        self.back_btn = QPushButton("←")
        self.back_btn.setFixedSize(26, 26)
        self.back_btn.setToolTip("Clear conversation & reset context")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #94a3b8;
                font-size: 16px;
                font-weight: 900;
            }
            QPushButton:hover { color: #f8fafc; }
        """)
        self.back_btn.clicked.connect(self.clear_conversation)
        header_layout.addWidget(self.back_btn)

        # Mode Pill Switch [ Manual | Auto ]
        self.mode_container = QFrame()
        self.mode_container.setStyleSheet("""
            QFrame {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 1px;
            }
        """)
        mode_layout = QHBoxLayout(self.mode_container)
        mode_layout.setContentsMargins(2, 2, 2, 2)
        mode_layout.setSpacing(2)

        self.manual_btn = QPushButton("Manual")
        self.manual_btn.setCheckable(True)
        self.manual_btn.setChecked(True)
        self.manual_btn.setFixedHeight(22)
        self.manual_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                border: none;
                border-radius: 10px;
                padding: 0 10px;
            }
        """)
        self.manual_btn.clicked.connect(lambda: self.set_mode("manual"))
        mode_layout.addWidget(self.manual_btn)

        self.auto_btn = QPushButton("Auto")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setFixedHeight(22)
        self.auto_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                font-size: 11px;
                font-weight: bold;
                border: none;
                border-radius: 10px;
                padding: 0 10px;
            }
            QPushButton:hover { color: #f8fafc; }
        """)
        self.auto_btn.clicked.connect(self.on_auto_btn_clicked)
        mode_layout.addWidget(self.auto_btn)
        header_layout.addWidget(self.mode_container)

        self.filter_btn = QPushButton("🎛️")
        self.filter_btn.setToolTip("Customize Persona & System Instructions")
        self.filter_btn.setFixedSize(24, 24)
        self.filter_btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 12px; } QPushButton:hover { background: #334155; border-radius: 4px; }")
        self.filter_btn.clicked.connect(self.prompt_persona)
        header_layout.addWidget(self.filter_btn)

        header_layout.addStretch()

        # Center Brand Logo: ⚡ Aura
        self.brand_label = QLabel("⚡ Aura")
        self.brand_label.setStyleSheet("color: #cbd5e1; font-size: 13px; font-weight: bold; font-family: 'Segoe UI', sans-serif;")
        header_layout.addWidget(self.brand_label)

        header_layout.addStretch()

        # Window Controls: Minimize, 3-State Cycle, Close
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(22, 22)
        self.min_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #94a3b8; font-size: 12px; font-weight: bold; } QPushButton:hover { background-color: #334155; color: white; border-radius: 4px; }")
        self.min_btn.clicked.connect(self.hide)
        header_layout.addWidget(self.min_btn)

        self.max_btn = QPushButton("□")
        self.max_btn.setToolTip("Cycle Size (Standard / Expanded / Compact)")
        self.max_btn.setFixedSize(22, 22)
        self.max_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #94a3b8; font-size: 13px; font-weight: bold; } QPushButton:hover { background-color: #334155; color: #38bdf8; border-radius: 4px; }")
        self.max_btn.clicked.connect(self.cycle_window_size)
        header_layout.addWidget(self.max_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setToolTip("Quit Aura Completely")
        self.close_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #94a3b8; font-size: 12px; font-weight: bold; } QPushButton:hover { background-color: #ef4444; color: white; border-radius: 4px; }")
        self.close_btn.clicked.connect(self.quit_application)
        header_layout.addWidget(self.close_btn)

        container_layout.addWidget(self.header)

        # ==========================================
        # 2. CHAT SCROLL AREA
        # ==========================================
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 4px;
                margin: 0;
            }
            QScrollBar::handle:vertical { background: rgba(100, 116, 139, 0.5); border-radius: 2px; min-height: 20px; }
            QScrollBar::handle:vertical:hover { background: rgba(148, 163, 184, 0.8); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

        self.chat_widget = QWidget()
        self.chat_widget.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(4)
        self.chat_layout.addStretch()

        self.scroll_area.setWidget(self.chat_widget)
        container_layout.addWidget(self.scroll_area)

        # Floating Jump-to-Bottom Button
        self.scroll_bottom_btn = QPushButton("↓", self.main_container)
        self.scroll_bottom_btn.setFixedSize(26, 26)
        self.scroll_bottom_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(30, 41, 59, 0.85);
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 13px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
                border-color: #3b82f6;
            }
        """)
        self.scroll_bottom_btn.clicked.connect(self.scroll_to_bottom)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_value_changed)
        self.scroll_area.verticalScrollBar().rangeChanged.connect(self.on_scroll_range_changed)

        # ==========================================
        # 3. HELPER TEXT & AUTO-HIDE HOVER SLIDER BAR
        # ==========================================
        self.middle_helper_bar = QWidget()
        self.middle_helper_bar.setFixedHeight(28)
        self.middle_helper_bar.setMouseTracking(True)
        helper_layout = QHBoxLayout(self.middle_helper_bar)
        helper_layout.setContentsMargins(4, 0, 4, 0)
        helper_layout.setSpacing(8)

        # Centered hint label with Space keycap style
        self.hint_label = QLabel("Press <span style='background:#1e293b; padding:1px 5px; border-radius:4px; border:1px solid #334155; font-family:Consolas,monospace; font-weight:bold; color:#f8fafc;'>Space</span> or the mic to start")
        self.hint_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        helper_layout.addWidget(self.hint_label, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Live Status Pill (Generating answer... / Capturing screen...)
        self.status_pill = QLabel("Generating answer...")
        self.status_pill.setStyleSheet("""
            background-color: rgba(30, 41, 59, 0.90);
            color: #38bdf8;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10.5px;
            font-weight: 600;
        """)
        self.status_pill.hide()
        helper_layout.addWidget(self.status_pill, alignment=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

        helper_layout.addStretch()

        # Dynamic Hover-Style Transparency Slider (Shows for 6s on hover/touch)
        self.slider_box = HoverSliderBox(self)
        self.slider_box.setFixedHeight(26)
        self.slider_box.trans_slider.setValue(self.opacity_val)
        self.slider_box.percent_label.setText(f"{self.opacity_val}%")
        self.slider_box.trans_slider.valueChanged.connect(self.on_slider_changed)
        self.slider_box.hide()
        helper_layout.addWidget(self.slider_box, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        container_layout.addWidget(self.middle_helper_bar)

        # Optional Text Input Container (Shown when typing or on focus)
        self.input_card = QFrame()
        self.input_card.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
            }
        """)
        input_inner_layout = QHBoxLayout(self.input_card)
        input_inner_layout.setContentsMargins(10, 4, 6, 4)
        input_inner_layout.setSpacing(6)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type your message...")
        self.text_input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #f8fafc;
                font-size: 13px;
                padding: 4px;
            }
        """)
        self.text_input.returnPressed.connect(self.send_text_prompt)
        input_inner_layout.addWidget(self.text_input)

        self.send_btn = QPushButton("↑")
        self.send_btn.setFixedSize(26, 26)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border: none;
                border-radius: 13px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.send_btn.clicked.connect(self.send_text_prompt)
        input_inner_layout.addWidget(self.send_btn)

        container_layout.addWidget(self.input_card)

        # ==========================================
        # 4. BOTTOM DOCK (3-Column Perfectly Centered Layout)
        # ==========================================
        self.dock = QWidget()
        self.dock.setObjectName("DockWidget")
        self.dock.setFixedHeight(46)
        dock_layout = QHBoxLayout(self.dock)
        dock_layout.setContentsMargins(0, 0, 0, 0)
        dock_layout.setSpacing(0)

        # 1. Left Container (Key + Credits)
        self.dock_left = QWidget()
        dock_left_layout = QHBoxLayout(self.dock_left)
        dock_left_layout.setContentsMargins(0, 0, 0, 0)
        dock_left_layout.setSpacing(6)
        dock_left_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.key_btn = QPushButton("⚙️")
        self.key_btn.setToolTip("Settings / API Key")
        self.key_btn.setFixedSize(30, 30)
        self.key_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; border: 1px solid #334155; border-radius: 15px; font-size: 13px; }
            QPushButton:hover { background-color: #334155; }
        """)
        self.key_btn.clicked.connect(self.show_settings_menu)
        dock_left_layout.addWidget(self.key_btn)

        self.credits_badge = QLabel("🪙 Free")
        self.credits_badge.setStyleSheet("background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; padding: 2px 8px; font-size: 11px;")
        dock_left_layout.addWidget(self.credits_badge)

        # 2. Center Container (Action Buttons: Camera, Mic, Message)
        self.dock_center = QWidget()
        dock_center_layout = QHBoxLayout(self.dock_center)
        dock_center_layout.setContentsMargins(0, 0, 0, 0)
        dock_center_layout.setSpacing(8)
        dock_center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.cam_btn = QPushButton("📷")
        self.cam_btn.setToolTip("1-Click Screen Capture (Alt+S or F9)")
        self.cam_btn.setFixedSize(36, 36)
        self.cam_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 18px;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
        """)
        self.cam_btn.clicked.connect(self.capture_screen_and_analyze)
        dock_center_layout.addWidget(self.cam_btn)

        self.voice_btn = QPushButton("🎙️")
        self.voice_btn.setToolTip("Voice Dictation (Click to Start / Stop, or Alt+V / F7)")
        self.voice_btn.setFixedSize(42, 42)
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 21px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        self.voice_btn.clicked.connect(self.on_voice_button_clicked)
        dock_center_layout.addWidget(self.voice_btn)

        self.chat_btn = QPushButton("💬")
        self.chat_btn.setToolTip("Focus Message Input")
        self.chat_btn.setFixedSize(36, 36)
        self.chat_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 18px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
        """)
        self.chat_btn.clicked.connect(lambda: self.text_input.setFocus())
        dock_center_layout.addWidget(self.chat_btn)

        # 3. Right Container (Type-through Switch + Transparent Switch)
        self.dock_right = QWidget()
        dock_right_layout = QHBoxLayout(self.dock_right)
        dock_right_layout.setContentsMargins(0, 0, 0, 0)
        dock_right_layout.setSpacing(6)
        dock_right_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.type_through_switch = CompactToggleSwitch("Type-through", is_checked=False)
        self.type_through_switch.toggled.connect(self.set_type_through)
        self.type_through_switch.hide()
        dock_right_layout.addWidget(self.type_through_switch)

        self.trans_switch = CompactToggleSwitch("Transparent", is_checked=False)
        self.trans_switch.toggled.connect(self.set_transparency)
        dock_right_layout.addWidget(self.trans_switch)

        # Assemble Dock with Balanced 1-0-1 Stretch Factors
        dock_layout.addWidget(self.dock_left, 1)
        dock_layout.addWidget(self.dock_center, 0)
        dock_layout.addWidget(self.dock_right, 1)

        container_layout.addWidget(self.dock)
        self.setCentralWidget(self.main_container)

        # Install event filters for smooth header dragging and global click-anywhere deselection
        self.header.installEventFilter(self)
        self.dock.installEventFilter(self)
        self.brand_label.installEventFilter(self)
        QApplication.instance().installEventFilter(self)

        self.add_message("Hi! I'm Aura. I can help you silently in all meetings, interviews, and code tasks.", is_user=False)

    def clear_all_text_selections(self, except_browser=None):
        if hasattr(self, 'selection_popup') and self.selection_popup.isVisible():
            self.selection_popup.hide()
        if hasattr(self, 'chat_layout'):
            for i in range(self.chat_layout.count()):
                item = self.chat_layout.itemAt(i)
                widget = item.widget() if item else None
                if isinstance(widget, MessageBubble):
                    if widget.text_browser != except_browser:
                        cursor = widget.text_browser.textCursor()
                        if cursor.hasSelection():
                            cursor.clearSelection()
                            widget.text_browser.setTextCursor(cursor)

    def mousePressEvent(self, event):
        self.clear_all_text_selections()
        super().mousePressEvent(event)

    def eventFilter(self, source, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            is_popup = False
            if hasattr(self, 'selection_popup') and self.selection_popup.isVisible():
                if source == self.selection_popup or self.selection_popup.isAncestorOf(source):
                    is_popup = True
            
            if not is_popup:
                clicked_browser = None
                curr = source
                while curr:
                    if isinstance(curr, QTextBrowser):
                        clicked_browser = curr
                        break
                    curr = curr.parent() if hasattr(curr, 'parent') else None
                
                self.clear_all_text_selections(except_browser=clicked_browser)

        if source in (self.header, self.dock, self.brand_label):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return False
            elif event.type() == QEvent.Type.MouseMove and self.drag_position is not None and event.buttons() == Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self.drag_position)
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.drag_position = None
                return False
        return super().eventFilter(source, event)

    def apply_container_style(self):
        if self.is_transparent_mode:
            # Controlled strictly by slider: 0% transparent (solid dark 240) to 100% transparent (clear 8)
            transparency_factor = self.opacity_val / 100.0
            raw_alpha = int((1.0 - transparency_factor) * 240)
            bg_alpha = max(8, raw_alpha)

            border_alpha = max(0, min(200, int((1.0 - (self.opacity_val / 100.0)) * 180)))
            border_style = f"1px solid rgba(51, 65, 85, {border_alpha})" if border_alpha > 20 else "none"

            self.main_container.setStyleSheet(f"""
                QWidget#MainContainer {{
                    background-color: rgba(15, 23, 42, {bg_alpha});
                    border: {border_style};
                    border-radius: 14px;
                }}
            """)
        else:
            self.main_container.setStyleSheet("""
                QWidget#MainContainer {
                    background-color: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 14px;
                }
            """)

    def show_slider_with_timer(self):
        if self.is_transparent_mode:
            self.slider_box.show()
            self.slider_timer.start(6000)

    def hide_slider_on_timeout(self):
        if not self.is_transparent_mode:
            self.slider_box.hide()
            return
        if self.slider_box.underMouse() or self.slider_box.trans_slider.isSliderDown():
            self.slider_timer.start(6000)
        else:
            self.slider_box.hide()

    def on_slider_hover_enter(self):
        if not self.is_transparent_mode:
            return
        self.slider_timer.stop()

    def on_slider_hover_leave(self):
        if self.is_transparent_mode:
            self.slider_timer.start(6000)
        else:
            self.slider_box.hide()

    def on_slider_changed(self, val):
        self.opacity_val = val
        self.slider_box.percent_label.setText(f"{val}%")
        self.config["TRANSPARENCY"] = val
        save_config(self.config)
        self.apply_container_style()
        self.show_slider_with_timer()

    def on_auto_btn_clicked(self):
        if self.current_mode == "auto":
            return
        # Temporarily keep manual selected in UI until confirmed
        self.manual_btn.setChecked(True)
        self.auto_btn.setChecked(False)

        if not self.auto_confirm_dialog:
            self.auto_confirm_dialog = AutoModeConfirmDialog(self.main_container)
            self.auto_confirm_dialog.confirmed.connect(lambda: self.set_mode("auto"))
            self.auto_confirm_dialog.cancelled.connect(lambda: self.set_mode("manual"))

        self.auto_confirm_dialog.show_centered(self.main_container)

    def set_mode(self, mode):
        self.current_mode = mode
        if mode == "manual":
            self.manual_btn.setChecked(True)
            self.manual_btn.setStyleSheet("background-color: #334155; color: #ffffff; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.auto_btn.setChecked(False)
            self.auto_btn.setStyleSheet("background-color: transparent; color: #94a3b8; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.is_auto_running = False
            self.is_auto_listening_paused = False
            self.update_voice_button_style()
        else:
            self.auto_btn.setChecked(True)
            self.auto_btn.setStyleSheet("background-color: #10b981; color: #ffffff; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.manual_btn.setChecked(False)
            self.manual_btn.setStyleSheet("background-color: transparent; color: #94a3b8; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.is_auto_listening_paused = False
            self.status_pill.setText("🎧 Auto Mode: Listening to meeting & mic audio...")
            self.status_pill.show()
            QTimer.singleShot(3500, self.status_pill.hide)
            self.start_auto_mode()
            self.update_voice_button_style()

    def update_voice_button_style(self):
        if self.current_mode == "auto":
            if self.is_auto_listening_paused:
                self.voice_btn.setText("⏸️")
                self.voice_btn.setToolTip("Auto Mode Paused — Click to Resume Listening")
                self.voice_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #d97706;
                        color: white;
                        border: 2px solid #f59e0b;
                        border-radius: 21px;
                        font-size: 15px;
                    }
                    QPushButton:hover {
                        background-color: #b45309;
                    }
                """)
            else:
                self.voice_btn.setText("🎙️")
                self.voice_btn.setToolTip("Auto Mode Active — Listening to audio (Click to Pause)")
                self.voice_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #10b981;
                        color: white;
                        border: none;
                        border-radius: 21px;
                        font-size: 16px;
                    }
                    QPushButton:hover {
                        background-color: #059669;
                    }
                """)
        else:
            if self.is_listening:
                self.voice_btn.setText("🛑")
                self.voice_btn.setToolTip("Listening... Click to Stop Recording")
                self.voice_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #ef4444;
                        color: white;
                        border: 2px solid #fca5a5;
                        border-radius: 21px;
                        font-size: 15px;
                    }
                    QPushButton:hover {
                        background-color: #dc2626;
                    }
                """)
            else:
                self.voice_btn.setText("🎙️")
                self.voice_btn.setToolTip("Voice Dictation (Click to Start / Stop, or Space)")
                self.voice_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2563eb;
                        color: white;
                        border: none;
                        border-radius: 21px;
                        font-size: 16px;
                    }
                    QPushButton:hover {
                        background-color: #1d4ed8;
                    }
                """)

    def on_voice_button_clicked(self):
        if self.current_mode == "auto":
            self.is_auto_listening_paused = not self.is_auto_listening_paused
            self.update_voice_button_style()
            if self.is_auto_listening_paused:
                self.status_pill.setText("⏸️ Auto listening paused")
                self.status_pill.show()
                QTimer.singleShot(2500, self.status_pill.hide)
            else:
                self.status_pill.setText("🎙️ Auto listening resumed")
                self.status_pill.show()
                QTimer.singleShot(2500, self.status_pill.hide)
        else:
            if self.is_listening:
                self.stop_voice_input()
            else:
                self.start_voice_input()

    def _get_working_mic_index(self):
        if not hasattr(self, '_cached_mic_index') or self._cached_mic_index is None:
            best_idx = 5
            try:
                if PYAUDIO_AVAILABLE:
                    mic_dev, _ = self._get_wasapi_audio_devices()
                    if mic_dev:
                        best_idx = mic_dev['index']
            except Exception:
                pass
            self._cached_mic_index = best_idx
        return self._cached_mic_index

    def _get_wasapi_audio_devices(self):
        if not PYAUDIO_AVAILABLE or pyaudio is None:
            return None, None
        p = pyaudio.PyAudio()
        mic_dev = None
        loop_dev = None
        try:
            # 1. Output Loopback device (Computer/Meeting/YouTube audio)
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                def_out = p.get_device_info_by_index(wasapi_info['defaultOutputDevice'])
                for loopback in p.get_loopback_device_info_generator():
                    if def_out['name'] in loopback['name']:
                        loop_dev = loopback
                        break
                if loop_dev is None and def_out.get('isLoopbackDevice', False):
                    loop_dev = def_out
            except Exception as e:
                print(f"Loopback detection error: {e}")

            # 2. Real Physical Microphone device
            # Check devices: DirectSound routes physical microphone with real hardware sound on Windows/Realtek
            candidates = []
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d.get('maxInputChannels', 0) > 0 and not d.get('isLoopbackDevice', False):
                    name_l = d.get('name', '').lower()
                    if 'mapper' in name_l:
                        continue
                    candidates.append(d)

            # Prioritize DirectSound microphone
            for d in candidates:
                api = p.get_host_api_info_by_index(d['hostApi'])
                if "DirectSound" in api.get('name', '') and ("microphone" in d.get('name', '').lower() or "array" in d.get('name', '').lower()):
                    mic_dev = d
                    break

            if mic_dev is None:
                for d in candidates:
                    api = p.get_host_api_info_by_index(d['hostApi'])
                    if "DirectSound" in api.get('name', ''):
                        mic_dev = d
                        break

            if mic_dev is None:
                try:
                    mic_dev = p.get_default_input_device_info()
                except Exception:
                    pass

            if mic_dev is None and candidates:
                mic_dev = candidates[0]
        except Exception as e:
            print(f"Audio device detection error: {e}")
        finally:
            p.terminate()
        return mic_dev, loop_dev

    def _get_loopback_device(self):
        _, loop_dev = self._get_wasapi_audio_devices()
        return loop_dev

    def _get_microphone(self):
        dev_idx = self._get_working_mic_index()
        try:
            if dev_idx is not None and dev_idx >= 0:
                return sr.Microphone(device_index=dev_idx, sample_rate=44100)
        except Exception:
            pass
        return sr.Microphone(sample_rate=44100)

    @staticmethod
    def _pcm_to_16k_wav(raw_data, sample_rate):
        try:
            if sample_rate != 16000:
                data_16k, _ = sr.audioop.ratecv(raw_data, 2, 1, sample_rate, 16000, None)
            else:
                data_16k = raw_data
            bio = io.BytesIO()
            with wave.open(bio, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(data_16k)
            return bio.getvalue(), data_16k
        except Exception as e:
            print(f"WAV conversion error: {e}")
            return None, None

    def _transcribe_audio_buffer(self, data_16k, wav_bytes):
        """
        Two-stage high-accuracy transcriber:
        1. Fast Google Speech Recognition (US + Indian English)
        2. Intelligent Gemini Flash Multimodal Speech-to-Text Fallback
        Returns clean, intelligible human spoken words, or empty string if only noise/music/silence.
        """
        text = ""
        r = sr.Recognizer()

        # 1. Fast Google Web Speech Recognition
        try:
            audio_data = sr.AudioData(data_16k, 16000, 2)
            text = r.recognize_google(audio_data, language="en-US")
        except Exception:
            try:
                audio_data = sr.AudioData(data_16k, 16000, 2)
                text = r.recognize_google(audio_data, language="en-IN")
            except Exception:
                text = ""

        clean = text.strip() if text else ""
        if clean:
            return clean

        # 2. Intelligent Gemini Multimodal Speech Transcriber Fallback
        if wav_bytes and getattr(self, 'client', None) and GENAI_AVAILABLE:
            try:
                prompt_parts = [
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                    "You are a precise speech-to-text transcriber for technical interviews and meetings. "
                    "Listen to this audio clip and transcribe the EXACT words spoken by the human speaker. "
                    "Return ONLY the plain transcribed words. "
                    "If the audio contains only background stadium noise, music, cheering, commentary noise, silence, coughs, or no intelligible human speech, respond with exactly: NO_SPEECH."
                ]
                res = self.client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt_parts
                )
                if res and res.text:
                    cand = res.text.strip().strip('"').strip("'")
                    cand_upper = cand.upper()
                    if (
                        cand
                        and not cand_upper.startswith("NO_SPEECH")
                        and not cand_upper.startswith("NO SPEECH")
                        and "EMPTY" not in cand_upper
                        and cand_upper != "00:00"
                        and len(cand) >= 2
                    ):
                        clean = cand
            except Exception as e:
                print(f"Gemini fallback transcription error: {e}")

        return clean

    def start_auto_mode(self):
        self.is_auto_running = True
        threading.Thread(target=self._auto_listener_loop, daemon=True).start()

    def _auto_listener_loop(self):
        if not SPEECH_AVAILABLE:
            return

        r = sr.Recognizer()

        while self.is_auto_running and self.current_mode == "auto":
            if self.is_auto_listening_paused or self.is_generating:
                time.sleep(0.3)
                continue

            audio_src = self.config.get("AUDIO_SOURCE", "dual")
            mic_dev, loop_dev = self._get_wasapi_audio_devices()

            # 1. High-Accuracy Dual Stream WASAPI Listener (Default)
            if PYAUDIO_AVAILABLE and (loop_dev or mic_dev):
                use_loop = (audio_src in ["dual", "loopback"]) and (loop_dev is not None)
                use_mic = (audio_src in ["dual", "mic"]) and (mic_dev is not None)
                if not use_loop and not use_mic:
                    use_loop = loop_dev is not None
                    use_mic = mic_dev is not None

                try:
                    p = pyaudio.PyAudio()
                    stream_loop = None
                    stream_mic = None
                    rate_loop = int(loop_dev.get('defaultSampleRate', 48000)) if loop_dev else 48000
                    channels_loop = min(2, loop_dev.get('maxInputChannels', 2)) if loop_dev else 2
                    rate_mic = int(mic_dev.get('defaultSampleRate', 44100)) if mic_dev else 44100
                    channels_mic = min(2, mic_dev.get('maxInputChannels', 2)) if mic_dev else 2

                    if use_loop and loop_dev:
                        stream_loop = p.open(
                            format=pyaudio.paInt16,
                            channels=channels_loop,
                            rate=rate_loop,
                            input=True,
                            input_device_index=loop_dev['index'],
                            frames_per_buffer=1024
                        )

                    if use_mic and mic_dev:
                        stream_mic = p.open(
                            format=pyaudio.paInt16,
                            channels=channels_mic,
                            rate=rate_mic,
                            input=True,
                            input_device_index=mic_dev['index'],
                            frames_per_buffer=1024
                        )

                    frames = []
                    has_speech = False
                    speech_start = None
                    silence_start = None
                    loop_start = time.time()
                    last_interim_time = 0
                    is_interim_working = False

                    # Dynamic ambient calibration
                    calib_mic = []
                    calib_loop = []
                    for _ in range(4):
                        if not self.is_auto_running or self.current_mode != "auto" or self.is_auto_listening_paused or self.is_generating:
                            break
                        if stream_loop:
                            try:
                                b_l = stream_loop.read(1024, exception_on_overflow=False)
                                m_l = sr.audioop.tomono(b_l, 2, 0.5, 0.5) if channels_loop == 2 else b_l
                                calib_loop.append(sr.audioop.rms(m_l, 2))
                            except Exception:
                                pass
                        if stream_mic:
                            try:
                                b_m = stream_mic.read(1024, exception_on_overflow=False)
                                m_m = sr.audioop.tomono(b_m, 2, 0.5, 0.5) if channels_mic == 2 else b_m
                                calib_mic.append(sr.audioop.rms(m_m, 2))
                            except Exception:
                                pass

                    ambient_mic = (sum(calib_mic) / len(calib_mic)) if calib_mic else 25.0
                    ambient_loop = (sum(calib_loop) / len(calib_loop)) if calib_loop else 25.0
                    thresh_mic = max(35.0, ambient_mic * 1.5)
                    thresh_loop = max(45.0, ambient_loop * 1.5)

                    while self.is_auto_running and self.current_mode == "auto" and not self.is_auto_listening_paused and not self.is_generating:
                        m_16k = None
                        l_16k = None
                        rms_m = 0
                        rms_l = 0

                        if stream_loop:
                            try:
                                b_l = stream_loop.read(1024, exception_on_overflow=False)
                                loop_mono = sr.audioop.tomono(b_l, 2, 0.5, 0.5) if channels_loop == 2 else b_l
                                l_16k, _ = sr.audioop.ratecv(loop_mono, 2, 1, rate_loop, 16000, None)
                                rms_l = sr.audioop.rms(l_16k, 2)
                            except Exception:
                                pass

                        if stream_mic:
                            try:
                                b_m = stream_mic.read(1024, exception_on_overflow=False)
                                mic_mono = sr.audioop.tomono(b_m, 2, 0.5, 0.5) if channels_mic == 2 else b_m
                                m_16k, _ = sr.audioop.ratecv(mic_mono, 2, 1, rate_mic, 16000, None)
                                rms_m = sr.audioop.rms(m_16k, 2)
                            except Exception:
                                pass

                        is_mic_active = (rms_m >= thresh_mic) and (m_16k is not None)
                        is_loop_active = (rms_l >= thresh_loop) and (l_16k is not None)

                        # Software gain normalization for quiet human speech
                        if m_16k and rms_m > 25:
                            gain_m = max(1.0, min(5.0, 4500.0 / max(rms_m, 1)))
                            if gain_m > 1.05:
                                m_16k = sr.audioop.mul(m_16k, 2, gain_m)

                        if l_16k and rms_l > 35:
                            gain_l = max(1.0, min(3.0, 4500.0 / max(rms_l, 1)))
                            if gain_l > 1.05:
                                l_16k = sr.audioop.mul(l_16k, 2, gain_l)

                        if is_mic_active and is_loop_active:
                            min_l = min(len(m_16k), len(l_16k))
                            mixed_16k = sr.audioop.add(m_16k[:min_l], l_16k[:min_l], 2)
                        elif is_mic_active:
                            mixed_16k = m_16k
                        elif is_loop_active:
                            mixed_16k = l_16k
                        elif m_16k:
                            mixed_16k = m_16k
                        elif l_16k:
                            mixed_16k = l_16k
                        else:
                            mixed_16k = None

                        if not mixed_16k:
                            time.sleep(0.01)
                            continue

                        now = time.time()
                        if is_mic_active or is_loop_active:
                            if not has_speech:
                                has_speech = True
                                speech_start = now
                            silence_start = None
                            frames.append(mixed_16k)
                        else:
                            if has_speech:
                                frames.append(mixed_16k)
                                if silence_start is None:
                                    silence_start = now
                                elif now - silence_start >= 1.1:
                                    break
                            else:
                                if now - loop_start > 6.0:
                                    break
                                time.sleep(0.005)

                        # Live interim analysis before speaking stops
                        if has_speech and (now - last_interim_time >= 0.7) and not is_interim_working and len(frames) >= 15:
                            last_interim_time = now
                            is_interim_working = True
                            snap_bytes = b"".join(frames)
                            def _do_interim_auto(aud_bytes):
                                nonlocal is_interim_working
                                try:
                                    r_sub = sr.Recognizer()
                                    aud = sr.AudioData(aud_bytes, 16000, 2)
                                    p_txt = ""
                                    try:
                                        p_txt = r_sub.recognize_google(aud, language="en-US")
                                    except Exception:
                                        try:
                                            p_txt = r_sub.recognize_google(aud, language="en-IN")
                                        except Exception:
                                            p_txt = ""
                                    if p_txt and p_txt.strip():
                                        clean_p = p_txt.strip()
                                        if len(clean_p) > 36:
                                            clean_p = "..." + clean_p[-33:]
                                        self.signals.voice_status_signal.emit(f"🎙️ \"{clean_p}\"", "interim")
                                except Exception:
                                    pass
                                finally:
                                    is_interim_working = False

                            threading.Thread(target=_do_interim_auto, args=(snap_bytes,), daemon=True).start()

                        if has_speech and (now - speech_start > 35.0):
                            break

                    if stream_loop:
                        try: stream_loop.stop_stream(); stream_loop.close()
                        except Exception: pass
                    if stream_mic:
                        try: stream_mic.stop_stream(); stream_mic.close()
                        except Exception: pass
                    p.terminate()

                    if frames and len(frames) > 10 and not self.is_generating and self.is_auto_running and not self.is_auto_listening_paused:
                        self.signals.voice_status_signal.emit("✨ Transcribing query...", "transcribing")
                        raw_data = b"".join(frames)
                        wav_bytes, data_16k = self._pcm_to_16k_wav(raw_data, 16000)
                        clean_text = self._transcribe_audio_buffer(data_16k, wav_bytes)

                        if clean_text and len(clean_text.split()) >= 2 and len(clean_text) >= 4:
                            if self.is_auto_running and not self.is_auto_listening_paused and not self.is_generating:
                                self.signals.voice_transcribed.emit(clean_text, wav_bytes)

                except Exception as e:
                    print(f"Auto dual listener error: {e}")
                    time.sleep(0.4)

            # 2. SpeechRecognition Microphone Listener Fallback
            else:
                try:
                    with self._get_microphone() as src:
                        if self.is_auto_listening_paused or not self.is_auto_running or self.is_generating:
                            continue
                        r.pause_threshold = 1.3
                        r.adjust_for_ambient_noise(src, duration=0.3)
                        audio = r.listen(src, timeout=5, phrase_time_limit=35)

                    if self.is_auto_listening_paused or not self.is_auto_running or self.is_generating:
                        continue

                    text = ""
                    try:
                        text = r.recognize_google(audio, language="en-US")
                    except Exception:
                        try:
                            text = r.recognize_google(audio, language="en-IN")
                        except Exception:
                            text = ""

                    clean_text = text.strip() if text else ""
                    if clean_text and len(clean_text.split()) >= 2 and len(clean_text) >= 7:
                        if self.is_auto_running and not self.is_auto_listening_paused and not self.is_generating:
                            self.signals.voice_transcribed.emit(clean_text, None)
                except sr.WaitTimeoutError:
                    continue
                except Exception:
                    time.sleep(0.4)

    def cycle_window_size(self):
        self.current_size_index = (self.current_size_index + 1) % len(self.SIZES)
        w, h = self.SIZES[self.current_size_index]
        self.resize(w, h)
        QTimer.singleShot(25, self.reflow_bubbles)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow_bubbles()

    def reflow_bubbles(self):
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, MessageBubble):
                widget.adjust_height()

    def set_transparency(self, enabled):
        self.is_transparent_mode = enabled
        self.trans_switch.set_checked(enabled)
        
        # Disable drop shadow in transparent mode for pristine clarity
        if hasattr(self, 'shadow_effect'):
            self.shadow_effect.setEnabled(not enabled)

        # Synchronously update all message bubbles with dynamic height reflow
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, MessageBubble):
                widget.apply_transparency(enabled)
        
        # Synchronously toggle dynamic Type-through switch & Hover Slider
        if self.is_transparent_mode:
            self.type_through_switch.show()
            self.type_through_switch.set_checked(self.is_click_through)
            self.show_slider_with_timer()
        else:
            self.type_through_switch.hide()
            self.slider_timer.stop()
            self.slider_box.hide()
            if self.is_click_through:
                self.set_type_through(False)
        
        self.apply_container_style()
        self.main_container.style().unpolish(self.main_container)
        self.main_container.style().polish(self.main_container)
        self.reflow_bubbles()
        self.main_container.update()
        self.update()
        QApplication.processEvents()

    def toggle_transparency(self):
        self.signals.transparency_toggled_signal.emit(not self.is_transparent_mode)

    def _set_native_click_through(self, enable=True):
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000

            if ctypes.sizeof(ctypes.c_void_p) == 8:
                GetWindowLong = user32.GetWindowLongPtrW
                SetWindowLong = user32.SetWindowLongPtrW
                GetWindowLong.restype = ctypes.c_int64
                SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int64]
                SetWindowLong.restype = ctypes.c_int64
            else:
                GetWindowLong = user32.GetWindowLongW
                SetWindowLong = user32.SetWindowLongW
                GetWindowLong.restype = ctypes.c_long
                SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
                SetWindowLong.restype = ctypes.c_long

            hwnd = wintypes.HWND(int(self.winId()))
            current_style = GetWindowLong(hwnd, GWL_EXSTYLE)
            if enable:
                new_style = current_style | WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                new_style = (current_style | WS_EX_LAYERED) & ~WS_EX_TRANSPARENT
            SetWindowLong(hwnd, GWL_EXSTYLE, new_style)
        except Exception as e:
            print(f"Error setting native click-through: {e}")

    def _poll_type_through_hover(self):
        if not self.is_click_through or not self.isVisible():
            return
        
        cursor_pos = QCursor.pos()
        win_rect = self.geometry()
        
        if win_rect.contains(cursor_pos):
            rel_y = cursor_pos.y() - win_rect.y()
            # If in Header (<= 42px) or Footer Dock (>= height - 52px), make interactive for clicks/toggles
            in_interactive_zone = (rel_y <= 42) or (rel_y >= self.height() - 52)
            if in_interactive_zone:
                if self._native_transparent_active:
                    self._set_native_click_through(False)
                    self._native_transparent_active = False
            else:
                if not self._native_transparent_active:
                    self._set_native_click_through(True)
                    self._native_transparent_active = True
        else:
            if not self._native_transparent_active:
                self._set_native_click_through(True)
                self._native_transparent_active = True

    def set_type_through(self, enabled):
        self.is_click_through = enabled
        self.type_through_switch.set_checked(enabled)
        
        if enabled:
            self._set_native_click_through(True)
            self._native_transparent_active = True
            self.type_through_timer.start()
        else:
            self.type_through_timer.stop()
            self._set_native_click_through(False)
            self._native_transparent_active = False
        
        self.apply_container_style()
        self.main_container.update()
        self.update()

    def toggle_type_through_global(self):
        if self.is_transparent_mode:
            self.signals.type_through_toggled_signal.emit(not self.is_click_through)

    def prompt_persona(self):
        persona, ok = QInputDialog.getMultiLineText(
            self, "Customize Assistant Persona",
            "Define your background, role, and instructions for the AI:",
            self.config.get("PERSONA", "")
        )
        if ok and persona.strip():
            self.config["PERSONA"] = persona.strip()
            save_config(self.config)

    def prompt_api_key(self):
        key, ok = QInputDialog.getText(self, "Gemini API Key", "Enter your Google Gemini API Key:", text=self.config.get("GEMINI_API_KEY", ""))
        if ok and key.strip():
            self.config["GEMINI_API_KEY"] = key.strip()
            save_config(self.config)
            self.init_ai()

    def prompt_audio_device(self):
        if not SPEECH_AVAILABLE:
            self.status_pill.setText("⚠️ Speech recognition not available")
            self.status_pill.show()
            QTimer.singleShot(3000, self.status_pill.hide)
            return

        options = [
            "🎙️+🔊 Dual Capture (Microphone + Computer Audio) [Recommended]",
            "🔊 Computer / Meeting Audio (YouTube, Zoom, Teams, Meet)",
            "🎙️ Microphone (Your Voice / Speech)"
        ]
        
        current_src = self.config.get("AUDIO_SOURCE", "dual")
        curr_idx = 0 if current_src == "dual" else (1 if current_src == "loopback" else 2)

        item, ok = QInputDialog.getItem(
            self, "Select Audio Source",
            "Choose where Aura should listen:",
            options, curr_idx, False
        )
        if ok and item:
            if "Dual" in item:
                self.config["AUDIO_SOURCE"] = "dual"
                label = "Dual Audio (Mic + Computer)"
            elif "Computer" in item:
                self.config["AUDIO_SOURCE"] = "loopback"
                label = "Computer Audio"
            else:
                self.config["AUDIO_SOURCE"] = "mic"
                label = "Microphone"

            self.config.pop("AUDIO_DEVICE_INDEX", None)
            save_config(self.config)
            self.status_pill.setText(f"🎧 Set: {label}")
            self.status_pill.show()
            QTimer.singleShot(3500, self.status_pill.hide)

    def show_settings_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0b1329;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #1e293b;
                color: #38bdf8;
            }
        """)
        key_act = menu.addAction("🔑 Set Gemini API Key")
        key_act.triggered.connect(self.prompt_api_key)

        audio_act = menu.addAction("🎙️ Select Audio Device (Mic / Stereo Mix)")
        audio_act.triggered.connect(self.prompt_audio_device)

        persona_act = menu.addAction("🎛️ Customize Persona & Instructions")
        persona_act.triggered.connect(self.prompt_persona)

        menu.addSeparator()
        quit_act = menu.addAction("❌ Quit Aura Completely")
        quit_act.triggered.connect(self.quit_application)

        btn_pos = self.key_btn.mapToGlobal(QPoint(0, -145))
        menu.exec(btn_pos)

    def add_message(self, text="", is_user=False, is_image=False, pixmap=None):
        bubble = MessageBubble(text, is_user=is_user, is_image=is_image, pixmap=pixmap, parent_assistant=self)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        QTimer.singleShot(40, self.update_scroll_bottom_btn)
        return bubble

    def update_scroll_bottom_btn(self):
        if not hasattr(self, 'scroll_bottom_btn') or not hasattr(self, 'scroll_area'):
            return
        sb = self.scroll_area.verticalScrollBar()
        max_val = sb.maximum()
        val = sb.value()
        if max_val - val > 30:
            self.scroll_bottom_btn.show()
            self.scroll_bottom_btn.move(self.main_container.width() - 44, self.height() - 150)
            self.scroll_bottom_btn.raise_()
        else:
            self.scroll_bottom_btn.hide()

    def scroll_to_bottom(self):
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())
        self.update_scroll_bottom_btn()

    def on_scroll_value_changed(self, val):
        self.update_scroll_bottom_btn()

    def on_scroll_range_changed(self, min_val, max_val):
        self.update_scroll_bottom_btn()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow_bubbles()
        self.update_scroll_bottom_btn()

    def clear_conversation(self):
        self.conversation_history.clear()
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.add_message("Hi! I'm Aura. Conversation context reset. How can I help?", is_user=False)
        self.scroll_to_bottom()

    def on_selection_action(self, action_type, full_prompt):
        if self.is_generating:
            return
        self.add_message(full_prompt, is_user=True)
        self.scroll_to_bottom()
        self.conversation_history.append({"role": "user", "text": full_prompt, "image_bytes": None})
        self.is_generating = True
        self.stream_chunk_buffer = ""
        self.current_ai_bubble = self.add_message("", is_user=False)
        self.status_pill.setText("Generating answer...")
        self.status_pill.show()
        threading.Thread(target=self._stream_response, args=(full_prompt,), daemon=True).start()

    def send_text_prompt(self, audio_bytes=None):
        if self.is_generating:
            return
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self.add_message(text, is_user=True)
        self.scroll_to_bottom()
        self.conversation_history.append({"role": "user", "text": text, "image_bytes": None, "audio_bytes": audio_bytes})

        if not self.ai_ready:
            self.add_message("⚠️ API key required. Click ⚙️ to configure.", is_user=False)
            return

        self.is_generating = True
        self.stream_chunk_buffer = ""
        self.current_ai_bubble = self.add_message("", is_user=False)
        self.status_pill.setText("Generating answer...")
        self.status_pill.show()
        threading.Thread(target=self._stream_response, args=(text,), kwargs={"audio_bytes": audio_bytes}, daemon=True).start()

    def _stream_response(self, prompt, image_bytes=None, audio_bytes=None):
        candidate_models = [
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.1-pro-preview"
        ]

        success = False
        last_error = ""

        # Build full multi-turn context from conversation history (retaining up to last 12 turns)
        contents = []
        recent_turns = self.conversation_history[-12:]
        for idx, turn in enumerate(recent_turns):
            parts = []
            if turn.get("text"):
                parts.append(types.Part.from_text(text=turn["text"]))
            # Only attach media bytes to the most recent turn for peak speed & bandwidth efficiency
            if idx == len(recent_turns) - 1:
                if turn.get("image_bytes"):
                    parts.append(types.Part.from_bytes(
                        data=turn["image_bytes"],
                        mime_type="image/jpeg"
                    ))
                if turn.get("audio_bytes"):
                    parts.append(types.Part.from_bytes(
                        data=turn["audio_bytes"],
                        mime_type="audio/wav"
                    ))
            if parts:
                contents.append(types.Content(role=turn["role"], parts=parts))

        if not contents:
            parts = []
            if prompt:
                parts.append(types.Part.from_text(text=prompt))
            if image_bytes:
                parts.append(types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/jpeg"
                ))
            if audio_bytes:
                parts.append(types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type="audio/wav"
                ))
            contents = parts

        persona_instruction = self.config.get("PERSONA", "")
        system_prompt = (
            f"{persona_instruction}\n"
            "You are an expert real-time AI assistant for interviews, technical discussions, system architecture, and general coding/CS questions.\n"
            "You maintain full conversational context and memory across follow-up questions, dry-runs, edge-cases, and refactorings.\n\n"
            "ADAPTIVE RESPONSE GUIDELINES:\n"
            "1. **General / Conceptual / Career / Advice Questions** (e.g. 'how to master CS skills', 'explain REST vs GraphQL', 'how does GC work'):\n"
            "   • Provide clean, beautifully structured, natural answers with crisp bullet points, bold key concepts, and clear actionable takeaways.\n"
            "   • NEVER force rigid framework labels (like H/E/R/O/S) on general questions.\n\n"
            "2. **Specific DSA / Algorithmic Coding Challenge Questions** (e.g. 'Two Sum', 'Word Ladder', DP, Graph/Tree problems):\n"
            "   • **Core Idea / Approach**: 1-2 direct sentences on the invariant/strategy.\n"
            "   • **Example / Trace**: Brief, clear walkthrough if helpful.\n"
            "   • **Optimized Implementation**: Clean code with concise comments.\n"
            "   • **Complexity**: Time and Space in bold (e.g., **O(N log N)** time, **O(N)** space).\n"
            "   • **Key Spoken Summary**: 1 punchy sentence to say aloud to an interviewer.\n\n"
            "3. **Screen Capture Questions**:\n"
            "   • **Direct Answer / Solution**: Immediate resolution.\n"
            "   • **Key Steps / Reasoning**: Concise bullet points.\n\n"
            "CRITICAL FORMATTING RULES FOR MATH & NOTATION:\n"
            "• DO NOT use LaTeX syntax or math delimiters ($ or $$ or \\times or \\cdot or \\le).\n"
            "• ALWAYS use clean, human-readable plain text / Unicode notation: e.g. **O(M × N)**, **O(M² × N)**, **O(N log N)**, **O(V + E)**, **O(1)**, 26 × M, ≤, ≥.\n"
            "• ALWAYS bold Big-O notation like **O(N)**, **O(M × N)**, **O(M² × N)**.\n"
            "• Keep formatting readable, clean, and concise with bold headings and bullet points. Avoid filler text."
        )

        fast_config = types.GenerateContentConfig(
            temperature=0.2,
            system_instruction=system_prompt
        )

        for m_name in candidate_models:
            try:
                response = self.client.models.generate_content_stream(
                    model=m_name,
                    contents=contents,
                    config=fast_config
                )
                for chunk in response:
                    if chunk.text:
                        self.signals.stream_chunk.emit(chunk.text)
                success = True
                self.active_model_name = m_name
                break
            except Exception as e:
                last_error = str(e)
                print(f"Model {m_name} failed: {e}")
                continue

        if not success:
            self.signals.stream_chunk.emit(f"\n[Error: {last_error}]")
        self.signals.stream_finished.emit()

    def on_stream_chunk(self, chunk):
        self.stream_chunk_buffer += chunk
        if not self.stream_render_timer.isActive():
            self.stream_render_timer.start()

    def _flush_stream_buffer(self):
        if self.stream_chunk_buffer and self.current_ai_bubble:
            buf = self.stream_chunk_buffer
            self.stream_chunk_buffer = ""
            self.current_ai_bubble.append_text(buf)
            self.update_scroll_bottom_btn()

    def on_stream_finished(self):
        self.stream_render_timer.stop()
        self._flush_stream_buffer()
        self.is_generating = False
        self.status_pill.hide()
        if self.current_ai_bubble:
            self.current_ai_bubble.show_action_chips()
            if self.current_ai_bubble.raw_text:
                self.conversation_history.append({
                    "role": "model",
                    "text": self.current_ai_bubble.raw_text,
                    "image_bytes": None
                })
        self.update_scroll_bottom_btn()

    def capture_screen_and_analyze(self):
        self.status_pill.setText("••• 📸 Capturing screen...")
        self.status_pill.show()
        
        was_visible = self.isVisible()
        if was_visible:
            self.hide()
            QApplication.processEvents()
            time.sleep(0.07)

        screen = QGuiApplication.primaryScreen()
        if not screen:
            if was_visible:
                self.show_and_activate()
            self.status_pill.hide()
            return

        pixmap = screen.grabWindow(0)
        
        if was_visible:
            self.show_and_activate()

        if pixmap.width() > 1600:
            pixmap_scaled = pixmap.scaledToWidth(1440, Qt.TransformationMode.FastTransformation)
        else:
            pixmap_scaled = pixmap

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        pixmap_scaled.save(buffer, "JPEG", 80)
        image_bytes = bytes(buffer.data())

        self.add_message("📸 Screen Capture", is_user=True, is_image=True, pixmap=pixmap)
        self.scroll_to_bottom()
        prompt = "Analyze this screen. Solve any question/problem visible or explain the active content immediately with clear steps."
        self.conversation_history.append({
            "role": "user",
            "text": prompt,
            "image_bytes": image_bytes
        })

        if not self.ai_ready:
            self.add_message("⚠️ API key required. Click ⚙️ to configure.", is_user=False)
            self.status_pill.hide()
            return

        self.is_generating = True
        self.stream_chunk_buffer = ""
        self.status_pill.setText("Generating answer...")
        self.status_pill.show()

        self.current_ai_bubble = self.add_message("", is_user=False)
        threading.Thread(target=self._stream_response, args=(prompt, image_bytes), daemon=True).start()

    def stop_voice_input(self):
        if not self.is_listening:
            return
        self.is_listening = False
        self.manual_voice_stop_requested = True
        self.update_voice_button_style()
        self.status_pill.setText("⏹️ Processing speech...")
        self.status_pill.show()

    def start_voice_input(self):
        if self.is_generating:
            return
        if not SPEECH_AVAILABLE:
            self.status_pill.setText("⚠️ SpeechRecognition or pyaudio not installed")
            self.status_pill.show()
            QTimer.singleShot(3000, self.status_pill.hide)
            return
        if self.is_listening:
            self.stop_voice_input()
            return

        self.is_listening = True
        self.manual_voice_stop_requested = False
        self.update_voice_button_style()
        self.status_pill.setText("🎙️ Listening... Speak now (Click mic to stop)")
        self.status_pill.show()

        def listen_worker():
            frames_16k = []
            mic_dev, loop_dev = self._get_wasapi_audio_devices()
            audio_src = self.config.get("AUDIO_SOURCE", "dual")

            # In manual mode, prioritize physical microphone for dictation
            target_dev = loop_dev if (audio_src == "loopback" and loop_dev) else (mic_dev or loop_dev)

            if PYAUDIO_AVAILABLE and target_dev:
                p = pyaudio.PyAudio()
                stream = None
                try:
                    native_rate = int(target_dev.get('defaultSampleRate', 44100))
                    native_channels = min(2, target_dev.get('maxInputChannels', 1))

                    stream = p.open(
                        format=pyaudio.paInt16,
                        channels=native_channels,
                        rate=native_rate,
                        input=True,
                        input_device_index=target_dev['index'],
                        frames_per_buffer=1024
                    )

                    self.signals.voice_status_signal.emit("🎙️ Listening... Speak now (Click mic to stop)", "active")

                    # Fast ambient calibration on initial background sound (~0.09s)
                    calib_rms = []
                    for _ in range(4):
                        if not self.is_listening or self.manual_voice_stop_requested:
                            break
                        try:
                            raw = stream.read(1024, exception_on_overflow=False)
                            mono = sr.audioop.tomono(raw, 2, 0.5, 0.5) if native_channels == 2 else raw
                            calib_rms.append(sr.audioop.rms(mono, 2))
                        except Exception:
                            pass

                    ambient_floor = (sum(calib_rms) / len(calib_rms)) if calib_rms else 25.0
                    speech_threshold = max(35.0, ambient_floor * 1.5)

                    has_speech = False
                    speech_start = None
                    silence_start = None
                    start_wait = time.time()
                    last_interim_time = 0
                    is_interim_working = False

                    while self.is_listening and not self.manual_voice_stop_requested:
                        try:
                            raw_chunk = stream.read(1024, exception_on_overflow=False)
                        except Exception:
                            break

                        mono_chunk = sr.audioop.tomono(raw_chunk, 2, 0.5, 0.5) if native_channels == 2 else raw_chunk
                        rms = sr.audioop.rms(mono_chunk, 2)

                        # Downsample to 16,000 Hz
                        chunk_16k, _ = sr.audioop.ratecv(mono_chunk, 2, 1, native_rate, 16000, None)

                        # Dynamic gain scaling for soft voices
                        if rms > 25:
                            gain = max(1.0, min(5.0, 4500.0 / max(rms, 1)))
                            if gain > 1.05:
                                chunk_16k = sr.audioop.mul(chunk_16k, 2, gain)

                        now = time.time()
                        if rms >= speech_threshold:
                            if not has_speech:
                                has_speech = True
                                speech_start = now
                            silence_start = None
                            frames_16k.append(chunk_16k)
                        else:
                            if has_speech:
                                frames_16k.append(chunk_16k)
                                if silence_start is None:
                                    silence_start = now
                                elif now - silence_start >= 1.1:
                                    break
                            else:
                                if now - start_wait > 9.0:
                                    break
                                time.sleep(0.005)

                        # Live interim recognition while speaking
                        if has_speech and (now - last_interim_time >= 0.7) and not is_interim_working and len(frames_16k) >= 12:
                            last_interim_time = now
                            is_interim_working = True
                            snap_bytes = b"".join(frames_16k)

                            def _do_interim_manual(aud_bytes):
                                nonlocal is_interim_working
                                try:
                                    r_sub = sr.Recognizer()
                                    aud = sr.AudioData(aud_bytes, 16000, 2)
                                    p_txt = ""
                                    try:
                                        p_txt = r_sub.recognize_google(aud, language="en-US")
                                    except Exception:
                                        try:
                                            p_txt = r_sub.recognize_google(aud, language="en-IN")
                                        except Exception:
                                            p_txt = ""
                                    if p_txt and p_txt.strip():
                                        clean_p = p_txt.strip()
                                        if len(clean_p) > 36:
                                            clean_p = "..." + clean_p[-33:]
                                        self.signals.voice_status_signal.emit(f"🎙️ \"{clean_p}\"", "interim")
                                except Exception:
                                    pass
                                finally:
                                    is_interim_working = False

                            threading.Thread(target=_do_interim_manual, args=(snap_bytes,), daemon=True).start()

                        if has_speech and (now - speech_start > 35.0):
                            break

                except Exception as e:
                    print(f"Manual voice recording error: {e}")
                finally:
                    self.is_listening = False
                    if stream:
                        try: stream.stop_stream(); stream.close()
                        except Exception: pass
                    p.terminate()

            else:
                try:
                    r = sr.Recognizer()
                    with self._get_microphone() as src:
                        sample_rate = src.SAMPLE_RATE
                        r.adjust_for_ambient_noise(src, duration=0.25)
                        self.signals.voice_status_signal.emit("🎙️ Listening... Speak now (Click mic to stop)", "active")
                        has_speech = False
                        speech_start = None
                        silence_start = None
                        start_wait = time.time()

                        while self.is_listening and not self.manual_voice_stop_requested:
                            try:
                                buf = src.stream.read(src.CHUNK)
                            except Exception:
                                break
                            chunk_16k, _ = sr.audioop.ratecv(buf, src.SAMPLE_WIDTH, 1, sample_rate, 16000, None)
                            frames_16k.append(chunk_16k)
                            chunk_energy = sr.audioop.rms(buf, src.SAMPLE_WIDTH)
                            now = time.time()
                            if chunk_energy > 40:
                                if not has_speech:
                                    has_speech = True
                                    speech_start = now
                                silence_start = None
                            else:
                                if has_speech:
                                    if silence_start is None:
                                        silence_start = now
                                    elif now - silence_start >= 1.1:
                                        break
                                else:
                                    if now - start_wait > 9.0:
                                        break
                            if has_speech and (now - speech_start > 35.0):
                                break
                except Exception as e:
                    print(f"Fallback recording error: {e}")
                finally:
                    self.is_listening = False

            # Finalize captured audio
            if frames_16k and len(frames_16k) > 6:
                self.signals.voice_status_signal.emit("✨ Transcribing query...", "transcribing")
                try:
                    data_16k = b"".join(frames_16k)
                    wav_bytes, _ = self._pcm_to_16k_wav(data_16k, 16000)
                    clean_text = self._transcribe_audio_buffer(data_16k, wav_bytes)

                    if clean_text and len(clean_text) >= 2:
                        self.signals.voice_transcribed.emit(clean_text, wav_bytes)
                    else:
                        self.signals.voice_status_signal.emit("⚠️ No speech detected", "error")
                except Exception as e:
                    print(f"Manual transcription error: {e}")
                    self.signals.voice_status_signal.emit("⚠️ Could not transcribe", "error")
            else:
                self.signals.voice_status_signal.emit("⚠️ No speech detected", "error")

            self.signals.voice_finished_signal.emit()

        threading.Thread(target=listen_worker, daemon=True).start()

    def on_voice_status(self, text, status_type):
        self.status_pill.setText(text)
        self.status_pill.show()
        if status_type == "error":
            QTimer.singleShot(2500, self.status_pill.hide)

    def on_voice_finished(self):
        self.update_voice_button_style()
        if not self.is_listening and "Listening" in self.status_pill.text():
            self.status_pill.hide()

    def on_voice_transcribed(self, text, audio_bytes=None):
        if self.is_generating:
            return
        clean = text.strip() if text else ""
        if not clean or clean.lower() in ["[audio query]", "audio query", "no_speech"]:
            return
        self.text_input.setText(clean)
        self.send_text_prompt(audio_bytes=audio_bytes)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not self.text_input.hasFocus():
            now = time.time()
            if not hasattr(self, '_last_space_press') or (now - self._last_space_press > 0.4):
                self._last_space_press = now
                self.on_voice_button_clicked()
            event.accept()
        else:
            super().keyPressEvent(event)

    def quit_application(self):
        try:
            self.is_auto_running = False
            self.is_listening = False
            self.manual_voice_stop_requested = True
            if KEYBOARD_AVAILABLE:
                try:
                    keyboard.unhook_all()
                except Exception:
                    pass
            try:
                QLocalServer.removeServer(LOCAL_SERVER_NAME)
            except Exception:
                pass
            if hasattr(self, 'app_mutex') and self.app_mutex:
                try:
                    ctypes.windll.kernel32.CloseHandle(self.app_mutex)
                except Exception:
                    pass
        except Exception as e:
            print(f"Error during shutdown: {e}")
        finally:
            QApplication.quit()
            os._exit(0)

    def closeEvent(self, event):
        self.quit_application()
        event.accept()

    def toggle_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_and_activate()

    def show_and_activate(self):
        self.showNormal()
        self._enforce_taskbar_hidden()
        self.activateWindow()
        self.raise_()

    def init_tray(self):
        # 100% Stealth Mode: Removed all taskbar and tray icons as requested so Aura leaves ZERO trace on the Windows taskbar
        self.tray_icon = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            y = event.position().y()
            # Restrict window dragging strictly to Header (top <= 42px) and Footer Dock (bottom >= height - 52px)
            if y <= 42 or y >= (self.height() - 52):
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            else:
                self.drag_position = None

    def mouseMoveEvent(self, event):
        if self.drag_position is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
        elif self.is_transparent_mode:
            pos = event.position()
            if pos.y() > self.height() - 130 and pos.x() > self.width() - 250:
                self.show_slider_with_timer()

    def mouseReleaseEvent(self, event):
        self.drag_position = None

    def setup_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                # Primary Non-Ctrl Hotkeys (Safe from proctoring/app key blocks)
                # Toggle window visibility: Alt+Space OR single-key F8
                keyboard.add_hotkey('alt+space', lambda: self.signals.toggle_window_signal.emit(), suppress=False)
                keyboard.add_hotkey('f8', lambda: self.signals.toggle_window_signal.emit(), suppress=False)

                # Screen capture: Alt+S OR F9
                keyboard.add_hotkey('alt+s', lambda: self.signals.trigger_camera_signal.emit(), suppress=False)
                keyboard.add_hotkey('f9', lambda: self.signals.trigger_camera_signal.emit(), suppress=False)

                # Voice dictation: Alt+V OR F7
                keyboard.add_hotkey('alt+v', lambda: self.signals.trigger_voice_signal.emit(), suppress=False)
                keyboard.add_hotkey('f7', lambda: self.signals.trigger_voice_signal.emit(), suppress=False)

                # Transparency toggle: Alt+G OR F10
                keyboard.add_hotkey('alt+g', lambda: self.signals.trigger_transparency_signal.emit(), suppress=False)
                keyboard.add_hotkey('f10', lambda: self.signals.trigger_transparency_signal.emit(), suppress=False)

                # Click-through toggle: Alt+T
                keyboard.add_hotkey('alt+t', lambda: self.signals.trigger_type_through_signal.emit(), suppress=False)

                # Legacy Ctrl shortcuts (if Ctrl is permitted)
                keyboard.add_hotkey('ctrl+space', lambda: self.signals.toggle_window_signal.emit(), suppress=False)
                keyboard.add_hotkey('ctrl+g', lambda: self.signals.trigger_transparency_signal.emit(), suppress=False)
                keyboard.add_hotkey('ctrl+t', lambda: self.signals.trigger_type_through_signal.emit(), suppress=False)
                keyboard.add_hotkey('ctrl+shift+s', lambda: self.signals.trigger_camera_signal.emit(), suppress=False)
                keyboard.add_hotkey('ctrl+shift+v', lambda: self.signals.trigger_voice_signal.emit(), suppress=False)
            except Exception as e:
                print(f"Failed to bind global hotkeys: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 1. OS-Level Kernel Mutex: strictly enforces SINGLE INSTANCE across the system
    ERROR_ALREADY_EXISTS = 183
    MUTEX_NAME = "AuraAssistantSingleInstanceMutex_Akki"
    app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    is_duplicate = (ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS)

    if is_duplicate:
        # Existing instance is already running! Wake it up and exit this duplicate immediately
        socket = QLocalSocket()
        socket.connectToServer(LOCAL_SERVER_NAME)
        if socket.waitForConnected(400):
            socket.write(b"WAKEUP\n")
            socket.waitForBytesWritten(400)
            socket.close()
        ctypes.windll.kernel32.CloseHandle(app_mutex)
        sys.exit(0)

    # 2. Local Server for IPC Wakeup
    QLocalServer.removeServer(LOCAL_SERVER_NAME)
    local_server = QLocalServer()
    local_server.listen(LOCAL_SERVER_NAME)

    assistant = NativeAssistant()
    assistant.app_mutex = app_mutex

    def on_new_connection():
        client_sock = local_server.nextPendingConnection()
        if client_sock:
            assistant.signals.show_window_signal.emit()
            client_sock.close()

    local_server.newConnection.connect(on_new_connection)
    assistant.show()
    sys.exit(app.exec())
