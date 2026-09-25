#!/bin/bash
# Startet Jev Mario: holt die neueste Version, startet das Spiel, Mario spielt.
BRANCH="claude/nifty-hypatia-9085kf"
ZIP="https://github.com/Dommeleee/SM64JEV/archive/refs/heads/$BRANCH.zip"
DEST="$HOME/JevMario"

echo "Suche nach Updates ..."
tmp="$(mktemp -d)"
if curl -fsSL --max-time 60 "$ZIP" -o "$tmp/app.zip" && unzip -q "$tmp/app.zip" -d "$tmp"; then
    rm -rf "$DEST"
    mv "$tmp"/SM64JEV-*/ "$DEST"
    echo "Neueste Version geladen."
else
    echo "Update nicht möglich (kein Internet?), nutze die vorhandene Version."
fi
rm -rf "$tmp"

if [ ! -d "$DEST/jev_player" ]; then
    echo "Programm nicht gefunden. Bitte Internetverbindung prüfen und nochmal starten."
else
    cd "$DEST" && python3 -m jev_player start "$@"
fi
echo
read -r -p "Fertig. Enter drücken zum Schließen."
