#!/bin/bash
# Einmalige Einrichtung auf dem Mac:
#   curl -fsSL https://raw.githubusercontent.com/Dommeleee/SM64JEV/claude/nifty-hypatia-9085kf/install.sh | bash
set -e
BRANCH="claude/nifty-hypatia-9085kf"
LAUNCHER="$HOME/Desktop/Jev Mario starten.command"
curl -fsSL "https://raw.githubusercontent.com/Dommeleee/SM64JEV/$BRANCH/Jev-Mario-starten.command" -o "$LAUNCHER"
chmod +x "$LAUNCHER"
echo
echo "Fertig! Auf deinem Schreibtisch liegt jetzt: 'Jev Mario starten'."
echo "Ab jetzt nur noch das doppelklicken."
