import sys
import os
import traceback
import json
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel, QTabWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import Qt, QUrl, QPoint
from PyQt6.QtGui import QColor

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
        self.last_injected_text = "" # Tracks what was pasted so we don't double-paste
        self.initUI()
        self.setup_hotkeys()

    def initUI(self):
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setGeometry(100, 100, 800, 800)
        self.setStyleSheet("background-color: #0f172a; color: #f8fafc;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = QWidget()
        self.title_bar.setStyleSheet("background-color: #1e293b; border-bottom: 1px solid #020617;")
        self.title_bar.setFixedHeight(34)
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 0, 5, 0)
        
        title_label = QLabel("AI Assistant")
        title_label.setStyleSheet("color: #cbd5e1; font-family: sans-serif; font-size: 13px; font-weight: bold;")
        title_layout.addWidget(title_label)

        self.new_tab_btn = QPushButton("+ New Tab")
        self.new_tab_btn.setStyleSheet("""
            QPushButton { border: none; font-weight: bold; color: white; background-color: #3b82f6; padding: 4px 10px; border-radius: 4px; margin-left: 10px; }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.new_tab_btn.clicked.connect(lambda: self.add_new_tab(QUrl("https://www.google.com/"), "Google Search"))
        title_layout.addWidget(self.new_tab_btn)

        title_layout.addStretch()

        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.setStyleSheet("QPushButton { border: none; font-weight: bold; color: #cbd5e1; font-size: 14px; } QPushButton:hover { background-color: #334155; color: white; }")
        self.min_btn.clicked.connect(self.showMinimized)
        title_layout.addWidget(self.min_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setStyleSheet("QPushButton { border: none; font-weight: bold; color: #cbd5e1; font-size: 14px; } QPushButton:hover { background-color: #ef4444; color: white; }")
        self.close_btn.clicked.connect(self.close)
        title_layout.addWidget(self.close_btn)

        layout.addWidget(self.title_bar)

        self.profile = QWebEngineProfile("GoogleAIProfile")
        storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_data")
        self.profile.setCachePath(storage_path)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profile.setHttpUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0")
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.ForceDarkMode, True)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { 
                background: #1e293b; 
                color: #94a3b8; 
                padding: 8px 16px; 
                border-right: 1px solid #0f172a; 
            }
            QTabBar::tab:selected { 
                background: #0f172a; 
                color: #f8fafc; 
                font-weight: bold; 
                border-top: 2px solid #3b82f6; 
            }
            QTabBar::tab:hover:!selected { background: #334155; color: white; }
        """)
        layout.addWidget(self.tabs)

        self.add_new_tab(QUrl("https://gemini.google.com/"), "Gemini AI")

    def add_new_tab(self, url, label="Loading..."):
        browser = QWebEngineView()
        page = QWebEnginePage(self.profile, browser)
        page.setBackgroundColor(QColor("#0f172a"))
        browser.setPage(page)
        browser.setUrl(url)
        
        i = self.tabs.addTab(browser, label)
        self.tabs.setCurrentIndex(i)
        browser.titleChanged.connect(lambda title, browser=browser: self.tabs.setTabText(self.tabs.indexOf(browser), title[:15] + "..." if len(title) > 15 else title))

    def close_tab(self, i):
        if self.tabs.count() < 2:
            self.close()
        else:
            self.tabs.removeTab(i)

    # --- CORE FEATURE: Smart Clipboard Injection ---
    def inject_clipboard_to_chat(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        
        # Don't inject if clipboard is empty or if we've already injected this exact text recently
        if not text or text == self.last_injected_text:
            return
            
        self.last_injected_text = text
        safe_text = json.dumps(text + "\\n")
        
        # This JavaScript safely finds the chat box and mimics a user pasting text into it
        js_code = f"""
        (function() {{
            let box = document.querySelector('rich-textarea div[contenteditable="true"]') || document.querySelector('textarea') || document.querySelector('div[contenteditable="true"]');
            if (box) {{
                box.focus();
                document.execCommand('insertText', false, {safe_text});
            }}
        }})();
        """
        
        current_widget = self.tabs.currentWidget()
        if isinstance(current_widget, QWebEngineView):
            current_widget.page().runJavaScript(js_code)
    # -----------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 34:
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
            # The magic trigger: Automatically pull from clipboard when overlay is summoned
            self.inject_clipboard_to_chat()

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
