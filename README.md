# SM64JEV – Jev spielt Super Mario 64

Ein kleines Experiment: Das Entscheidungsmodell **Jev** von TypeSafe AI steuert Mario in
[SM64CoopDX](https://github.com/coop-deluxe/sm64coopdx), einer Mac-, Windows- und Linux-Version
von Super Mario 64.

- **Das Spiel** läuft mit dem Mod `mod/jev-mario`. Er meldet Marios Position sowie Münzen,
  Sterne und Abgründe in der Nähe. Außerdem führt er die Befehle bildgenau aus.
- **Python** (`jev_player/`) liest diese Meldungen und fragt Jev oder eine einfache Regel:
  *laufen, springen, Weitsprung, erkunden oder anhalten?*
- **Eine Sicherheitsregel** verhindert, dass Mario absichtlich in einen Abgrund läuft, egal was
  Jev sagt.

Jev kostet 0,042 $ pro Million Eingabe-Tokens, die Antworten sind kostenlos. Eine Entscheidung
kostet weit weniger als einen hundertstel Cent. Das Programm hört automatisch auf, Jev zu fragen, wenn das
Budget verbraucht ist (Standard: 0,10 $). Dann steuert die einfache Regel weiter.

## ⚠️ Niemals hochladen

- **Die Spieldatei (`.z64`)**: Sie ist urheberrechtlich geschützt und gehört nur auf deinen
  Rechner.
- **Den API-Schlüssel**: Er wird in `~/.jev-mario/api_key` auf deinem Rechner gespeichert, nicht
  in diesem Ordner.

Die Datei `.gitignore` schützt zusätzlich davor, dass so etwas versehentlich hochgeladen wird.

## Einrichtung auf dem Mac (einmalig)

1. **SM64CoopDX herunterladen**: <https://github.com/coop-deluxe/sm64coopdx/releases>, dort die
   macOS-Datei der neuesten Version (mindestens v1.4). Starte die App einmal. Sie fragt nach der
   Spieldatei: `Super Mario 64 (USA).z64` auswählen. Danach die App wieder schließen.
2. **Diesen Ordner herunterladen**: Auf GitHub auf den grünen Knopf **Code**, dann auf
   **Download ZIP** klicken und die ZIP-Datei entpacken.
3. **`1-Einrichten.command` doppelklicken.** Das installiert den Mod und fragt einmal nach dem
   Jev-API-Schlüssel. Beim Einfügen ist nichts zu sehen, das ist Absicht.
   - Meldet macOS *„nicht verifizierter Entwickler“*: Rechtsklick auf die Datei, dann **Öffnen**.
   - Fehlt `python3`: macOS bietet dann an, die „Befehlszeilen-Entwicklertools“ zu installieren.
     Bestätige das und doppelklicke die Datei danach noch einmal.

## Spielen

1. SM64CoopDX starten, auf **Host** klicken, unter **Mods** den Eintrag **Jev Mario** anhaken
   und das Spiel starten.
2. Eine der beiden Dateien doppelklicken:
   - `2-Mario-mit-Regel.command`: die einfache Regel, kostenlos
   - `3-Mario-mit-Jev.command`: Jev entscheidet, höchstens 0,10 $
3. Oben links im Spiel steht, was Mario gerade tut. Im Terminal siehst du die Entscheidungen und
   die bisherigen Kosten.
4. **Beenden**: im Terminal `Ctrl+C` drücken. Dann steuerst du wieder selbst. Im Spiel-Chat kannst
   du die Steuerung auch mit `/jev off` und `/jev on` aus- und einschalten.

## Ohne Spiel testen

Es gibt eine kleine Testwelt mit Münzen, Plattformen und Abgründen. Sie ist viel einfacher als das
echte Spiel und dient nur zum Ausprobieren und Vergleichen:

```bash
python3 -m jev_player sim --brain rule --seconds 120
python3 -m jev_player sim --brain jev --seconds 120 --budget 0.02
python3 -m unittest discover tests      # automatische Tests
```

## Ehrliche Grenzen

- Mario läuft zu Münzen und Sternen, springt auf Stufen und weicht Abgründen aus. Einen Stern
  „verstehen“ (Bosse, Rätsel, Kletterpassagen) kann er nicht.
- Die Regel ist zum Vergleich da. Nur wenn Jev mehr Münzen sammelt als die Regel, hilft Jev
  wirklich.
