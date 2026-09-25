import sys
import os
import traceback
import json
import threading
import ctypes
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- BYPASS GOOGLE SECURE BROWSER CHECK ---
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-blink-features=AutomationControlled"

from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel, QTabWidget, QDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import Qt, QUrl, QPoint, pyqtSignal
from PyQt6.QtGui import QColor

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("Warning: keyboard module not found. Global hotkeys disabled.")

try:
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(0.5) 
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False
    print("Warning: uiautomation module not found. Desktop text reading disabled.")

try:
    import speech_recognition as sr
    SPEECH_AVAILABLE = True
except ImportError:
    SPEECH_AVAILABLE = False
    print("Warning: SpeechRecognition module not found. Voice dictation disabled.")

overlay_instance = None


# --- LOCAL SERVER FOR CHROME EXTENSION ---
class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/inject':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            try:
                data = json.loads(post_data)
                text = data.get('text', '')
            except:
                text = post_data
            
            if text and overlay_instance:
                overlay_instance.external_inject_signal.emit(text)
            
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b"Success")
            
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        
    def log_message(self, format, *args):
        pass

def start_server():
    server = HTTPServer(('localhost', 65432), RequestHandler)
    server.serve_forever()
# -----------------------------------------


# --- SAFETY CONFIRMATION DIALOG (For 2-Way Automation) ---
class SafetyConfirmDialog(QDialog):
    def __init__(self, action_text, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: #7f1d1d; color: white; border: 2px solid #ef4444; border-radius: 8px;")
        
        # Position slightly offset from the main window
        if parent:
            self.setGeometry(parent.x() + 50, parent.y() + 50, 400, 120)
        else:
            self.setGeometry(100, 100, 400, 120)
        
        layout = QVBoxLayout(self)
        
        lbl_title = QLabel("⚠️ HUMAN APPROVAL REQUIRED")
        lbl_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #fca5a5;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        lbl_action = QLabel(f"Target Action: {action_text}")
        lbl_action.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_action.setWordWrap(True)
        lbl_action.setStyleSheet("font-size: 12px; margin: 10px 0;")
        layout.addWidget(lbl_action)
        
        lbl_inst = QLabel("Press ENTER to Allow   |   Press ESC to Block")
        lbl_inst.setStyleSheet("font-size: 11px; color: #fecaca; font-weight: bold;")
        lbl_inst.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_inst)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
# ---------------------------------------------------------


class AssistantOverlay(QMainWindow):
    toggle_signal = pyqtSignal()
    ghost_signal = pyqtSignal()
    external_inject_signal = pyqtSignal(str)
    desktop_grab_signal = pyqtSignal() 
    dictation_signal = pyqtSignal()
    reset_title_signal = pyqtSignal() 
    test_safety_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        global overlay_instance
        overlay_instance = self
        
        self.oldPos = None
        self.is_ghost_mode = False
        self.is_listening = False 
        
        self.toggle_signal.connect(self.toggle_visibility)
        self.ghost_signal.connect(self.toggle_ghost_mode)
        self.external_inject_signal.connect(self.inject_external_text)
        self.desktop_grab_signal.connect(self.grab_desktop_text)
        self.dictation_signal.connect(self.start_dictation)
        self.reset_title_signal.connect(self.reset_title)
        self.test_safety_signal.connect(self.trigger_safety_test)

        self.initUI()
        self.setup_hotkeys()
        
        self.server_thread = threading.Thread(target=start_server, daemon=True)
        self.server_thread.start()

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
        
        self.title_label = QLabel("AI Assistant")
        self.title_label.setStyleSheet("color: #cbd5e1; font-family: sans-serif; font-size: 13px; font-weight: bold;")
        title_layout.addWidget(self.title_label)

        self.new_tab_btn = QPushButton("+ New Tab")
        self.new_tab_btn.setStyleSheet("""
            QPushButton { border: none; font-weight: bold; color: white; background-color: #3b82f6; padding: 4px 10px; border-radius: 4px; margin-left: 10px; }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.new_tab_btn.clicked.connect(lambda: self.add_new_tab(QUrl("https://www.google.com/"), "Google Search"))
        title_layout.addWidget(self.new_tab_btn)

        title_layout.addStretch()

        self.ghost_btn = QPushButton("👻")
        self.ghost_btn.setToolTip("Toggle Ghost Mode (Ctrl+G)")
        self.ghost_btn.setFixedSize(30, 30)
        self.ghost_btn.setStyleSheet("QPushButton { border: none; font-size: 16px; } QPushButton:hover { background-color: #334155; }")
        self.ghost_btn.clicked.connect(self.toggle_ghost_mode)
        title_layout.addWidget(self.ghost_btn)

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
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        storage_path = os.path.join(base_dir, "web_data")
        self.profile.setCachePath(storage_path)
        self.profile.setPersistentStoragePath(storage_path)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        
        # MAC SAFARI SPOOF: Google's security checks are highly optimized to catch fake Chrome/Windows 
        # User-Agents on QtWebEngine. Spoofing Mac Safari often completely bypasses the Chromium fingerprinting.
        self.profile.setHttpUserAgent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15")
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.ForceDarkMode, True)

        # JS INJECTION: Google checks for 'navigator.webdriver' to detect automated embedded browsers.
        # We inject a script before the page even loads to delete these flags from the Javascript environment.
        from PyQt6.QtWebEngineCore import QWebEngineScript
        anti_bot_script = QWebEngineScript()
        anti_bot_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        anti_bot_script.setSourceCode("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        anti_bot_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self.profile.scripts().insert(anti_bot_script)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #1e293b; color: #94a3b8; padding: 8px 16px; border-right: 1px solid #0f172a; }
            QTabBar::tab:selected { background: #0f172a; color: #f8fafc; font-weight: bold; border-top: 2px solid #3b82f6; }
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

    def start_dictation(self):
        if not SPEECH_AVAILABLE:
            print("Speech modules missing. Run: pip install SpeechRecognition pyaudio")
            return
            
        if self.is_listening:
            return
        self.is_listening = True
        
        self.title_label.setText("AI Assistant 🔴 (Listening...)")
        self.title_label.setStyleSheet("color: #ef4444; font-family: sans-serif; font-size: 13px; font-weight: bold;")
        
        threading.Thread(target=self._process_dictation, daemon=True).start()

    def _process_dictation(self):
        try:
            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=15)
                
            text = recognizer.recognize_google(audio)
            if text:
                self.external_inject_signal.emit(text)
                
        except sr.WaitTimeoutError:
            print("Voice dictation timed out.")
        except sr.UnknownValueError:
            print("Voice dictation could not understand the audio.")
        except AttributeError:
            print("Microphone block: The audio stream failed to open properly.")
        except Exception as e:
            print(f"Voice dictation error: {e}")
        finally:
            self.is_listening = False
            self.reset_title_signal.emit()

    def reset_title(self):
        self.title_label.setText("AI Assistant")
        self.title_label.setStyleSheet("color: #cbd5e1; font-family: sans-serif; font-size: 13px; font-weight: bold;")

    def toggle_ghost_mode(self):
        if not self.is_ghost_mode:
            self.setWindowOpacity(0.5) 
            self.is_ghost_mode = True
            self.ghost_btn.setStyleSheet("QPushButton { border: none; font-size: 16px; background-color: #3b82f6; border-radius: 15px;} ")
        else:
            self.setWindowOpacity(1.0) 
            self.is_ghost_mode = False
            self.ghost_btn.setStyleSheet("QPushButton { border: none; font-size: 16px; } QPushButton:hover { background-color: #334155; }")

    def toggle_visibility(self):
        if self.isVisible() and self.isActiveWindow() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()
            self.raise_()

    def inject_external_text(self, text):
        if not self.isVisible() or self.isMinimized() or not self.isActiveWindow():
            self.showNormal()
            self.activateWindow()
            self.raise_()

        safe_text = json.dumps(text + "\\n")
        
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

    def get_active_window_title(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value.lower()
        except:
            return ""

    def grab_desktop_text(self):
        window_title = self.get_active_window_title()

        # TASK 1: PRIVACY DENY-LIST
        deny_list = ["1password", "bitwarden", "keepass", "lastpass", "dashlane", "bank", "vault"]
        if any(bad_word in window_title for bad_word in deny_list):
            print(f"PRIVACY SHIELD: Blocked text extraction from secure app ({window_title})")
            self.title_label.setText(f"⚠️ Blocked (Privacy Shield): {window_title[:15]}...")
            self.title_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
            threading.Timer(3.0, lambda: self.reset_title_signal.emit()).start()
            return

        extracted_text = ""

        # STRATEGY 1: Try UIA First (Silent, preserves clipboard)
        if UIA_AVAILABLE:
            try:
                control = auto.GetFocusedControl()
                if control:
                    text_pattern = control.GetTextPattern()
                    if text_pattern:
                        selections = text_pattern.GetSelection()
                        if selections and len(selections) > 0:
                            extracted_text = selections[0].GetText(-1)
            except Exception as e:
                print(f"UIA native text read failed: {e}")

        # STRATEGY 2: Fallback to simulated Copy for Electron Apps (VS Code)
        if not extracted_text and KEYBOARD_AVAILABLE:
            print("Falling back to simulated copy for non-native UI...")
            try:
                cb = QApplication.clipboard()
                
                # FIX: We must release the keys the user is currently holding (Ctrl+Shift+D), 
                # otherwise Windows registers 'Ctrl+Shift+C' instead of 'Ctrl+C'
                keyboard.release('ctrl')
                keyboard.release('shift')
                keyboard.release('d')
                
                import time
                time.sleep(0.05) # Brief pause for OS to register key release
                
                # Simulate Ctrl+C to push highlighted text to clipboard
                keyboard.send('ctrl+c')
                
                # Give Windows OS a fraction of a second to update the clipboard
                time.sleep(0.15)
                
                new_text = cb.text()
                if new_text:
                    extracted_text = new_text
            except Exception as e:
                print(f"Clipboard fallback failed: {e}")

        # ROUTING & INJECTION
        if extracted_text:
            # TASK 2: APP-AWARE ROUTING
            routed_text = extracted_text
            if "code" in window_title or "pycharm" in window_title or "intellij" in window_title:
                routed_text = f"I am currently coding in my IDE. Please review or explain this snippet:\\n\\n{extracted_text}"
            elif "outlook" in window_title or "mail" in window_title or "gmail" in window_title:
                routed_text = f"Please draft a professional response to this email:\\n\\n{extracted_text}"
            elif "word" in window_title or "notepad" in window_title:
                routed_text = f"Please review, format, or continue this text:\\n\\n{extracted_text}"

            self.inject_external_text(routed_text)
        else:
            print("No text could be extracted.")

    # TASK 3: HUMAN-IN-THE-LOOP FRAMEWORK (For Future 2-Way Automation)
    def trigger_safety_test(self):
        dialog = SafetyConfirmDialog("Type generated AI code into active window", self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.title_label.setText("Action Approved! (2-way execution would happen here)")
            self.title_label.setStyleSheet("color: #4ade80; font-weight: bold;")
        else:
            self.title_label.setText("Action Blocked by Human!")
            self.title_label.setStyleSheet("color: #ef4444; font-weight: bold;")
        
        threading.Timer(3.0, lambda: self.reset_title_signal.emit()).start()

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
                keyboard.add_hotkey('ctrl+space', lambda: self.toggle_signal.emit())
                keyboard.add_hotkey('ctrl+g', lambda: self.ghost_signal.emit())
                keyboard.add_hotkey('ctrl+shift+d', lambda: self.desktop_grab_signal.emit())
                keyboard.add_hotkey('ctrl+shift+v', lambda: self.dictation_signal.emit())
                
                # New hotkey specifically for testing the safety framework before we build 2-way automation
                keyboard.add_hotkey('ctrl+shift+h', lambda: self.test_safety_signal.emit())
            except Exception as e:
                print(f"Failed to bind hotkeys: {e}")

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
