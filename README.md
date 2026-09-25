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

1. **SM64CoopDX installieren**: <https://github.com/coop-deluxe/sm64coopdx/releases>, dort die
   macOS-Datei der neuesten Version herunterladen und die App in **Programme** ziehen. Die App
   einmal öffnen, die Spieldatei `Super Mario 64 (USA).z64` auswählen und die App wieder schließen.
2. **Terminal öffnen** (⌘ + Leertaste, „Terminal“ tippen, Enter), diese Zeile einfügen und Enter
   drücken:
   ```
   curl -fsSL https://raw.githubusercontent.com/Dommeleee/SM64JEV/claude/nifty-hypatia-9085kf/install.sh | bash
   ```
   Danach liegt auf dem Schreibtisch **„Jev Mario starten“**.

## Spielen

**„Jev Mario starten“ doppelklicken.** Alles andere passiert automatisch:

- Die neueste Version wird geladen.
- Das Spiel startet mit dem Mod als Host, ganz ohne Menüs.
- Mario spielt los.

Beim ersten Start fragt das Programm nach dem Jev-API-Schlüssel. Drückst du nur Enter, spielt
die kostenlose Regel statt Jev. Beenden: Spiel schließen oder im Terminal `Ctrl+C` drücken. Im
Spiel-Chat schaltest du die Steuerung mit `/jev off` und `/jev on` aus und ein.

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
