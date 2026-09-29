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
    QDialog, QTextEdit, QMenu as QContextMenu
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject, QTimer, QBuffer, QIODevice, QRect
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
        "PERSONA": "I am Akshay, a 3rd year BTech Computer Science student focusing on backend architecture, data analysis, and building AI tools. When answering, be direct, concise, and structured."
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
    status_updated = pyqtSignal(str, str)
    show_window_signal = pyqtSignal()
    toggle_window_signal = pyqtSignal()
    trigger_camera_signal = pyqtSignal()


# --- Floating Quick Action Tooltip (Explain / What / How) ---
class SelectionActionPopup(QFrame):
    action_triggered = pyqtSignal(str, str)  # (action_type, selected_text)

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


class MessageBubble(QFrame):
    def __init__(self, text, is_user=False, is_image=False, pixmap=None, parent_assistant=None):
        super().__init__(parent_assistant)
        self.parent_assistant = parent_assistant
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.raw_text = text
        self.is_user = is_user
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        if is_image and pixmap:
            img_label = QLabel()
            scaled_pixmap = pixmap.scaledToWidth(260, Qt.TransformationMode.SmoothTransformation)
            img_label.setPixmap(scaled_pixmap)
            img_label.setStyleSheet("border-radius: 6px; margin-bottom: 4px;")
            layout.addWidget(img_label)

        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setReadOnly(True)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        if is_user:
            self.setStyleSheet("""
                QFrame {
                    background-color: #1e293b;
                    border: 1px solid #334155;
                    border-radius: 12px;
                    margin-left: 60px;
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
                    border-radius: 12px;
                    margin-right: 40px;
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
                font-size: 13.5px;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
        """)

        # Listen for selection to show [ Explain | What | How ] popup
        self.text_browser.selectionChanged.connect(self.on_selection_changed)
            
        layout.addWidget(self.text_browser)
        self.update_content(text)

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
            body {{ color: #f1f5f9; font-family: 'Segoe UI', sans-serif; font-size: 13.5px; line-height: 1.5; margin: 0; padding: 0; }}
            p {{ margin: 0 0 6px 0; }}
            strong {{ color: #38bdf8; font-weight: 600; }}
            h1, h2, h3, h4 {{ color: #60a5fa; margin: 6px 0 3px 0; font-size: 14px; font-weight: bold; }}
            ul, ol {{ margin: 0 0 6px 16px; padding: 0; }}
            li {{ margin-bottom: 3px; }}
            code {{ background-color: #0b1120; color: #7dd3fc; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace; font-size: 12.5px; }}
            pre {{ background-color: #0b1120; padding: 8px; border-radius: 6px; border: 1px solid #1e293b; margin: 4px 0; }}
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
        doc.setTextWidth(380)
        h = int(doc.size().height()) + 14
        self.text_browser.setFixedHeight(max(24, h))


class NativeAssistant(QMainWindow):
    SIZES = [
        (480, 680),  # Stage 0: Default
        (620, 780),  # Stage 1: Expanded
        (760, 880)   # Stage 2: Wide
    ]

    def __init__(self):
        super().__init__()
        self.oldPos = None
        self.is_transparent_mode = False
        self.is_click_through = False
        self.is_listening = False
        self.current_size_index = 0
        self.signals = WorkerSignals()
        self.current_ai_bubble = None
        self.config = load_config()
        self.client = None
        self.active_model_name = "gemini-flash-lite-latest"
        self.current_mode = "manual"

        # Floating quick-action selection popup
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
        self.setMinimumSize(360, 480)

        # Main container with Angel-style dark navy surface
        self.main_container = QWidget(self)
        self.main_container.setObjectName("MainContainer")
        self.apply_container_style()

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 8)
        self.main_container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.main_container)
        container_layout.setContentsMargins(14, 10, 14, 12)
        container_layout.setSpacing(8)

        # ==========================================
        # 1. TOP HEADER (Back, Mode Switch, Logo, Window Controls)
        # ==========================================
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        # Back Button
        self.back_btn = QPushButton("←")
        self.back_btn.setFixedSize(24, 24)
        self.back_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #94a3b8; font-size: 14px; font-weight: bold; }
            QPushButton:hover { color: #f8fafc; }
        """)
        header_layout.addWidget(self.back_btn)

        # Manual / Auto Pill Switch
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

        # Settings/Filter icon next to pill
        self.filter_btn = QPushButton("🎛️")
        self.filter_btn.setToolTip("Customize Persona & System Prompt")
        self.filter_btn.setFixedSize(24, 24)
        self.filter_btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 12px; } QPushButton:hover { background: #334155; border-radius: 4px; }")
        self.filter_btn.clicked.connect(self.prompt_persona)
        header_layout.addWidget(self.filter_btn)

        header_layout.addStretch()

        # Center Brand Logo: 🪽 Angel
        self.brand_label = QLabel("🪽 Angel")
        self.brand_label.setStyleSheet("color: #cbd5e1; font-size: 13px; font-weight: bold; font-family: 'Segoe UI', sans-serif;")
        header_layout.addWidget(self.brand_label)

        header_layout.addStretch()

        # Window Controls: Minimize, 3-State Maximize, Close
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(22, 22)
        self.min_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #94a3b8; font-size: 12px; font-weight: bold; } QPushButton:hover { background-color: #334155; color: white; border-radius: 4px; }")
        self.min_btn.clicked.connect(self.hide)
        header_layout.addWidget(self.min_btn)

        self.max_btn = QPushButton("□")
        self.max_btn.setToolTip("Cycle Size (Compact / Medium / Large)")
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
        self.chat_layout.setSpacing(6)
        self.chat_layout.addStretch()

        self.scroll_area.setWidget(self.chat_widget)
        container_layout.addWidget(self.scroll_area)

        # Helper hint above input
        self.hint_label = QLabel("Chat · type a message or ask a follow-up question")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 500;")
        container_layout.addWidget(self.hint_label)

        # ==========================================
        # 3. TEXT INPUT BAR
        # ==========================================
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
        # 4. BOTTOM DOCK (Settings, Center Actions, Transparency Toggle)
        # ==========================================
        self.dock = QWidget()
        dock_layout = QHBoxLayout(self.dock)
        dock_layout.setContentsMargins(0, 2, 0, 0)
        dock_layout.setSpacing(8)

        # Left: ⚙️ Settings + Status Badge
        self.key_btn = QPushButton("⚙️")
        self.key_btn.setToolTip("Settings / Gemini API Key")
        self.key_btn.setFixedSize(30, 30)
        self.key_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; border: 1px solid #334155; border-radius: 15px; font-size: 13px; }
            QPushButton:hover { background-color: #334155; }
        """)
        self.key_btn.clicked.connect(self.prompt_api_key)
        dock_layout.addWidget(self.key_btn)

        self.status_pill = QLabel("● Active")
        self.status_pill.setStyleSheet("background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; padding: 2px 8px; font-size: 11px;")
        dock_layout.addWidget(self.status_pill)

        dock_layout.addStretch()

        # Center Action Pill Dock (📷 Camera, 🎙️ Mic, 💬 Chat, ➕ Add)
        self.center_dock = QFrame()
        self.center_dock.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 18px;
            }
        """)
        center_layout = QHBoxLayout(self.center_dock)
        center_layout.setContentsMargins(4, 2, 4, 2)
        center_layout.setSpacing(6)

        # 📷 Instant Full-Screen Snapshot
        self.cam_btn = QPushButton("📷")
        self.cam_btn.setToolTip("1-Click Screen Capture (Ctrl+Shift+S)")
        self.cam_btn.setFixedSize(30, 30)
        self.cam_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; font-size: 14px; }
            QPushButton:hover { background-color: #334155; border-radius: 15px; }
        """)
        self.cam_btn.clicked.connect(self.capture_screen_and_analyze)
        center_layout.addWidget(self.cam_btn)

        # 🎙️ Blue Highlight Mic Button
        self.voice_btn = QPushButton("🎙️")
        self.voice_btn.setToolTip("Voice Dictation (Ctrl+Shift+V)")
        self.voice_btn.setFixedSize(32, 32)
        self.voice_btn.setStyleSheet("""
            QPushButton { background-color: #2563eb; color: white; border: none; border-radius: 16px; font-size: 14px; }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        self.voice_btn.clicked.connect(self.start_voice_input)
        center_layout.addWidget(self.voice_btn)

        # 💬 Follow-up
        self.follow_btn = QPushButton("💬")
        self.follow_btn.setToolTip("Quick Follow-up")
        self.follow_btn.setFixedSize(30, 30)
        self.follow_btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 13px; } QPushButton:hover { background-color: #334155; border-radius: 15px; }")
        self.follow_btn.clicked.connect(lambda: self.text_input.setFocus())
        center_layout.addWidget(self.follow_btn)

        # ➕ Attach / Context
        self.add_btn = QPushButton("➕")
        self.add_btn.setToolTip("Add Context")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setStyleSheet("QPushButton { background: transparent; border: none; font-size: 13px; } QPushButton:hover { background-color: #334155; border-radius: 15px; }")
        self.add_btn.clicked.connect(self.prompt_persona)
        center_layout.addWidget(self.add_btn)

        dock_layout.addWidget(self.center_dock)
        dock_layout.addStretch()

        # Right: Click-Through Toggle + Transparent Switch
        self.clickthrough_btn = QPushButton("↖ Type-through")
        self.clickthrough_btn.setCheckable(True)
        self.clickthrough_btn.setToolTip("Allow clicks/typing to pass through to apps underneath")
        self.clickthrough_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; font-size: 11px; padding: 3px 8px; }
            QPushButton:hover { color: #f8fafc; }
        """)
        self.clickthrough_btn.clicked.connect(self.toggle_click_through)
        dock_layout.addWidget(self.clickthrough_btn)

        self.trans_btn = QPushButton("⚪ Transparent")
        self.trans_btn.setCheckable(True)
        self.trans_btn.setToolTip("Toggle 100% Transparent Wallpaper HUD (Ctrl+G)")
        self.trans_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; font-size: 11px; padding: 3px 8px; }
            QPushButton:hover { color: #38bdf8; }
        """)
        self.trans_btn.clicked.connect(self.toggle_transparency)
        dock_layout.addWidget(self.trans_btn)

        container_layout.addWidget(self.dock)
        self.setCentralWidget(self.main_container)

        # Initial clean greeting matching Angel
        self.add_message("Hi! I'm Angel. I can help you silently in all online meetings and interviews.", is_user=False)

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
                    background-color: rgba(15, 23, 42, 0.95);
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
        else:
            self.auto_btn.setChecked(True)
            self.auto_btn.setStyleSheet("background-color: #10b981; color: #ffffff; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")
            self.manual_btn.setChecked(False)
            self.manual_btn.setStyleSheet("background-color: transparent; color: #94a3b8; font-size: 11px; font-weight: bold; border: none; border-radius: 10px; padding: 0 10px;")

    def cycle_window_size(self):
        self.current_size_index = (self.current_size_index + 1) % len(self.SIZES)
        w, h = self.SIZES[self.current_size_index]
        self.resize(w, h)

    def toggle_transparency(self):
        self.is_transparent_mode = not self.is_transparent_mode
        if self.is_transparent_mode:
            self.trans_btn.setText("🔵 Transparent")
            self.trans_btn.setStyleSheet("background-color: #2563eb; color: #ffffff; border: 1px solid #3b82f6; border-radius: 12px; font-size: 11px; padding: 3px 8px;")
            self.apply_container_style()
        else:
            self.trans_btn.setText("⚪ Transparent")
            self.trans_btn.setStyleSheet("background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; font-size: 11px; padding: 3px 8px;")
            self.apply_container_style()

    def toggle_click_through(self):
        self.is_click_through = not self.is_click_through
        if self.is_click_through:
            self.clickthrough_btn.setText("🔵 Type-through: ON")
            self.clickthrough_btn.setStyleSheet("background-color: #2563eb; color: #ffffff; border: 1px solid #3b82f6; border-radius: 12px; font-size: 11px; padding: 3px 8px;")
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
            self.show()
        else:
            self.clickthrough_btn.setText("↖ Type-through")
            self.clickthrough_btn.setStyleSheet("background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; font-size: 11px; padding: 3px 8px;")
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, False)
            self.show()

    def prompt_persona(self):
        persona, ok = QInputDialog.getMultiLineText(
            self, "Customize Assistant Persona",
            "Define your background, job role, or system prompt for the AI:",
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

    def send_text_prompt(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
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
            "You are an expert real-time meeting and interview co-pilot. "
            "Provide crisp, structured, high-accuracy answers immediately without fluff or boilerplate."
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
        prompt = "Analyze this screen. If there is a question or problem, solve it with direct steps. If there is code, explain or debug it."
        threading.Thread(target=self._stream_response, args=(prompt, image_bytes), daemon=True).start()

    def start_voice_input(self):
        if not SPEECH_AVAILABLE or self.is_listening:
            return
        self.is_listening = True
        self.status_pill.setText("🔴 Listening...")
        self.status_pill.setStyleSheet("background-color: #7f1d1d; color: #fca5a5; border: 1px solid #ef4444; border-radius: 12px; padding: 2px 8px; font-size: 11px;")

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
                self.status_pill.setText("● Active")
                self.status_pill.setStyleSheet("background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 12px; padding: 2px 8px; font-size: 11px;")

        threading.Thread(target=listen_worker, daemon=True).start()

    def on_voice_transcribed(self, text):
        self.text_input.setText(text)
        self.send_text_prompt()

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
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "🪽")
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Angel Assistant")

        tray_menu = QMenu()
        show_action = QAction("Show Assistant", self)
        show_action.triggered.connect(self.show_and_activate)
        tray_menu.addAction(show_action)

        cam_action = QAction("📸 1-Click Screen Capture", self)
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
            self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.oldPos is not None:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.oldPos = None

    def setup_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey('ctrl+space', lambda: self.signals.toggle_window_signal.emit())
                keyboard.add_hotkey('ctrl+g', lambda: self.toggle_transparency())
                keyboard.add_hotkey('ctrl+shift+s', lambda: self.signals.trigger_camera_signal.emit())
                keyboard.add_hotkey('ctrl+shift+v', lambda: self.start_voice_input())
            except Exception as e:
                print(f"Failed to bind global hotkeys: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    assistant = NativeAssistant()
    assistant.show()
    sys.exit(app.exec())
