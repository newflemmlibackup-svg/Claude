#!/bin/bash
# Baut eine eigenstaendige macOS-App (Klickpilot.app). Muss auf einem Mac mit
# installiertem Python 3 (inkl. Tkinter) ausgefuehrt werden - siehe README.md
# fuer Hinweise zur Python-Installation.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Pruefe Betriebssystem ==="
if [ "$(uname -s)" != "Darwin" ]; then
    echo "FEHLER: Klickpilot steuert Maus und Tastatur ueber macOS-Schnittstellen"
    echo "und laesst sich nur auf einem Mac bauen und benutzen."
    exit 1
fi

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

echo "=== Baue Klickpilot.app ==="
pyinstaller --noconfirm --windowed \
    --name "Klickpilot" \
    --osx-bundle-identifier "de.klickpilot.app" \
    --collect-all PIL \
    --collect-all numpy \
    --collect-all pynput \
    --collect-all objc \
    --collect-submodules Quartz \
    --collect-submodules ApplicationServices \
    run.py

echo "=== Ad-hoc signieren (reduziert Gatekeeper-Meldungen) ==="
codesign --force --deep --sign - "dist/Klickpilot.app" || true

echo
echo "=== Fertig ==="
echo "Die fertige App liegt unter: dist/Klickpilot.app"
echo
echo "WICHTIG - nach jedem Neubau:"
echo "  macOS merkt sich die Freigaben pro Programmsignatur. Ein frisch"
echo "  gebautes Klickpilot.app muss deshalb in den Systemeinstellungen unter"
echo "  'Datenschutz & Sicherheit' bei 'Bedienungshilfen' und"
echo "  'Bildschirmaufnahme' einmal neu freigegeben werden (alten Eintrag mit"
echo "  '-' entfernen, App neu starten, Nachfrage bestaetigen)."
