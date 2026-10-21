@echo off
title Aura AI Assistant Launcher

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

:: Kill any stuck previous background pythonw instances so mic and ports are freed
taskkill /F /IM pythonw.exe >nul 2>&1

:: Quick check if dependencies are already installed (avoids 10-second pip lag on every launch)
python -c "import PyQt6, google.genai, PIL, keyboard, speech_recognition, pyaudiowpatch" >nul 2>&1
if %errorlevel% neq 0 (
    echo First-time setup: Installing required audio and AI libraries...
    pip install PyQt6 google-genai pillow keyboard speechrecognition pyaudiowpatch --quiet
)

:: Boot the Assistant smoothly using pythonw (no black console window)
start "" pythonw native_assistant.py
exit /b
