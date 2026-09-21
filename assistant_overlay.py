import sys
import traceback
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt, QUrl

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
        # Sleek frameless design, always-on-top (PyQt6 syntax)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        
        # Massive 800x800 size
        self.setGeometry(100, 100, 800, 800)
        
        # Solid background to prevent transparency glitching
        self.setStyleSheet("background-color: white;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Web Browser
        try:
            self.browser = QWebEngineView()
            self.browser.setUrl(QUrl("https://gemini.google.com/"))
            layout.addWidget(self.browser)
        except Exception as e:
            print(f"Error initializing WebEngine: {e}")

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
