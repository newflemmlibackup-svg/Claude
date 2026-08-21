#!/bin/bash
# Baut eine eigenstaendige macOS-App (Behandlungsplaner.app). Muss auf einem
# Mac mit installiertem Python 3 (inkl. Tkinter) ausgefuehrt werden - siehe
# README.md fuer Hinweise zur Python-Installation.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Pruefe Tkinter ==="
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "FEHLER: Das python3 in deinem PATH hat kein Tkinter."
    echo "Bitte Python von https://www.python.org/downloads/macos/ installieren"
    echo "(bringt Tkinter mit) oder bei Homebrew zusaetzlich 'brew install python-tk' ausfuehren."
    exit 1
fi

echo "=== Erstelle/aktualisiere virtuelle Umgebung ==="
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "=== Installiere Abhaengigkeiten ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Baue Behandlungsplaner.app ==="
pyinstaller --noconfirm --windowed \
    --name "Behandlungsplaner" \
    --collect-all pydicom \
    --collect-all reportlab \
    --collect-all PIL \
    run.py

echo "=== Ad-hoc signieren (reduziert Gatekeeper-Meldungen) ==="
codesign --force --deep --sign - "dist/Behandlungsplaner.app" || true

echo
echo "=== Fertig ==="
echo "Die fertige App liegt unter: dist/Behandlungsplaner.app"
echo "Hinweis: Beim ersten Start auf einem anderen Mac ggf. mit Rechtsklick > "
echo "'Oeffnen' bestaetigen (siehe README.md, Abschnitt macOS/Gatekeeper)."
