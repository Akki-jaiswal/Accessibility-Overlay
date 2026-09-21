import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel, QTabWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
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
        self.oldPos = None
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
        title_layout.setContentsMargins(10, 0, 5, 0)
        
        title_label = QLabel("AI Assistant")
        title_label.setStyleSheet("color: #666; font-family: sans-serif; font-size: 12px; font-weight: bold;")
        title_layout.addWidget(title_label)

        # --- NEW TAB BUTTON ---
        self.new_tab_btn = QPushButton("+ New Tab")
        self.new_tab_btn.setStyleSheet("QPushButton { border: none; font-weight: bold; color: #444; background-color: #e0e0e0; padding: 4px 8px; border-radius: 3px; margin-left: 10px; } QPushButton:hover { background-color: #ccc; }")
        # Opens a standard Google search page so you can freely browse the web!
        self.new_tab_btn.clicked.connect(lambda: self.add_new_tab(QUrl("https://www.google.com/"), "Google Search"))
        title_layout.addWidget(self.new_tab_btn)

        title_layout.addStretch() # Pushes the next buttons to the far right

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
        self.profile = QWebEngineProfile("GoogleAIProfile")
        storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_data")
        self.profile.setCachePath(storage_path)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profile.setHttpUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0")
        # ------------------------------------

        # --- TABS SETUP ---
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True) # Makes tabs look integrated and sleek
        self.tabs.setTabsClosable(True) # Adds the 'x' to each tab
        self.tabs.tabCloseRequested.connect(self.close_tab)
        
        # Sleek styling for the tabs
        self.tabs.setStyleSheet("""
            QTabBar::tab { background: #eee; padding: 5px 15px; border-right: 1px solid #ccc; border-bottom: 1px solid #ccc; }
            QTabBar::tab:selected { background: white; font-weight: bold; border-bottom: none; }
        """)
        layout.addWidget(self.tabs)

        # Add the first default tab
        self.add_new_tab(QUrl("https://gemini.google.com/"), "Gemini AI")

    # --- TAB MANAGEMENT METHODS ---
    def add_new_tab(self, url, label="Loading..."):
        browser = QWebEngineView()
        
        # Bind our custom profile so EVERY tab shares the same login!
        page = QWebEnginePage(self.profile, browser)
        browser.setPage(page)
        browser.setUrl(url)
        
        # Add browser to the tab widget
        i = self.tabs.addTab(browser, label)
        self.tabs.setCurrentIndex(i) # Switch to the new tab immediately
        
        # Dynamically update the tab title when the website loads
        browser.titleChanged.connect(lambda title, browser=browser: self.tabs.setTabText(self.tabs.indexOf(browser), title[:15] + "..." if len(title) > 15 else title))

    def close_tab(self, i):
        if self.tabs.count() < 2:
            self.close() # Close the whole overlay if they close the very last tab
        else:
            self.tabs.removeTab(i)
    # ------------------------------

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
