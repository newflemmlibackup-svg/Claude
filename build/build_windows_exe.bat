@echo off
REM Baut die eigenstaendige Windows-Anwendung (dist\DVT-Sidexis-Importer.exe).
REM Voraussetzung: Python 3.10+ von python.org ist installiert.
setlocal
cd /d "%~dp0\.."
if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
python build\build.py
endlocal
pause
