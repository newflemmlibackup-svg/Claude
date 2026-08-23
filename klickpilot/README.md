# Klickpilot

Ein Werkzeug fuer macOS, das wiederkehrende Klickstrecken uebernimmt - auch
bei Programmen, die keinerlei Schnittstelle anbieten. Klickpilot bedient sie
so, wie ein Mensch es tut: es schaut auf den Bildschirm, erkennt die
Bedienelemente wieder und klickt sie an.

## Die Grundidee

1. Auf **"+ Neuer Button"** klicken und einen Namen vergeben.
2. Nach einem kurzen Countdown wird **mitgeschnitten**, was Sie tun: Klicks,
   Doppelklicks, Rechtsklicks, Ziehen, Scrollen und Tastatureingaben.
3. Mit **F9** beenden - fertig ist der Button.
4. Ein Klick auf den Button spielt den ganzen Ablauf jederzeit wieder ab.

Der entscheidende Punkt: Klickpilot merkt sich **nicht** die Mauskoordinate,
sondern **wie die Stelle aussah**. Beim Abspielen wird dieser Bildausschnitt
auf dem aktuellen Bildschirm gesucht. Poppt der Dialog heute weiter rechts
auf, ist das Fenster verschoben, groesser oder auf dem zweiten Monitor -
der Knopf wird trotzdem gefunden und getroffen.

## Wie die Wiedererkennung arbeitet

Zu jedem Klick werden beim Aufnehmen zwei Bildausschnitte gesichert:

* eine enge **Schablone** rund um den Klickpunkt (das Bedienelement selbst),
* ein grosser **Umgebungsausschnitt** (die Nachbarschaft).

Beim Abspielen wird die Schablone per **normierter Kreuzkorrelation** (ZNCC)
auf dem Bildschirm gesucht. Dieses Verfahren vergleicht Muster, nicht
absolute Helligkeiten - ein anderes Farbschema, ein hellerer Monitor oder
eine leicht andere Fensterfarbe stoeren also nicht. Gesucht wird zweistufig:
zuerst grob auf einem verkleinerten Bildschirmfoto, danach fein in voller
Aufloesung rund um die besten Kandidaten. Eine Suche ueber einen kompletten
Retina-Bildschirm dauert damit rund eine viertel Sekunde.

Zusaetzlich werden mehrere Groessenstufen geprueft (0,84 bis 1,18), damit
auch eine veraenderte Zoomstufe oder ein Monitor mit anderer Aufloesung noch
passt.

Der Umgebungsausschnitt entscheidet dort, wo die Schablone allein nicht
reicht: Sehen zehn "Loeschen"-Knoepfe in einer Liste voellig gleich aus,
verraet erst die Nachbarschaft (die Beschriftung links daneben), welcher
gemeint war.

Findet Klickpilot ein Element nicht sofort, **wartet** es (voreingestellt 8
Sekunden) - so laufen Ablaeufe auch dann durch, wenn ein Programm einmal
laenger braucht, bis der Dialog erscheint.

## Voraussetzungen

* macOS (Aufnahme und Wiedergabe nutzen die macOS-Schnittstellen Quartz).
* Die fertige `Klickpilot.app` (siehe unten) **oder** Python 3.10+ mit den
  Paketen aus `requirements.txt`.

### Freigaben in den Systemeinstellungen

macOS laesst kein Programm ungefragt Maus und Bildschirm uebernehmen. Unter
**Systemeinstellungen > Datenschutz & Sicherheit** muessen deshalb zwei
Haken gesetzt werden:

| Bereich | wofuer |
| --- | --- |
| **Bedienungshilfen** | Eingaben mitlesen und Maus/Tastatur steuern |
| **Bildschirmaufnahme** | Bedienelemente auf dem Bildschirm wiedererkennen |

Klickpilot fragt beim ersten Start selbst danach und bietet an, die passende
Seite zu oeffnen. Nach dem Erteilen muss das Programm **einmal neu gestartet**
werden. Wird Klickpilot aus dem Terminal gestartet, vergibt macOS die Rechte
an das Terminal, nicht an Klickpilot.

## Installation aus dem Quellcode

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m klickpilot
```

## Eigenstaendige macOS-App bauen

```bash
chmod +x build/build_macos_app.sh   # nur beim allerersten Mal noetig
./build/build_macos_app.sh
```

Die fertige App liegt danach unter `dist/Klickpilot.app`.

**Gatekeeper-Hinweis:** Da die App nicht mit einem kostenpflichtigen
Apple-Entwicklerzertifikat signiert ist, meldet macOS beim ersten Start auf
einem anderen Mac vermutlich *"kann nicht geoeffnet werden, da der
Entwickler nicht verifiziert werden kann"*. Einmalig genuegt: App mit
**Rechtsklick > Oeffnen** starten und im Dialog erneut **Oeffnen**
bestaetigen.

**Nach jedem Neubau** aendert sich die Programmsignatur; die Freigaben fuer
Bedienungshilfen und Bildschirmaufnahme muessen dann einmal neu erteilt
werden (alten Eintrag mit "-" entfernen, App neu starten).

## Bedienung im Einzelnen

### Aufnehmen

Waehrend der Aufnahme blendet sich das Hauptfenster aus; nur ein kleines
Aufnahmefenster bleibt sichtbar und zeigt mit, was erkannt wurde. Klicks auf
dieses Fenster werden **nicht** mitgeschnitten.

* **Fertig (F9)** beendet die Aufnahme und speichert.
* **Verwerfen** bricht ab, ohne etwas zu speichern.

Zwei kurz aufeinanderfolgende Klicks an derselben Stelle werden automatisch
als Doppelklick erkannt, gehaltenes Ziehen als Ziehbewegung, getippte
Zeichen zu einem Texteingabe-Schritt zusammengefasst. Kurzbefehle wie
`Cmd+C` bleiben als Tastenkombination erhalten (und landen nicht im Text).

Aufgenommene Denkpausen werden uebernommen, aber auf 3 Sekunden gedeckelt -
so laeuft die Wiedergabe zuegig, ohne aus dem Takt zu geraten.

### Abspielen

Ein Klick auf den Button genuegt. Waehrend der Wiedergabe:

* **F10** oder der **Stopp**-Knopf halten den Ablauf sofort an
  (Notbremse, funktioniert auch, wenn Klickpilot im Hintergrund ist).
* Wird ein Element nicht gefunden, haelt der Ablauf an und meldet, an
  welchem Schritt es lag und wie hoch die erreichte Aehnlichkeit war.

Jedem Button laesst sich ein **globales Tastenkuerzel** zuweisen
(z. B. `cmd+shift+1`), mit dem er aus jedem Programm heraus startet.

### Schritte nachbearbeiten

Rechtsklick auf einen Button > **Bearbeiten** zeigt alle Schritte mit dem
jeweils gespeicherten Bildausschnitt und dem eingezeichneten Klickpunkt.
Dort laesst sich einstellen:

* **Pause davor** - laengere Wartezeit vor dem Schritt,
* **Erkennungsschwelle** - wie aehnlich es sein muss (Standard 78 %);
  senken, wenn sich das Fenster leicht veraendert, anheben bei
  Verwechslungen,
* **Wartezeit** - wie lange auf das Element gewartet wird,
* **Wenn nicht gefunden** - anhalten, ueberspringen oder nochmal versuchen,
* Schritte verschieben, abschalten, loeschen, Pausen einfuegen.

**"Erkennung jetzt testen"** sucht den Ausschnitt sofort auf dem aktuellen
Bildschirm und nennt die erreichte Aehnlichkeit - die schnellste Art,
einen zickigen Schritt einzustellen. Mit **"Ab hier ausfuehren"** bzw.
**"Nur diesen Schritt"** laesst sich gezielt ein Teil erproben.

Ueber **Schritte anhaengen** kann eine bestehende Aufnahme spaeter
fortgesetzt werden.

### Weitergeben

Jeder Button ist ein eigener Ordner und laesst sich als ZIP exportieren und
auf einem anderen Mac wieder importieren (Menue **Button > Exportieren /
Importieren**).

## Ohne Fenster: die Kommandozeile

```bash
python -m klickpilot --list                 # vorhandene Buttons anzeigen
python -m klickpilot --run "Rechnung"       # Ablauf starten
python -m klickpilot --record "Neuer Name"  # aufnehmen (Ende mit Strg+C)
python -m klickpilot --check                # Freigaben pruefen
```

Damit lassen sich Ablaeufe auch aus anderen Skripten, aus einem
Automator-Dienst oder zeitgesteuert starten.

## Wo die Daten liegen

Voreingestellt unter `~/Klickpilot`, ein Ordner je Button:

```
~/Klickpilot/
  rechnung-drucken/
    macro.json          Schrittfolge (lesbares JSON)
    assets/
      a0001.png         gemerkter Bildausschnitt
      a0001_ctx.png     zugehoerige Umgebung
```

Der Ordner laesst sich frei kopieren und sichern.

## Aufbau des Projekts

```
klickpilot/
  matcher.py     Bildaehnlichkeitssuche (ZNCC, grob/fein, mehrere Groessen)
  anchors.py     Ausschnitte anlegen und auf dem Bildschirm wiederfinden
  screen.py      Bildschirmfotos (Quartz), Punkte/Pixel, Mitschnittpuffer
  inputs.py      Maus- und Tastaturereignisse erzeugen (Quartz)
  keytap.py      Eigene Tastaturerfassung (Quartz-Tap statt pynput)
  recorder.py    Ereignisse zu einer sauberen Schrittfolge verdichten
  hotkeys.py     Globale Tastenkuerzel (nutzt keytap.py)
  player.py      Wiedergabe samt Warten, Wiederholen, Abbrechen
  storage.py     Ablage je Button, Export/Import
  models.py      Datenmodell (Anker, Schritt, Button)
  app.py         Hauptfenster (Tkinter)
  editor.py      Schritt-Editor
  cli.py         Kommandozeile
  permissions.py Pruefung der macOS-Freigaben
run.py           Einstiegspunkt fuer PyInstaller-Builds
tests/           Automatisierte Tests (pytest)
build/           Skript zum Bauen der macOS-App
```

## Entwicklung / Tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests/
```

Die Tests bauen einen **simulierten Bildschirm** mit Fenstern, Listen und
Knoepfen. Damit wird der komplette Weg geprueft - Aufnahme, Speichern,
Wiederfinden auf einem verschobenen/aufgehellten/gezoomten Bildschirm bis
zum ausgeloesten Klick - ohne echten Mac und ohne dass sich dabei eine Maus
bewegt. Die Oberflaechentests laufen mit, sobald Tkinter und eine Anzeige
vorhanden sind.

## Grenzen

* **Nur macOS.** Aufnahme und Wiedergabe setzen auf Quartz auf.
* **Was sich nicht mehr aehnlich sieht, wird nicht gefunden.** Nach einem
  groesseren Programm-Update mit neuem Aussehen muessen betroffene Schritte
  neu aufgenommen werden. Ein Wechsel zwischen hellem und dunklem
  Erscheinungsbild verandert Bedienelemente meist zu stark.
* **Verdeckte Elemente gibt es nicht.** Was ein anderes Fenster ueberdeckt,
  ist fuer Klickpilot nicht da - deshalb blendet sich das eigene Fenster
  waehrend der Wiedergabe aus.
* **Text wird zeichenweise gesendet**, layoutunabhaengig. Tastenkombinationen
  (Cmd+C und aehnliche) gehen dagegen ueber die Tastenposition und setzen
  ein US-/deutsches Standardlayout voraus.
* **Ein Ablauf ist kein Skript mit Bedingungen.** Es gibt keine Verzweigungen
  ("wenn Fehlermeldung, dann ..."); ein Schritt kann lediglich uebersprungen
  oder wiederholt werden.
* **Kein Ersatz fuer eine echte Schnittstelle.** Wo ein Programm eine
  Import-/Exportfunktion oder eine API bietet, ist diese immer der
  verlaesslichere Weg. Ablaeufe mit rechtlicher oder medizinischer Tragweite
  bitte stichprobenartig kontrollieren - Klickpilot bedient die Oberflaeche,
  es prueft nicht, ob das Ergebnis stimmt.
