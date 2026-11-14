# DVT-Sidexis-Importer

Programm für die Zahnarztpraxis: liest DVT-Aufnahmen fremder Behandler
(DICOM, z. B. vom mitgebrachten USB-Stick oder einer CD), repariert sie und
schreibt sie so neu, dass sie sich in **Sidexis** importieren lassen.

Läuft unter **Windows** und **macOS**. (Sidexis selbst gibt es nur für Windows –
am Mac aufbereitete Aufnahmen werden einfach per Netzlaufwerk oder Stick zum
Sidexis-PC gebracht.)

## Bedienung

1. **Stick einstecken.** Das Programm erkennt neue USB-Sticks und CDs von
   selbst und analysiert sie sofort. Alternativ über *Anderen Ordner wählen …*
   einen beliebigen Ordner angeben.
2. **Prüfen und Patientendaten einstellen.** Die gefundenen Aufnahmen werden
   aufgelistet, samt Hinweisen (z. B. „3 fehlende Schichten werden schwarz
   ergänzt“). Rechts lassen sich Nachname, Vorname, Geburtsdatum, Geschlecht,
   Patienten-Nr., Aufnahmedatum und Bezeichnung ändern – am besten genau so,
   wie der Patient in Sidexis angelegt ist.
3. **Für Sidexis aufbereiten** klicken. Das Ergebnis landet in
   `Dokumente/DVT-Sidexis-Import/<Name>_<Datum>` (Speicherort änderbar).
4. In Sidexis den DICOM-Import aufrufen und diesen Ordner bzw. die darin
   liegende Datei `DICOMDIR` auswählen.

Der Original-Datenträger wird nur gelesen und nie verändert.

## Was das Programm repariert

Jede Schicht wird **komplett neu aufgebaut** – aus den Fremddaten werden nur
die Bildpunkte und wenige geprüfte Angaben übernommen. Das Ergebnis ist daher
immer gleich aufgebaut, egal von welchem Gerät die Aufnahme stammt:

| Problem in den Fremddaten | Was passiert |
|---|---|
| Einzelne Schichten fehlen | Lücke wird erkannt (über Position bzw. Bildnummer) und mit **schwarzen Schichten** gefüllt |
| Datei beschädigt / Bilddaten unlesbar | Schicht wird durch eine schwarze ersetzt |
| Datei abgeschnitten | Vorhandener Teil bleibt erhalten, der Rest wird schwarz |
| Komprimiert (JPEG, JPEG 2000, RLE) | Wird verlustfrei entpackt |
| Eine große Multiframe-Datei („Enhanced CT“) | Wird in klassische Einzelschichten zerlegt |
| Keine/defekte `DICOMDIR`, fehlende UIDs | Neue, stimmige Kennungen und gültige `DICOMDIR` |
| Falsche Modalität (z. B. `OT`) | Wird auf `CT` gesetzt |
| Schichten unsortiert, Dateinamen ohne Endung, verschachtelte Ordner | Wird unabhängig von Namen sortiert und einheitlich abgelegt |
| Ungleichmäßige Schichtabstände, doppelte Schichten | Exakt gleichmäßige Abstände, Duplikate entfernt |
| Herstellereigene Zusatzfelder, 8/12-Bit-Sonderformate | Einheitlich 16 Bit Graustufen, nur Standardfelder |

„Schwarz“ bedeutet: der dunkelste Wert der Aufnahme (Luft), damit die
Ersatzschichten in der 3D-Ansicht nicht als heller Balken erscheinen.

Nach dem Schreiben liest das Programm das Ergebnis zur Kontrolle noch einmal
ein und meldet, ob alles vollständig ist.

## Wichtige Hinweise

- **Bitte einmal mit echten Aufnahmen in Sidexis gegenprüfen.** Das Programm
  wurde mit vielen künstlich beschädigten Testdaten geprüft, konnte bei der
  Entwicklung aber nicht direkt gegen Sidexis getestet werden. Klappt der
  Import bei einem bestimmten Fremdgerät nicht, hilft die Option *Zusätzlich
  einfache .dcm-Einzeldateien schreiben* (zweiter Ordner ohne `DICOMDIR`).
- **Schwarze Ersatzschichten enthalten keine Bildinformation.** An diesen
  Stellen fehlt Diagnostik – das Programm zeigt die Anzahl deutlich an.
- **Voxelgröße:** Fehlt sie in den Fremddaten, warnt das Programm; Messungen
  sind dann nicht verlässlich.
- Fehlen Schichten ganz am Anfang oder Ende, kann das nicht erkannt werden.
- ZIP-Dateien auf dem Stick müssen vorher entpackt werden.
- Das Programm ersetzt keine fachliche Kontrolle der Bilder.

## Installation

### Fertige Programme

Bei jeder Änderung baut GitHub automatisch beide Versionen (Reiter **Actions**
→ letzter Lauf „DVT-Sidexis-Importer bauen“ → **Artifacts**):

- `DVT-Sidexis-Importer-Windows.zip` – enthält eine einzelne `.exe`, keine
  Installation nötig.
- `DVT-Sidexis-Importer-macOS.zip` – enthält die `.app` (für Macs mit
  Apple-Chip).

Beim ersten Start warnt das Betriebssystem, weil das Programm nicht
kostenpflichtig signiert ist:

- **Windows:** „Der Computer wurde durch Windows geschützt“ → *Weitere
  Informationen* → *Trotzdem ausführen*.
- **macOS:** App mit Rechtsklick → *Öffnen* starten; oder
  *Systemeinstellungen → Datenschutz & Sicherheit → Dennoch öffnen*.

### Selbst bauen

Mit installiertem Python 3.10+ (von python.org):

```bat
build\build_windows_exe.bat
```

```bash
./build/build_macos_app.sh
```

### Aus dem Quellcode starten

```bash
pip install -r requirements.txt
```

```bash
python -m dvt_importer
```

## Entwicklung

```bash
pip install -r requirements.txt pytest
```

```bash
python -m pytest tests
```

```bash
python -m dvt_importer --selftest
```

```
dvt_importer/
  scanner.py    Findet DICOM-Bilder und gruppiert sie zu Aufnahmen
  volume.py     Schichtreihenfolge, Geometrie, Lückenerkennung
  converter.py  Baut die Schichten neu auf, schreibt Medium + DICOMDIR, Abschlussprüfung
  drives.py     Erkennung von USB-Sticks/CDs (Windows, macOS, Linux)
  gui.py        Bedienoberfläche
  selftest.py   Selbsttest der fertig gebauten Anwendung
build/          Build-Skripte (PyInstaller)
tests/          Automatische Tests mit künstlich beschädigten DVT-Daten
```

---

Im Ordner `behandlungsplaner/` liegt ein davon unabhängiges zweites Werkzeug
(siehe dortige Beschreibung).
