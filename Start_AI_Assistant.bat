@echo off
title AI Assistant Launcher

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo ===================================================
    echo ERROR: Python is not installed on this computer!
    echo ===================================================
    echo Please download it from: https://www.python.org/downloads/
    echo.
    echo VERY IMPORTANT: When installing, you MUST check the box
    echo that says "Add Python to PATH" at the bottom of the installer.
    echo.
    pause
    exit /b
)

:: Install dependencies silently
echo Checking and installing required libraries (this takes a few seconds)...
pip install PyQt6 google-generativeai pillow keyboard uiautomation SpeechRecognition pyaudio --quiet

:: Boot the Native app using pythonw (no black terminal window)
start "" pythonw native_assistant.py

