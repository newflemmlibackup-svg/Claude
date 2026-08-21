@echo off
REM Baut eine eigenstaendige Windows-.exe des Behandlungsplaners.
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

echo === Baue Behandlungsplaner.exe ===
pyinstaller --noconfirm --onefile --windowed ^
    --name "Behandlungsplaner" ^
    --collect-all pydicom ^
    --collect-all reportlab ^
    --collect-all PIL ^
    run.py

echo.
echo === Fertig ===
echo Die fertige Datei liegt unter: dist\Behandlungsplaner.exe
endlocal
