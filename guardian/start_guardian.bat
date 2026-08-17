@echo off
REM Guardian launcher — starts the WATCHER (no console window). The watcher
REM detects the Insta360 camera and manages Guardian's lifecycle, so the camera
REM is never held across a replug. Auto-runs at login (copied to Startup folder)
REM and can be double-clicked to start manually.
start "" "C:\Users\Celluloid Solutions\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe" "C:\Users\Celluloid Solutions\Desktop\idea72\guardian\watcher.py"
