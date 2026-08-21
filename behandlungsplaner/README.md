# Behandlungsplaner

Behandlungsplanungstool fuer die Zahnarztpraxis: OPG (Panorama-Roentgenbild)
importieren, Befunde/Massnahmen direkt auf dem Bild einzeichnen, automatisch
eine Planungsliste mit Kosten fuehren und als PDF exportieren.

## Funktionen

- **OPG-Import**: JPEG/PNG/TIFF/BMP sowie DICOM (Einzelbild, inkl. korrekter
  Fensterung/Normalisierung).
- **8 Befund-Symbole** per Drag&Drop aus der Palette auf das Bild ziehen:
  Implantat, Krone, Teilkrone, NICO/FDOK, Extraktion, Wurzelbehandlung,
  Fehlender Zahn, Bruecke (spannt zwei Zahnpositionen).
- **Frei skalier- und rotierbar**: jedes Symbol per Eckgriffpunkt beliebig in
  Breite/Hoehe anpassen, per Drehgriff rotieren (fuer geneigte Zaehne).
- **Optionales FDI-Kalibrierraster**: 32 verschiebbare Punkte (Zahn 11-48)
  entlang der beiden Kieferboegen. Einmal auf die tatsaechlichen Zahnpositionen
  im Bild ziehen - danach "snappen" neu platzierte Symbole automatisch auf den
  naechsten Zahn und werden anhand des Abstands zu den Nachbarzaehnen sinnvoll
  vorskaliert. Komplett **optional**: ohne Kalibrierung lassen sich Symbole
  weiterhin frei platzieren und per Rechtsklick-Menue manuell einem
  FDI-Zahn zuordnen.
- **Bruecken-Symbol**: zwei Ankerpunkte, die sich (bei aktiver Kalibrierung)
  ebenfalls an Zahnpositionen einklinken; die ueberspannten Zaehne (Pfeiler +
  Zwischenglieder) werden automatisch ermittelt.
- **Status je Position**: geplant/durchgefuehrt mit Datum (fuer die
  Verlaufskontrolle ueber mehrere Termine).
- **Planungsliste** unterhalb des Bildes: Typ, Zahn, Status, Datum, Notiz,
  Kosten je Position, plus Summen (offen/durchgefuehrt/gesamt).
- **Preisliste**: Standardkosten je Befundart hinterlegbar, pro Position frei
  ueberschreibbar.
- **PDF-Export**: annotiertes OPG, Legende, vollstaendige Kostentabelle mit
  Summen, Patienten-/Praxiskopf - fuer die Patientenaufklaerung oder Akte.
- **Mehrere Plaene pro Patient**: "Folgeplan" dupliziert Bild + Positionen
  eines bestehenden Plans fuer den naechsten Termin.
- **Undo/Redo**, Autosave (alle 60s bei ungespeicherten Aenderungen),
  Speichern-Abfrage beim Schliessen.
- Zoom/Pan des OPG (Mausrad = Zoom, rechte Maustaste = verschieben).

## Kalibrierung - kurz erklaert

Eine automatische Zahnerkennung per Bildanalyse (KI) ist ohne trainiertes
medizinisches Modell nicht zuverlaessig moeglich und wuerde ein Risiko fuer
Fehlzuordnungen bergen. Stattdessen bietet das Tool ein **manuell
kalibrierbares Raster**: Ansicht > "FDI-Kalibrierraster" aktivieren, die 32
vorplatzierten Punkte auf die echten Zahnpositionen im eigenen OPG ziehen
(einmalig pro Bild). Ab dann orientieren sich neu gezogene Symbole automatisch
an Position und Groesse des jeweiligen Zahns. Die Kalibrierung bleibt rein
geometrisch (keine Diagnose) und ist jederzeit korrigierbar.

## Datenablage

Jeder Plan liegt als eigener Ordner im "Praxis-Datenordner"
(einstellbar unter Einstellungen, Standard: `~/Behandlungsplaene`):

```
Behandlungsplaene/
  Mustermann_Erika_2026-08-21/
    opg.png
    plan.json
```

Damit ist ein Plan vollstaendig eigenstaendig (Bild + Planung) und laesst sich
einfach kopieren/sichern.

## Installation aus dem Quellcode

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m behandlungsplaner
```

## Eigenstaendige macOS-App bauen

Auf einem Mac mit installiertem Python 3 (empfohlen: der offizielle Installer
von [python.org](https://www.python.org/downloads/macos/), der Tkinter schon
mitbringt; bei Homebrew-Python zusaetzlich `brew install python-tk`):

```bash
chmod +x build/build_macos_app.sh   # nur beim allerersten Mal noetig
./build/build_macos_app.sh
```

Die fertige App liegt danach unter `dist/Behandlungsplaner.app`.

**Gatekeeper-Hinweis:** Da die App nicht mit einem kostenpflichtigen
Apple-Entwicklerzertifikat signiert ist, meldet macOS beim ersten Start auf
einem anderen Mac vermutlich *"kann nicht geoeffnet werden, da der Entwickler
nicht verifiziert werden kann"*. Einmalig genuegt: App mit **Rechtsklick >
Oeffnen** starten und im Dialog erneut **Oeffnen** bestaetigen (alternativ:
**Systemeinstellungen > Datenschutz & Sicherheit** > "Trotzdem oeffnen").

PyInstaller baut nur fuer die Architektur (Apple Silicon/M-Chip vs. Intel),
auf der es ausgefuehrt wird. Fuer beide Architekturen: Build-Schritt auf je
einem Intel- und einem Apple-Silicon-Mac ausfuehren.

## Eigenstaendige Windows-.exe bauen

```bat
build\build_windows_exe.bat
```

## Entwicklung / Tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests/
```

Die Test-Suite deckt Datenmodell, FDI-Logik, Symbol-Geometrie, Bildimport
(inkl. synthetischem DICOM), PDF-Export sowie die komplette
Canvas-Interaktion (Verschieben, rotationskorrektes Skalieren, Rotieren,
Kalibrier-Snapping, Bruecken-Ankerpunkte) und einen kompletten
End-to-End-Durchlauf der Anwendung ab (Plan anlegen, alle 8 Symboltypen
platzieren, Undo/Redo, Speichern, PDF-Export, Folgeplan) - letztere unter
Xvfb (virtuelles Display).

## Aufbau des Projekts

```
behandlungsplaner/
  fdi.py             FDI-Zahnschema, Bogen-Reihenfolge, Default-Kalibrierraster
  models.py          PlanItem/TreatmentPlan, Befundarten, Preisliste
  shapes.py          Symbol-Geometrie (Canvas UND PDF-Export nutzen dieselbe)
  storage.py         Plan-Ordner anlegen/laden/speichern, Bildimport inkl. DICOM
  render.py          PIL-Rendering (Bild + Symbole + Legende)
  pdf_export.py      PDF-Erstellung (reportlab)
  canvas_view.py      Interaktive Canvas (Zoom/Pan, Drag&Drop, Handles, Kalibrierung)
  palette.py          Symbol-Palette (Drag-Quelle)
  plan_list_view.py   Planungsliste (Kosten/Status-Tabelle)
  start_screen.py      Planuebersicht
  app.py              Verdrahtung, Menue, Undo/Redo, Autosave
  config.py            Einstellungen (Praxis-Datenordner, Praxisname)
run.py                 Einstiegspunkt fuer PyInstaller-Builds
tests/                 Automatisierte Tests (pytest)
build/                 Skripte fuer macOS-.app / Windows-.exe
```

## Wichtige Hinweise

- **Keine automatische Bildanalyse**: Zahnpositionen basieren auf manueller
  bzw. kalibrierter Einzeichnung durch das Praxisteam, nicht auf einer
  KI-Bilderkennung. Die Kalibrierung ersetzt keine radiologische Befundung.
- **Kosten sind Beispielwerte**: Die mitgelieferte Preisliste dient nur als
  Ausgangspunkt und ist keine verbindliche GOZ-/BEMA-Abrechnungsgrundlage.
  Das exportierte PDF ist kein amtlicher Heil- und Kostenplan.
- Vor klinischer/administrativer Nutzung Bild- und Kostendaten immer pruefen.
