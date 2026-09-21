import sys
import traceback
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import Qt, QUrl

# Try importing keyboard, but don't crash if it fails
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("Warning: keyboard module not found. Global hotkeys disabled.")

class AssistantOverlay(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.setup_hotkeys()

    def initUI(self):
        # Sleek frameless design, always-on-top
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        # Increased size for better visibility
        self.setGeometry(100, 100, 800, 800)
        self.setWindowOpacity(0.95)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Web Browser - Now pointing to an AI Assistant
        try:
            self.browser = QWebEngineView()
            self.browser.setUrl(QUrl("https://gemini.google.com/"))
            layout.addWidget(self.browser)
        except Exception as e:
            print(f"Error initializing WebEngine: {e}")
            layout.addWidget(QLabel("Failed to load WebBrowser. Check console."))

    def setup_hotkeys(self):
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey('ctrl+space', self.toggle_visibility)
            except Exception as e:
                print(f"Failed to bind hotkey: {e}")

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()
            self.raise_()

    # Allow closing with Escape key
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        overlay = AssistantOverlay()
        overlay.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        traceback.print_exc()
