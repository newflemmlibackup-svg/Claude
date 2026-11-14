"""Baut die eigenständige Anwendung für das aktuelle Betriebssystem.

    python build/build.py

Ergebnis:  dist/DVT-Sidexis-Importer.exe   (Windows)
           dist/DVT-Sidexis-Importer.app   (macOS)
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "DVT-Sidexis-Importer"

args = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", NAME,
    "--specpath", str(ROOT / "build" / "spec"),
    "--workpath", str(ROOT / "build" / "work"),
    "--distpath", str(ROOT / "dist"),
    # pydicom und die Decoder für komprimierte Bilder (JPEG, JPEG 2000) vollständig einpacken.
    "--collect-all", "pydicom",
    "--collect-all", "pylibjpeg",
    "--collect-all", "openjpeg",
    "--collect-all", "libjpeg",
    "--copy-metadata", "pylibjpeg",
    "--copy-metadata", "pylibjpeg-openjpeg",
    "--copy-metadata", "pylibjpeg-libjpeg",
]
if sys.platform != "darwin":
    args.append("--onefile")        # Windows: eine einzelne .exe
else:
    args += ["--osx-bundle-identifier", "de.praxis.dvt-sidexis-importer"]
args.append(str(ROOT / "run.py"))

os.chdir(ROOT)
subprocess.check_call(args)
if sys.platform == "darwin":
    # Ad-hoc-Signatur, damit macOS die App überhaupt startet.
    subprocess.call(["codesign", "--force", "--deep", "--sign", "-", f"dist/{NAME}.app"])
print(f"\nFertig: {ROOT / 'dist'}")
