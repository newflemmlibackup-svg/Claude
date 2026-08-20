# DVT-Sidexis-Importer

Kleines Werkzeug mit grafischer Oberflaeche fuer die Zahnarztpraxis: liest
DVT-/DICOM-Datensaetze von fremden Behandlern (z. B. von einem mitgebrachten
USB-Stick) ein, repariert die haeufigsten Kompatibilitaetsprobleme und
schreibt einen neuen Ordner, der sich in **Sidexis** ueber
`Datei > Import > DICOM` importieren laesst.

## Warum lassen sich manche fremden DVTs nicht in Sidexis importieren?

Viele DVT-/CBCT-Geraete exportieren zwar "DICOM"-Dateien, aber Sidexis'
Import basiert auf einer **DICOMDIR**-Datei (dem Standard-Inhaltsverzeichnis
eines DICOM-Datentraegers). Typische Ursachen fuer einen fehlgeschlagenen
Import sind:

- **Keine (gueltige) DICOMDIR** vorhanden – manche Geraete-Software exportiert
  nur die einzelnen Bilddateien ohne Inhaltsverzeichnis.
- **Fehlende oder inkonsistente UIDs** (Study-/Series-/SOP-Instance-UID), so
  dass Sidexis die Bilder keiner Studie/Serie zuordnen kann.
- **Komprimierte Bilddaten** (z. B. JPEG2000), deren Transfersyntax vom
  Sidexis-DICOM-Codec nicht unterstuetzt wird.
- **Unpassendes oder fehlendes `Modality`-Tag** – ein DVT-Volumen muss als
  `CT` gekennzeichnet sein, damit Sidexis es als 3D-Datensatz erkennt.
- **Nicht-konforme Datei-/Ordnerstruktur** (z. B. Dateien ohne Endung,
  beliebige Verschachtelung), auf die sich der automatische Import ohne
  DICOMDIR nicht verlassen kann.

Dieses Tool liest alle Dateien im gewaehlten Quellordner unabhaengig von
Dateiname/-endung ein, erkennt zusammengehoerige Bildserien, behebt die oben
genannten Punkte und baut mit `pydicom` ein neues, DICOM-konformes Fileset
inklusive gueltiger DICOMDIR neu auf.

## Voraussetzungen

- Windows-PC (da Sidexis dort laeuft) – das Tool selbst ist plattformunabhaengig.
- Entweder die fertige `DVT-Sidexis-Importer.exe` (siehe `build/`) **oder**
  Python 3.10+ mit den Paketen aus `requirements.txt`.

## Bedienung

1. **Fremden USB-Stick auswaehlen**: Ordner/Laufwerk mit dem DVT-Export des
   Fremdbehandlers auswaehlen und auf **"Scannen"** klicken.
2. Das Tool zeigt alle gefundenen Serien mit Patient, Modalitaet, Anzahl
   Bilder und erkannten Problemen ("Hinweise") an. Serien an-/abwaehlen
   (Standard: alle ausgewaehlt).
3. **Zielordner waehlen** (leerer, neuer Ordner empfohlen).
4. Auf **"Konvertieren"** klicken. Der Fortschritt und ein Protokoll werden
   angezeigt.
5. Nach Abschluss: den Zielordner in Sidexis ueber
   **Datei > Import > DICOM** auswaehlen (bzw. die darin liegende
   `DICOMDIR`-Datei).

> **Wichtig:** Der Original-USB-Stick des Fremdbehandlers wird nur gelesen,
> nie veraendert. Bitte das Konvertierungsergebnis vor der klinischen
> Verwendung stichprobenartig mit dem Original vergleichen (z. B. Anzahl
> Schichten, Patientendaten) – das Tool arbeitet mit Heuristiken, um auch mit
> unvollstaendigen Fremd-Daten zurechtzukommen.

## Installation aus dem Quellcode

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
python -m dvt_importer
```

## Eigenstaendige Windows-.exe bauen

Auf einem Windows-Rechner mit installiertem Python:

```bat
build\build_windows_exe.bat
```

Die fertige Datei liegt danach unter `dist\DVT-Sidexis-Importer.exe` und kann
ohne weitere Installation auf anderen Praxis-PCs verteilt werden.

## Entwicklung / Tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests/
```

Die Tests erzeugen synthetische, absichtlich "kaputte" Beispiel-DVT-Daten
(fehlende UIDs, falsches Modality-Tag, keine DICOMDIR, keine Dateiendungen)
und pruefen den kompletten Ablauf von `scan_source()` bis zum fertigen,
wieder einlesbaren DICOM-Fileset.

## Aufbau des Projekts

```
dvt_importer/
  scanner.py     Durchsucht den Quellordner und gruppiert Dateien zu Serien
  converter.py   Normalisiert die Daten und schreibt DICOMDIR + Bilddateien
  gui.py         Tkinter-Bedienoberflaeche
  __main__.py    Einstiegspunkt (`python -m dvt_importer`)
tests/           Automatisierte Tests (pytest)
build/           Skript zum Bauen einer Windows-.exe
```

## Grenzen

- Fehlen in den Quelldaten sowohl Study- als auch Series-UID, wird anhand der
  Ordnerstruktur gruppiert (ein Ordner = eine Serie). Bei ungewoehnlichen
  Exporten (mehrere Serien in einem Ordner ohne UIDs) kann das zu falscher
  Gruppierung fuehren – in diesem Fall bitte die Ordner vor dem Scannen manuell
  trennen.
- Fuer komprimierte Bilddaten (JPEG/JPEG2000) werden die Pakete
  `pylibjpeg`/`pylibjpeg-openjpeg` benoetigt. Fehlt die Dekodierung, wird dies
  im Protokoll als Warnung ausgegeben und die betroffene Serie im
  Originalzustand uebernommen (kann dann ggf. weiterhin nicht importierbar
  sein).
- Das Tool ersetzt keine Pruefung durch Fachpersonal: Bild- und Patientendaten
  vor klinischer Nutzung immer verifizieren.
