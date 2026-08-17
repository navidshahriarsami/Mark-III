@echo off
REM Guardian launcher — runs the camera monitor with no console window.
REM Used by the "Guardian" scheduled task (auto-start at login) and can be
REM double-clicked to start manually.
start "" "C:\Users\Celluloid Solutions\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe" "C:\Users\Celluloid Solutions\Desktop\idea72\guardian\guardian.py"
