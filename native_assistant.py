import sys
import os
import io
import json
import threading
import time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QScrollArea, QFrame, QTextBrowser,
    QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect, QInputDialog,
    QSizePolicy, QSlider
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject, QTimer, QBuffer, QIODevice, QEvent
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QGuiApplication, QAction, QCursor
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
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    defaults = {
        "GEMINI_API_KEY": "",
        "PERSONA": "I am Akshay, a 3rd year BTech Computer Science student focusing on backend architecture, data analysis, and building AI tools. When answering, be direct, concise, and structured.",
        "TRANSPARENCY": 65
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")


class WorkerSignals(QObject):
    stream_chunk = pyqtSignal(str)
    stream_finished = pyqtSignal()
    voice_transcribed = pyqtSignal(str)
    show_window_signal = pyqtSignal()
    toggle_window_signal = pyqtSignal()
    trigger_camera_signal = pyqtSignal()
    transparency_toggled_signal = pyqtSignal(bool)
    type_through_toggled_signal = pyqtSignal(bool)


# --- Toggle Switch with Label Below & Full Hit Area ---
class CompactToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, label_text, is_checked=False, parent=None):
        super().__init__(parent)
        self.is_checked = is_checked
        self.label_text = label_text
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Pill switch representation
        self.switch_btn = QPushButton()
        self.switch_btn.setFixedSize(32, 18)
        self.switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switch_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.switch_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Label underneath
        self.label = QLabel(label_text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
            event.accept()
        else:
            super().mousePressEvent(event)

    def toggle(self):
        self.is_checked = not self.is_checked
        self.update_style()
        self.toggled.emit(self.is_checked)

    def set_checked(self, checked):
        if self.is_checked != checked:
            self.is_checked = checked
            self.update_style()

    def update_style(self):
        if self.is_checked:
            self.switch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    border: 1px solid #60a5fa;
                    border-radius: 9px;
                }
            """)
            self.label.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 600;")
        else:
            self.switch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #334155;
                    border: 1px solid #475569;
                    border-radius: 9px;
                }
            """)
            self.label.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500;")


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


# --- Adaptive Message Bubble ---
class MessageBubble(QFrame):
    def __init__(self, text, is_user=False, is_image=False, pixmap=None, parent_assistant=None):
        super().__init__(parent_assistant)
        self.parent_assistant = parent_assistant
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.raw_text = text
        self.is_user = is_user
        
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)

        if is_image and pixmap:
            self.img_label = QLabel()
            scaled_pixmap = pixmap.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation)
            self.img_label.setPixmap(scaled_pixmap)
            self.img_label.setStyleSheet("border-radius: 6px; margin-bottom: 4px;")
            layout.addWidget(self.img_label)

        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setReadOnly(True)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.viewport().setAutoFillBackground(False)
        self.text_browser.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        self.text_browser.selectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.text_browser)

        # Set transparent mouse events if parent is in type-through mode
        if parent_assistant and parent_assistant.is_click_through:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.text_browser.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            if self.text_browser.viewport():
                self.text_browser.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.apply_transparency(parent_assistant.is_transparent_mode if parent_assistant else False)
        self.update_content(text)

    def apply_transparency(self, is_transparent):
        if is_transparent:
            self.setStyleSheet("""
                QFrame {
                    background-color: transparent;
                    border: none;
                    margin-left: 4px;
                    margin-right: 4px;
                    margin-top: 2px;
                    margin-bottom: 2px;
                }
            """)
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #ffffff;
                    font-size: 13.5px;
                    font-weight: 500;
                    font-family: 'Segoe UI', -apple-system, sans-serif;
                }
            """)
        else:
            if self.is_user:
                self.setStyleSheet("""
                    QFrame {
                        background-color: #1e293b;
                        border: 1px solid #334155;
                        border-radius: 10px;
                        margin-left: 50px;
                        margin-right: 2px;
                        margin-top: 2px;
                        margin-bottom: 2px;
                    }
                """)
            else:
                self.setStyleSheet("""
                    QFrame {
                        background-color: #182234;
                        border: 1px solid #1e293b;
                        border-radius: 10px;
                        margin-right: 30px;
                        margin-left: 2px;
                        margin-top: 2px;
                        margin-bottom: 2px;
                    }
                """)
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #f1f5f9;
                    font-size: 13px;
                    font-family: 'Segoe UI', -apple-system, sans-serif;
                }
            """)
        self.update()

    def on_selection_changed(self):
        selected = self.text_browser.textCursor().selectedText().strip()
        if selected and len(selected) > 2 and self.parent_assistant:
            cursor_pos = QCursor.pos()
            self.parent_assistant.selection_popup.show_at(QPoint(cursor_pos.x() - 60, cursor_pos.y() - 35), selected)
        elif self.parent_assistant:
            self.parent_assistant.selection_popup.hide()

    def _render_html(self, text):
        if not text:
            return ""
        if md_parser:
            html = md_parser.render(text)
        else:
            html = f"<p>{text}</p>"
        
        styled_html = f"""
        <style>
            body {{ color: #f1f5f9; font-family: 'Segoe UI', sans-serif; font-size: 13px; line-height: 1.45; margin: 0; padding: 0; }}
            p {{ margin: 0 0 5px 0; }}
            strong {{ color: #38bdf8; font-weight: 600; }}
            h1, h2, h3, h4 {{ color: #60a5fa; margin: 5px 0 3px 0; font-size: 13.5px; font-weight: bold; }}
            ul, ol {{ margin: 0 0 5px 14px; padding: 0; }}
            li {{ margin-bottom: 2px; }}
            code {{ background-color: #0b1120; color: #7dd3fc; padding: 1px 3px; border-radius: 3px; font-family: Consolas, monospace; font-size: 12px; }}
            pre {{ background-color: #0b1120; padding: 6px; border-radius: 5px; border: 1px solid #1e293b; margin: 3px 0; }}
        </style>
        {html}
        """
        return styled_html

    def update_content(self, text):
        self.raw_text = text
        self.text_browser.setHtml(self._render_html(text))
        self.adjust_height()

    def append_text(self, new_text):
        self.raw_text += new_text
        self.text_browser.setHtml(self._render_html(self.raw_text))
        self.adjust_height()

    def adjust_height(self):
        doc = self.text_browser.document()
        doc.setTextWidth(460)
        h = int(doc.size().height()) + 8
        self.text_browser.setFixedHeight(max(18, h))


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
        self.is_auto_running = False
        self.current_size_index = 0
        self.signals = WorkerSignals()
        self.current_ai_bubble = None
        self.config = load_config()
        self.client = None
        self.active_model_name = "gemini-flash-lite-latest"
        self.current_mode = "manual"

        self.selection_popup = SelectionActionPopup()
        self.selection_popup.action_triggered.connect(self.on_selection_action)

        self.init_ai()
        self.init_ui()
        self.init_tray()
        self.setup_hotkeys()

        # Connect signals
        self.signals.stream_chunk.connect(self.on_stream_chunk)
        self.signals.stream_finished.connect(self.on_stream_finished)
        self.signals.voice_transcribed.connect(self.on_voice_transcribed)
        self.signals.show_window_signal.connect(self.show_and_activate)
        self.signals.toggle_window_signal.connect(self.toggle_visibility)
        self.signals.trigger_camera_signal.connect(self.capture_screen_and_analyze)
        self.signals.transparency_toggled_signal.connect(self.set_transparency)
        self.signals.type_through_toggled_signal.connect(self.set_type_through)

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
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        w, h = self.SIZES[0]
        self.resize(w, h)
        self.setMinimumSize(420, 480)

        self.main_container = QWidget(self)
        self.main_container.setObjectName("MainContainer")
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

        # Bold Back Arrow
        self.back_btn = QPushButton("←")
        self.back_btn.setFixedSize(26, 26)
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
        self.auto_btn.clicked.connect(lambda: self.set_mode("auto"))
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
        self.close_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #94a3b8; font-size: 12px; font-weight: bold; } QPushButton:hover { background-color: #ef4444; color: white; border-radius: 4px; }")
        self.close_btn.clicked.connect(self.close)
        header_layout.addWidget(self.close_btn)

        container_layout.addWidget(self.header)

        # ==========================================
        # 2. CHAT SCROLL AREA
        # ==========================================
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                border: none;
                background: rgba(15, 23, 42, 0.2);
                width: 4px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical { background: #475569; border-radius: 2px; }
            QScrollBar::handle:vertical:hover { background: #64748b; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self.chat_widget = QWidget()
        self.chat_widget.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(4)
        self.chat_layout.addStretch()

        self.scroll_area.setWidget(self.chat_widget)
        container_layout.addWidget(self.scroll_area)

        # ==========================================
        # 3. HELPER TEXT BAR
        # ==========================================
        self.middle_helper_bar = QWidget()
        helper_layout = QHBoxLayout(self.middle_helper_bar)
        helper_layout.setContentsMargins(4, 0, 4, 0)
        helper_layout.setSpacing(8)

        # Centered hint label with Space keycap style
        self.hint_label = QLabel("Press <span style='background:#1e293b; padding:1px 5px; border-radius:4px; border:1px solid #334155; font-family:Consolas,monospace; font-weight:bold; color:#f8fafc;'>Space</span> or the mic to start")
        self.hint_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        helper_layout.addStretch()
        helper_layout.addWidget(self.hint_label, alignment=Qt.AlignmentFlag.AlignCenter)
        helper_layout.addStretch()

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
        self.input_card.hide()

        # ==========================================
        # 4. BOTTOM DOCK (Separated Floating Action Buttons)
        # ==========================================
        self.dock = QWidget()
        self.dock.setObjectName("DockWidget")
        dock_layout = QHBoxLayout(self.dock)
        dock_layout.setContentsMargins(0, 2, 0, 0)
        dock_layout.setSpacing(8)

        # Left: ⚙️ Settings + Credits/Model Badge
        self.key_btn = QPushButton("⚙️")
        self.key_btn.setToolTip("Settings / API Key")
        self.key_btn.setFixedSize(30, 30)
        self.key_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; border: 1px solid #334155; border-radius: 15px; font-size: 13px; }
            QPushButton:hover { background-color: #334155; }
        """)
        self.key_btn.clicked.connect(self.prompt_api_key)
        dock_layout.addWidget(self.key_btn)

        self.credits_badge = QLabel("🪙 Free")
        self.credits_badge.setStyleSheet("background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; padding: 2px 8px; font-size: 11px;")
        dock_layout.addWidget(self.credits_badge)

        dock_layout.addStretch()

        # Center Action Buttons (Built as 3 distinct circular buttons, NOT a shared box)
        self.cam_btn = QPushButton("📷")
        self.cam_btn.setToolTip("1-Click Screen Capture (Ctrl+Shift+S)")
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
        dock_layout.addWidget(self.cam_btn)

        # Prominent Vibrant Blue Circle Mic Button
        self.voice_btn = QPushButton("🎙️")
        self.voice_btn.setToolTip("Voice Dictation (Press Space when focused, or Ctrl+Shift+V)")
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
        self.voice_btn.clicked.connect(self.start_voice_input)
        dock_layout.addWidget(self.voice_btn)

        # Message / Chat Focus Button
        self.chat_btn = QPushButton("💬")
        self.chat_btn.setToolTip("Toggle Message Input")
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
        self.chat_btn.clicked.connect(self.toggle_input_card)
        dock_layout.addWidget(self.chat_btn)

        dock_layout.addStretch()

        # Right: Type-through Switch (Shown ONLY in transparent mode)
        self.type_through_switch = CompactToggleSwitch("Type-through", is_checked=False)
        self.type_through_switch.toggled.connect(self.set_type_through)
        self.type_through_switch.hide()
        dock_layout.addWidget(self.type_through_switch)

        # Right: Transparent Switch with Label Below
        self.trans_switch = CompactToggleSwitch("Transparent", is_checked=False)
        self.trans_switch.toggled.connect(self.set_transparency)
        dock_layout.addWidget(self.trans_switch)

        container_layout.addWidget(self.dock)
        self.setCentralWidget(self.main_container)

        # Install event filters for smooth header/dock dragging
        self.header.installEventFilter(self)
        self.dock.installEventFilter(self)
        self.brand_label.installEventFilter(self)

        self.add_message("Hi! I'm Aura. I can help you silently in all meetings, interviews, and code tasks.", is_user=False)

    def eventFilter(self, source, event):
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
            self.main_container.setStyleSheet("""
                QWidget#MainContainer {
                    background-color: transparent;
                    border: none;
                }
            """)
        else:
            self.main_container.setStyleSheet("""
                QWidget#MainContainer {
                    background-color: rgba(15, 23, 42, 245);
                    border: 1px solid #334155;
                    border-radius: 14px;
                }
            """)

    def set_mode(self, mode):
        self.current_mode = mode
        if mode == "manual":
            self.manual_btn.setChecked(True)
            self.manual_btn.setStyleSheet("background-color: #334155; color: #ffffff; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.auto_btn.setChecked(False)
            self.auto_btn.setStyleSheet("background-color: transparent; color: #94a3b8; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.is_auto_running = False
        else:
            self.auto_btn.setChecked(True)
            self.auto_btn.setStyleSheet("background-color: #10b981; color: #ffffff; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.manual_btn.setChecked(False)
            self.manual_btn.setStyleSheet("background-color: transparent; color: #94a3b8; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.start_auto_mode()

    def start_auto_mode(self):
        self.is_auto_running = True
        threading.Thread(target=self._auto_listener_loop, daemon=True).start()

    def _auto_listener_loop(self):
        if not SPEECH_AVAILABLE:
            return
        r = sr.Recognizer()
        r.pause_threshold = 1.0
        r.dynamic_energy_threshold = True

        while self.is_auto_running and self.current_mode == "auto":
            try:
                with sr.Microphone() as src:
                    r.adjust_for_ambient_noise(src, duration=0.2)
                    audio = r.listen(src, timeout=4, phrase_time_limit=15)
                text = r.recognize_google(audio)
                if text and self.is_auto_running:
                    self.signals.voice_transcribed.emit(text)
            except Exception:
                time.sleep(0.5)

    def cycle_window_size(self):
        self.current_size_index = (self.current_size_index + 1) % len(self.SIZES)
        w, h = self.SIZES[self.current_size_index]
        self.resize(w, h)

    def set_transparency(self, enabled):
        self.is_transparent_mode = enabled
        self.trans_switch.set_checked(enabled)
        
        # Disable drop shadow in transparent mode for pristine clarity
        if hasattr(self, 'shadow_effect'):
            self.shadow_effect.setEnabled(not enabled)

        # Synchronously update all message bubbles
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, MessageBubble):
                widget.apply_transparency(enabled)
        
        # Synchronously toggle dynamic Type-through switch
        if self.is_transparent_mode:
            self.type_through_switch.show()
            self.type_through_switch.set_checked(self.is_click_through)
        else:
            self.type_through_switch.hide()
            if self.is_click_through:
                self.set_type_through(False)
        
        self.apply_container_style()
        self.main_container.update()
        self.update()
        QApplication.processEvents()

    def toggle_transparency(self):
        self.signals.transparency_toggled_signal.emit(not self.is_transparent_mode)

    def set_type_through(self, enabled):
        self.is_click_through = enabled
        self.type_through_switch.set_checked(enabled)
        
        # Make the middle scroll area and chat transparent to mouse clicks
        self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        if self.scroll_area.viewport():
            self.scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        self.chat_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        
        # Header, dock, and toggle switch remain 100% clickable so you can turn it off anytime!
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            widget = item.widget() if item else None
            if widget:
                widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
                if hasattr(widget, 'text_browser'):
                    widget.text_browser.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
                    if widget.text_browser.viewport():
                        widget.text_browser.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        
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

    def add_message(self, text="", is_user=False, is_image=False, pixmap=None):
        bubble = MessageBubble(text, is_user=is_user, is_image=is_image, pixmap=pixmap, parent_assistant=self)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        QTimer.singleShot(40, self.scroll_to_bottom)
        return bubble

    def scroll_to_bottom(self):
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def on_selection_action(self, action_type, full_prompt):
        self.add_message(full_prompt, is_user=True)
        self.current_ai_bubble = self.add_message("", is_user=False)
        threading.Thread(target=self._stream_response, args=(full_prompt,), daemon=True).start()

    def toggle_input_card(self):
        if self.input_card.isVisible():
            self.input_card.hide()
        else:
            self.input_card.show()
            self.text_input.setFocus()

    def send_text_prompt(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self.input_card.hide()
        self.add_message(text, is_user=True)

        if not self.ai_ready:
            self.add_message("⚠️ API key required. Click ⚙️ to configure.", is_user=False)
            return

        self.current_ai_bubble = self.add_message("", is_user=False)
        threading.Thread(target=self._stream_response, args=(text,), daemon=True).start()

    def _stream_response(self, prompt, image_bytes=None):
        candidate_models = [
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-pro-latest",
            "gemini-2.5-flash-lite"
        ]

        success = False
        last_error = ""

        if image_bytes:
            contents = [
                prompt,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/jpeg"
                )
            ]
        else:
            contents = prompt

        persona_instruction = self.config.get("PERSONA", "")
        system_prompt = (
            f"{persona_instruction}\n"
            "You are an expert real-time assistant. Provide direct, concise, and structured answers immediately."
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
        if self.current_ai_bubble:
            self.current_ai_bubble.append_text(chunk)
            self.scroll_to_bottom()

    def on_stream_finished(self):
        pass

    def capture_screen_and_analyze(self):
        was_visible = self.isVisible()
        if was_visible:
            self.hide()
            QApplication.processEvents()
            time.sleep(0.07)

        screen = QGuiApplication.primaryScreen()
        if not screen:
            if was_visible:
                self.show_and_activate()
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

        if not self.ai_ready:
            self.add_message("⚠️ API key required. Click ⚙️ to configure.", is_user=False)
            return

        self.current_ai_bubble = self.add_message("", is_user=False)
        prompt = "Analyze this screen. Solve any question/problem visible or explain the active content immediately with clear steps."
        threading.Thread(target=self._stream_response, args=(prompt, image_bytes), daemon=True).start()

    def start_voice_input(self):
        if not SPEECH_AVAILABLE or self.is_listening:
            return
        self.is_listening = True

        def listen_worker():
            try:
                r = sr.Recognizer()
                r.pause_threshold = 0.8
                r.dynamic_energy_threshold = True
                with sr.Microphone() as src:
                    r.adjust_for_ambient_noise(src, duration=0.3)
                    audio = r.listen(src, timeout=5, phrase_time_limit=15)
                
                text = ""
                try:
                    text = r.recognize_google(audio, language="en-IN")
                except Exception:
                    text = r.recognize_google(audio, language="en-US")
                
                if text:
                    self.signals.voice_transcribed.emit(text)
            except Exception as e:
                print(f"Voice error: {e}")
            finally:
                self.is_listening = False

        threading.Thread(target=listen_worker, daemon=True).start()

    def on_voice_transcribed(self, text):
        self.text_input.setText(text)
        self.send_text_prompt()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not self.text_input.hasFocus():
            self.start_voice_input()
        else:
            super().keyPressEvent(event)

    def toggle_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_and_activate()

    def show_and_activate(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor("#38bdf8"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "⚡")
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Aura Assistant")

        tray_menu = QMenu()
        show_action = QAction("Show Assistant", self)
        show_action.triggered.connect(self.show_and_activate)
        tray_menu.addAction(show_action)

        cam_action = QAction("📷 1-Click Screen Capture", self)
        cam_action.triggered.connect(self.capture_screen_and_analyze)
        tray_menu.addAction(cam_action)

        trans_action = QAction("⚪ Toggle Transparent", self)
        trans_action.triggered.connect(self.toggle_transparency)
        tray_menu.addAction(trans_action)

        tray_menu.addSeparator()
        key_action = QAction("⚙️ Set API Key", self)
        key_action.triggered.connect(self.prompt_api_key)
        tray_menu.addAction(key_action)

        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(lambda r: self.toggle_visibility() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray_icon.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_position is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, event):
        self.drag_position = None

    def setup_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey('ctrl+space', lambda: self.signals.toggle_window_signal.emit())
                keyboard.add_hotkey('ctrl+g', lambda: self.toggle_transparency())
                keyboard.add_hotkey('ctrl+t', lambda: self.toggle_type_through_global())
                keyboard.add_hotkey('ctrl+shift+s', lambda: self.signals.trigger_camera_signal.emit())
                keyboard.add_hotkey('ctrl+shift+v', lambda: self.start_voice_input())
            except Exception as e:
                print(f"Failed to bind global hotkeys: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    assistant = NativeAssistant()
    assistant.show()
    sys.exit(app.exec())
