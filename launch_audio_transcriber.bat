@echo off
set "APP_DIR=%~dp0"
set "PYTHON=%APP_DIR%..\work\audio_transcriber_venv\Scripts\pythonw.exe"
start "" "%PYTHON%" "%APP_DIR%app.py"
