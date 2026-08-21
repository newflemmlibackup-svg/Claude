@echo off
REM Baut eine eigenstaendige Windows-.exe des DVT-Sidexis-Importers.
REM Muss auf einem Windows-Rechner mit installiertem Python (python.org,
REM Standardinstallation inkl. Tkinter) ausgefuehrt werden.

setlocal
cd /d "%~dp0\.."

echo === Erstelle/aktualisiere virtuelle Umgebung ===
if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo === Installiere Abhaengigkeiten ===
pip install --upgrade pip
pip install -r requirements.txt

echo === Baue DVT-Sidexis-Importer.exe ===
pyinstaller --noconfirm --onefile --windowed ^
    --name "DVT-Sidexis-Importer" ^
    --collect-all pydicom ^
    --collect-all pylibjpeg ^
    run.py

echo.
echo === Fertig ===
echo Die fertige Datei liegt unter: dist\DVT-Sidexis-Importer.exe
endlocal
