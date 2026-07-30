@echo off
REM Spawns the Scribe panel detached, no console window.
cd /d "%~dp0"
start "" pythonw "%~dp0scribe_window.py" %*
