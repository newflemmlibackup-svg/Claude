#!/bin/bash
# Baut die eigenständige macOS-App (dist/DVT-Sidexis-Importer.app).
# Voraussetzung: Python 3.10+ von python.org (bringt Tkinter mit).
set -euo pipefail
cd "$(dirname "$0")/.."
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "FEHLER: Dieses python3 hat kein Tkinter. Bitte Python von python.org installieren."
    exit 1
fi
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
python build/build.py
