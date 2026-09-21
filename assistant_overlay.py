import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtCore import Qt, QUrl, QPoint

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("Warning: keyboard module not found. Global hotkeys disabled.")

class AssistantOverlay(QMainWindow):
    def __init__(self):
        super().__init__()
        self.oldPos = None # Used for dragging
        self.initUI()
        self.setup_hotkeys()

    def initUI(self):
        # Sleek frameless design, always-on-top
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setGeometry(100, 100, 800, 800)
        self.setStyleSheet("background-color: white;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Custom Sleek Title Bar ---
        self.title_bar = QWidget()
        self.title_bar.setStyleSheet("background-color: #f5f5f5; border-bottom: 1px solid #e0e0e0;")
        self.title_bar.setFixedHeight(30)
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(15, 0, 5, 0)
        
        title_label = QLabel("AI Assistant (Click and drag this bar to move)")
        title_label.setStyleSheet("color: #666; font-family: sans-serif; font-size: 12px;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.setStyleSheet("QPushButton { border: none; font-weight: bold; color: #555; } QPushButton:hover { background-color: #ddd; }")
        self.min_btn.clicked.connect(self.showMinimized)
        title_layout.addWidget(self.min_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setStyleSheet("QPushButton { border: none; font-weight: bold; color: #555; } QPushButton:hover { background-color: #ff4444; color: white; }")
        self.close_btn.clicked.connect(self.close)
        title_layout.addWidget(self.close_btn)

        layout.addWidget(self.title_bar)
        # ------------------------------

        # --- Persistent Web Session Logic ---
        # Instead of the default profile (which sometimes ignores local folders), we create a named custom profile.
        self.profile = QWebEngineProfile("GoogleAIProfile")
        storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_data")
        
        # We must set BOTH Cache and Storage paths to force Chromium to write to the hard drive
        self.profile.setCachePath(storage_path)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        
        # Firefox Disguise to bypass Google's bot detection
        self.profile.setHttpUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0")
        # ------------------------------------

        # Web Browser
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage
            self.browser = QWebEngineView()
            
            # Explicitly bind our custom profile to the page
            page = QWebEnginePage(self.profile, self.browser)
            self.browser.setPage(page)
            
            self.browser.setUrl(QUrl("https://gemini.google.com/"))
            layout.addWidget(self.browser)
        except Exception as e:
            print(f"Error initializing WebEngine: {e}")

    # --- Window Dragging Logic ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 30:
            self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.oldPos is not None:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.oldPos = None
    # -----------------------------

    def setup_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey('ctrl+space', self.toggle_visibility)
            except Exception as e:
                print(f"Failed to bind hotkey: {e}")

    def toggle_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()
            self.raise_()

    # Allow closing with Escape key
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        overlay = AssistantOverlay()
        overlay.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        traceback.print_exc()
