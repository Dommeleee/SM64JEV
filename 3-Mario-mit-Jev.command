#!/bin/bash
# Doppelklick startet dies im Terminal (macOS).
cd "$(dirname "$0")" || exit 1
python3 -m jev_player play --brain jev --budget 0.10
echo
read -r -p "Fertig. Enter drücken zum Schließen."
