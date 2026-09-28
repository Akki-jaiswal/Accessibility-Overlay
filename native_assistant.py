import sys
import os
import io
import json
import threading
import time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QScrollArea, QFrame, QTextBrowser,
    QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect, QInputDialog
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject, QTimer, QBuffer, QIODevice
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QGuiApplication, QAction
from PIL import Image

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

# API Key config path
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_api_key():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                return data.get("GEMINI_API_KEY", "")
        except Exception:
            pass
    return os.environ.get("GEMINI_API_KEY", "")


def save_api_key(key):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump({"GEMINI_API_KEY": key}, f)
    except Exception as e:
        print(f"Error saving config: {e}")


class WorkerSignals(QObject):
    stream_chunk = pyqtSignal(str)
    stream_finished = pyqtSignal()
    voice_transcribed = pyqtSignal(str)
    status_updated = pyqtSignal(str, str)  # (text, color)
    show_window_signal = pyqtSignal()
    toggle_window_signal = pyqtSignal()
    trigger_camera_signal = pyqtSignal()


class MessageBubble(QFrame):
    def __init__(self, text, is_user=False, is_image=False, pixmap=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.raw_text = text
        self.is_user = is_user
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        sender_label = QLabel("You" if is_user else "Gemini AI")
        sender_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #94a3b8;")
        layout.addWidget(sender_label)

        if is_image and pixmap:
            img_label = QLabel()
            scaled_pixmap = pixmap.scaledToWidth(260, Qt.TransformationMode.SmoothTransformation)
            img_label.setPixmap(scaled_pixmap)
            img_label.setStyleSheet("border-radius: 6px; margin-top: 4px;")
            layout.addWidget(img_label)

        # Rich Markdown Text Browser
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setReadOnly(True)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        if is_user:
            self.setStyleSheet("""
                QFrame {
                    background-color: #1e3a8a;
                    border: 1px solid #2563eb;
                    border-radius: 12px;
                    margin-left: 35px;
                    margin-right: 4px;
                    margin-top: 3px;
                    margin-bottom: 3px;
                }
            """)
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #f8fafc;
                    font-size: 13px;
                    font-family: 'Segoe UI', sans-serif;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #1e293b;
                    border: 1px solid #334155;
                    border-radius: 12px;
                    margin-right: 35px;
                    margin-left: 4px;
                    margin-top: 3px;
                    margin-bottom: 3px;
                }
            """)
            self.text_browser.setStyleSheet("""
                QTextBrowser {
                    background: transparent;
                    border: none;
                    color: #f1f5f9;
                    font-size: 13px;
                    font-family: 'Segoe UI', sans-serif;
                }
            """)
            
        layout.addWidget(self.text_browser)
        self.update_content(text)

    def update_content(self, text):
        self.raw_text = text
        self.text_browser.setMarkdown(text)
        self.adjust_height()

    def append_text(self, new_text):
        self.raw_text += new_text
        self.text_browser.setMarkdown(self.raw_text)
        self.adjust_height()

    def adjust_height(self):
        doc = self.text_browser.document()
        doc.setTextWidth(360)
        h = int(doc.size().height()) + 12
        self.text_browser.setFixedHeight(max(24, h))


class NativeAssistant(QMainWindow):
    def __init__(self):
        super().__init__()
        self.oldPos = None
        self.is_ghost_mode = False
        self.is_listening = False
        self.signals = WorkerSignals()
        self.current_ai_bubble = None
        self.api_key = load_api_key()
        self.client = None
        self.active_model_name = "gemini-flash-latest"

        self.init_ai()
        self.init_ui()
        self.init_tray()
        self.setup_hotkeys()

        # Connect signals
        self.signals.stream_chunk.connect(self.on_stream_chunk)
        self.signals.stream_finished.connect(self.on_stream_finished)
        self.signals.voice_transcribed.connect(self.on_voice_transcribed)
        self.signals.status_updated.connect(self.on_status_updated)
        self.signals.show_window_signal.connect(self.show_and_activate)
        self.signals.toggle_window_signal.connect(self.toggle_visibility)
        self.signals.trigger_camera_signal.connect(self.capture_screen_and_analyze)

    def init_ai(self):
        if self.api_key and GENAI_AVAILABLE:
            try:
                self.client = genai.Client(api_key=self.api_key)
                self.ai_ready = True
                print("Gemini GenAI client initialized.")
            except Exception as e:
                print(f"Failed to init Gemini API: {e}")
                self.ai_ready = False
        else:
            self.ai_ready = False

    def init_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(460, 680)
        self.setMinimumSize(360, 480)

        # Central widget container with dark modern theme
        self.main_container = QWidget(self)
        self.main_container.setObjectName("MainContainer")
        self.main_container.setStyleSheet("""
            QWidget#MainContainer {
                background-color: rgba(15, 23, 42, 0.95);
                border: 1px solid #334155;
                border-radius: 16px;
            }
        """)

        # Drop shadow for clean floating look
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 8)
        self.main_container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.main_container)
        container_layout.setContentsMargins(12, 10, 12, 12)
        container_layout.setSpacing(8)

        # --- Top Header / Toolbar ---
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(6)

        # Title / Status
        self.title_label = QLabel("⚡ Native AI")
        self.title_label.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self.title_label)

        self.status_badge = QLabel("Ready")
        self.status_badge.setStyleSheet("color: #94a3b8; font-size: 11px; margin-left: 4px;")
        header_layout.addWidget(self.status_badge)

        header_layout.addStretch()

        # 📸 Quick Camera Button (1-Click screen analyze)
        self.cam_btn = QPushButton("📸")
        self.cam_btn.setToolTip("1-Click Screen Capture & Analyze (Ctrl+Shift+S)")
        self.cam_btn.setFixedSize(28, 28)
        self.cam_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; border: 1px solid #475569; border-radius: 6px; font-size: 13px; }
            QPushButton:hover { background-color: #3b82f6; border-color: #60a5fa; }
        """)
        self.cam_btn.clicked.connect(self.capture_screen_and_analyze)
        header_layout.addWidget(self.cam_btn)

        # 👻 Ghost Mode Button
        self.ghost_btn = QPushButton("👻")
        self.ghost_btn.setToolTip("Toggle Ghost Transparency (Ctrl+G)")
        self.ghost_btn.setFixedSize(28, 28)
        self.ghost_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; border: 1px solid #475569; border-radius: 6px; font-size: 13px; }
            QPushButton:hover { background-color: #6366f1; border-color: #818cf8; }
        """)
        self.ghost_btn.clicked.connect(self.toggle_ghost_mode)
        header_layout.addWidget(self.ghost_btn)

        # ⚙️ Settings / API Key Button
        self.key_btn = QPushButton("⚙️")
        self.key_btn.setToolTip("Set Gemini API Key")
        self.key_btn.setFixedSize(28, 28)
        self.key_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; border: 1px solid #475569; border-radius: 6px; font-size: 13px; }
            QPushButton:hover { background-color: #334155; }
        """)
        self.key_btn.clicked.connect(self.prompt_api_key)
        header_layout.addWidget(self.key_btn)

        # Minimize Button
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(28, 28)
        self.min_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: none; color: #94a3b8; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background-color: #334155; color: white; border-radius: 6px; }
        """)
        self.min_btn.clicked.connect(self.hide)
        header_layout.addWidget(self.min_btn)

        # Close Button
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: none; color: #94a3b8; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background-color: #ef4444; color: white; border-radius: 6px; }
        """)
        self.close_btn.clicked.connect(self.close)
        header_layout.addWidget(self.close_btn)

        container_layout.addWidget(self.header)

        # --- Chat Scroll Area ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                border: none;
                background: rgba(15, 23, 42, 0.4);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #475569;
                border-radius: 3px;
            }
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

        # --- Input Bar ---
        self.input_container = QWidget()
        self.input_container.setStyleSheet("""
            QWidget {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
            }
        """)
        input_layout = QHBoxLayout(self.input_container)
        input_layout.setContentsMargins(8, 4, 8, 4)
        input_layout.setSpacing(6)

        # Voice Dictation Button
        self.voice_btn = QPushButton("🎙️")
        self.voice_btn.setToolTip("Voice Dictation (Ctrl+Shift+V)")
        self.voice_btn.setFixedSize(30, 30)
        self.voice_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; font-size: 15px; }
            QPushButton:hover { background-color: #334155; border-radius: 6px; }
        """)
        self.voice_btn.clicked.connect(self.start_voice_input)
        input_layout.addWidget(self.voice_btn)

        # Text Input Field
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Ask AI or press 📸 for instant screen solve...")
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
        input_layout.addWidget(self.text_input)

        # Send Button
        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(30, 30)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.send_btn.clicked.connect(self.send_text_prompt)
        input_layout.addWidget(self.send_btn)

        container_layout.addWidget(self.input_container)

        self.setCentralWidget(self.main_container)

        # Initial Welcome Message
        if not self.api_key:
            self.add_message("👋 Welcome! Click the ⚙️ button at the top to add your free Gemini API Key and start instant AI streaming.", is_user=False)
        else:
            self.add_message("⚡ Native AI ready. Press 📸 or Ctrl+Shift+S for instant full-screen capture.", is_user=False)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        # Create a clean tray icon programmatically
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor("#38bdf8"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "AI")
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Native AI Assistant")

        tray_menu = QMenu()
        show_action = QAction("Show Assistant", self)
        show_action.triggered.connect(self.show_and_activate)
        tray_menu.addAction(show_action)

        cam_action = QAction("📸 1-Click Screen Capture", self)
        cam_action.triggered.connect(self.capture_screen_and_analyze)
        tray_menu.addAction(cam_action)

        ghost_action = QAction("👻 Toggle Ghost Mode", self)
        ghost_action.triggered.connect(self.toggle_ghost_mode)
        tray_menu.addAction(ghost_action)

        tray_menu.addSeparator()
        key_action = QAction("⚙️ Set API Key", self)
        key_action.triggered.connect(self.prompt_api_key)
        tray_menu.addAction(key_action)

        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def prompt_api_key(self):
        key, ok = QInputDialog.getText(self, "Gemini API Key", "Enter your Google Gemini API Key:", text=self.api_key)
        if ok and key.strip():
            self.api_key = key.strip()
            save_api_key(self.api_key)
            self.init_ai()
            if self.ai_ready:
                self.add_message("✅ API Key configured successfully! Ready to stream.", is_user=False)
                self.on_status_updated("Ready", "#4ade80")
            else:
                self.add_message("❌ Failed to initialize client. Please check your API key.", is_user=False)

    def add_message(self, text="", is_user=False, is_image=False, pixmap=None):
        bubble = MessageBubble(text, is_user=is_user, is_image=is_image, pixmap=pixmap)
        # Insert before the bottom stretch
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        QTimer.singleShot(50, self.scroll_to_bottom)
        return bubble

    def scroll_to_bottom(self):
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def send_text_prompt(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self.add_message(text, is_user=True)

        if not self.ai_ready:
            self.add_message("⚠️ Please configure your Gemini API key via the ⚙️ settings button first.", is_user=False)
            return

        self.current_ai_bubble = self.add_message("", is_user=False)
        self.on_status_updated("Thinking...", "#38bdf8")

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

        # Prepare contents
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

        fast_config = types.GenerateContentConfig(
            temperature=0.2,
            system_instruction="You are a real-time, high-speed desktop assistant. Answer questions or solve problems directly, accurately, and crisply without unnecessary conversational filler."
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
        self.on_status_updated("Ready", "#4ade80")

    def capture_screen_and_analyze(self):
        # 1. Grab full screen silently from framebuffer without stealing OS window focus
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return

        pixmap = screen.grabWindow(0)
        
        # 2. Downscale if very large to ensure sub-second transmission
        if pixmap.width() > 1600:
            pixmap_scaled = pixmap.scaledToWidth(1440, Qt.TransformationMode.FastTransformation)
        else:
            pixmap_scaled = pixmap

        # 3. Fast In-Memory JPEG Compression (80KB vs 6MB PNG)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        pixmap_scaled.save(buffer, "JPEG", 80)
        image_bytes = bytes(buffer.data())

        # Show preview in UI
        self.show_and_activate()
        self.add_message("📸 Screen Analysis", is_user=True, is_image=True, pixmap=pixmap)

        if not self.ai_ready:
            self.add_message("⚠️ Gemini API key not set. Click ⚙️ to configure.", is_user=False)
            return

        self.current_ai_bubble = self.add_message("", is_user=False)
        self.on_status_updated("Analyzing...", "#fbbf24")

        prompt = "Analyze this screen. Solve any question/problem visible or explain the active content immediately with clear steps."
        threading.Thread(target=self._stream_response, args=(prompt, image_bytes), daemon=True).start()

    def start_voice_input(self):
        if not SPEECH_AVAILABLE:
            self.add_message("⚠️ SpeechRecognition or PyAudio missing.", is_user=False)
            return
        if self.is_listening:
            return
        self.is_listening = True
        self.on_status_updated("Listening...", "#ef4444")

        def listen_worker():
            try:
                r = sr.Recognizer()
                r.pause_threshold = 0.8
                r.dynamic_energy_threshold = True
                with sr.Microphone() as src:
                    r.adjust_for_ambient_noise(src, duration=0.4)
                    audio = r.listen(src, timeout=5, phrase_time_limit=15)
                
                # Try multi-lingual English recognition (en-IN first, fallback to en-US)
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
                self.signals.status_updated.emit("Ready", "#4ade80")

        threading.Thread(target=listen_worker, daemon=True).start()

    def on_voice_transcribed(self, text):
        self.text_input.setText(text)
        self.send_text_prompt()

    def on_status_updated(self, text, color):
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; margin-left: 4px;")

    def toggle_ghost_mode(self):
        if not self.is_ghost_mode:
            # Ghost Mode: 45% transparent, hides inputs, floats text over screen
            self.setWindowOpacity(0.45)
            self.input_container.hide()
            self.is_ghost_mode = True
            self.ghost_btn.setStyleSheet("""
                QPushButton { background-color: #6366f1; border: 1px solid #818cf8; border-radius: 6px; font-size: 13px; }
            """)
        else:
            self.setWindowOpacity(1.0)
            self.input_container.show()
            self.is_ghost_mode = False
            self.ghost_btn.setStyleSheet("""
                QPushButton { background-color: #1e293b; border: 1px solid #475569; border-radius: 6px; font-size: 13px; }
                QPushButton:hover { background-color: #6366f1; border-color: #818cf8; }
            """)

    def toggle_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_and_activate()

    def show_and_activate(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 40:
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
                keyboard.add_hotkey('ctrl+g', lambda: self.toggle_ghost_mode())
                keyboard.add_hotkey('ctrl+shift+s', lambda: self.signals.trigger_camera_signal.emit())
                keyboard.add_hotkey('ctrl+shift+v', lambda: self.start_voice_input())
            except Exception as e:
                print(f"Failed to bind global hotkeys: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    assistant = NativeAssistant()
    assistant.show()
    sys.exit(app.exec())
