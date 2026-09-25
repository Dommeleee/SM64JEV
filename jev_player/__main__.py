"""Command line: python3 -m jev_player <command>

  setup    install the mod into SM64CoopDX and store the Jev API key
  play     let the rule or Jev steer Mario in the running game
  sim      run a brain in the built-in test world (no game needed)
"""

from __future__ import annotations

import argparse
import getpass
import shutil
import sys
import time
from pathlib import Path

from jev_player.bridge import Command, GameBridge
from jev_player.brains import HOLD_FRAMES, JevBrain, RuleBrain
from jev_player.jev_client import JevClient, load_api_key, save_api_key
from jev_player.paths import MOD_NAME, find_user_dir
from jev_player.sim import SimWorld

REPO_DIR = Path(__file__).resolve().parent.parent


def make_brain(args):
    if args.brain == "rule":
        return RuleBrain(), None
    key = load_api_key()
    if not key:
        sys.exit("Kein Jev-API-Schlüssel gefunden. Bitte zuerst: python3 -m jev_player setup")
    client = JevClient(key, budget_usd=args.budget)
    return JevBrain(client), client


def cmd_setup(args):
    user_dir = find_user_dir(args.user_dir)
    mods_dir = user_dir / "mods"
    if not user_dir.exists():
        print(f"SM64CoopDX-Ordner nicht gefunden ({user_dir}).")
        print("Bitte SM64CoopDX einmal starten und wieder schließen, dann setup erneut ausführen.")
        return
    target = mods_dir / MOD_NAME
    mods_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(REPO_DIR / "mod" / MOD_NAME, target)
    (user_dir / "sav").mkdir(exist_ok=True)
    print(f"Mod installiert: {target}")

    if load_api_key():
        print("Jev-API-Schlüssel ist schon gespeichert.")
    else:
        key = getpass.getpass("Jev-API-Schlüssel einfügen (Eingabe bleibt unsichtbar, leer = überspringen): ").strip()
        if key:
            print(f"Gespeichert in {save_api_key(key)} (nur auf diesem Rechner, nicht im Repository).")
    print("Fertig. Jetzt SM64CoopDX starten, unter Mods 'Jev Mario' anhaken, Spiel hosten.")


def cmd_play(args):
    user_dir = find_user_dir(args.user_dir)
    bridge = GameBridge(user_dir)
    brain, client = make_brain(args)
    next_id = int(time.time() * 10) % 1_000_000_000
    hold_until = -1
    start_coins = None
    last_print = 0.0
    waiting_since = time.monotonic()
    hinted = False
    print(f"Spiele mit '{brain.name}'. Warte auf das Spiel ({bridge.state_path}) ... Beenden mit Ctrl+C.")
    try:
        while True:
            state = bridge.read_state()
            if state is None:
                if start_coins is None and not hinted and time.monotonic() - waiting_since > 15:
                    hinted = True
                    print("Noch keine Daten vom Spiel. Bitte prüfen:")
                    print("  - Läuft SM64CoopDX, mit 'Jev Mario' unter Mods angehakt?")
                    print("  - Bist du im Spiel (nicht im Menü) und steht oben links 'Jev: ...'?")
                    print("  - Falls dort 'Jev: Fehler beim Speichern' steht: Spiel neu starten.")
                time.sleep(0.03)
                continue
            if start_coins is None:
                start_coins = state["coins"]
                print("Verbunden!")
            if state["t"] < hold_until:
                continue
            d = brain.decide(state)
            next_id += 1
            bridge.send(Command(next_id, d.act, d.tx, d.tz, frames=24))
            hold_until = state["t"] + HOLD_FRAMES.get(d.act, 0)
            if time.monotonic() - last_print > 0.5:
                last_print = time.monotonic()
                cost = f"  |  Jev: {client.usage.calls} Anfragen, {client.usage.cost:.5f} $" if client else ""
                print(f"{d.act:9s} [{d.source:6s}] {d.reason:34s} Münzen {state['coins']}{cost}")
    except KeyboardInterrupt:
        pass
    finally:
        bridge.clear()
    print_summary(brain, client)


def cmd_sim(args):
    world = SimWorld(seed=args.seed)
    brain, client = make_brain(args)
    frames = int(args.seconds * 30)
    next_id, hold_until = 0, -1
    while world.frame < frames:
        state = world.read_state()
        if state["t"] >= hold_until:
            d = brain.decide(state)
            next_id += 1
            world.send(Command(next_id, d.act, d.tx, d.tz, frames=24))
            hold_until = state["t"] + HOLD_FRAMES.get(d.act, 0)
        world.step(6)
    print(f"Testwelt {args.seed}, {args.seconds:.0f} s, Gehirn '{brain.name}': "
          f"{world.coins_collected} Münzen, {world.deaths} Stürze")
    print_summary(brain, client)
    return world


def print_summary(brain, client):
    if client:
        print(f"Jev-Anfragen: {client.usage.calls}, Kosten: {client.usage.cost:.5f} $")
    if getattr(brain, "disabled_reason", None):
        print(f"Jev wurde abgeschaltet: {brain.disabled_reason}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m jev_player", description="Jev spielt Super Mario 64")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="Mod installieren und API-Schlüssel speichern")
    p.add_argument("--user-dir", help="SM64CoopDX-Benutzerordner, falls nicht automatisch gefunden")
    p.set_defaults(func=cmd_setup)

    for name, func, helptext in (("play", cmd_play, "im laufenden Spiel steuern"),
                                 ("sim", cmd_sim, "in der Testwelt ohne Spiel ausprobieren")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--brain", choices=["rule", "jev"], default="rule")
        p.add_argument("--budget", type=float, default=0.10, help="Höchstbetrag in Dollar für Jev (Standard 0.10)")
        p.set_defaults(func=func)
        if name == "play":
            p.add_argument("--user-dir", help="SM64CoopDX-Benutzerordner")
        else:
            p.add_argument("--seconds", type=float, default=120)
            p.add_argument("--seed", type=int, default=0)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
