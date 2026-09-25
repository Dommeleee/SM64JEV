"""Command line: python3 -m jev_player <command>

  start    everything in one go: install mod, launch the game as host, let Mario play
  setup    only install the mod into SM64CoopDX and store the Jev API key
  play     let the rule or Jev steer Mario in an already running game
  sim      run a brain in the built-in test world (no game needed)
"""

from __future__ import annotations

import argparse
import getpass
import glob
import shutil
import subprocess
import sys
import time
from pathlib import Path

from jev_player.bridge import Command, GameBridge
from jev_player.brains import HOLD_FRAMES, JevBrain, RuleBrain
from jev_player.jev_client import JevClient, load_api_key, save_api_key
from jev_player.paths import MOD_NAME, find_user_dir
from jev_player.sim import SimWorld

REPO_DIR = Path(__file__).resolve().parent.parent
MOD_VERSION = 3  # must match MOD_VERSION in mod/jev-mario/main.lua
LOG_DIR = Path.home() / ".jev-mario"
GAME_ARGS = ["--server", "7777", "--disable-mods", "--enable-mod", MOD_NAME,
             "--skip-intro", "--skip-update-check", "--no-discord", "--playername", "Jev"]


def make_brain(brain_name: str, budget: float):
    if brain_name == "rule":
        return RuleBrain(), None
    key = load_api_key()
    if not key:
        sys.exit("Kein Jev-API-Schlüssel gefunden. Bitte zuerst: python3 -m jev_player setup")
    client = JevClient(key, budget_usd=budget)
    return JevBrain(client), client


def install_mod(user_dir: Path) -> Path:
    mods_dir = user_dir / "mods"
    target = mods_dir / MOD_NAME
    mods_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(REPO_DIR / "mod" / MOD_NAME, target)
    (user_dir / "sav").mkdir(exist_ok=True)
    return target


def ask_for_key_once() -> None:
    if load_api_key() or not sys.stdin.isatty():
        return
    key = getpass.getpass("Jev-API-Schlüssel einfügen (unsichtbar, Enter = ohne Jev spielen): ").strip()
    if key:
        print(f"Gespeichert in {save_api_key(key)} (nur auf diesem Rechner).")


def find_game() -> Path | None:
    """Executable inside the SM64CoopDX app bundle (macOS) or a plain executable."""
    home = str(Path.home())
    patterns = [
        "/Applications/*coop*.app", "/Applications/*Coop*.app",
        home + "/Applications/*coop*.app", home + "/Applications/*Coop*.app",
        home + "/Downloads/*coop*.app", home + "/Downloads/*Coop*.app",
        home + "/Downloads/*/*coop*.app", home + "/Downloads/*/*Coop*.app",
        home + "/Desktop/*coop*.app", home + "/Desktop/*Coop*.app",
    ]
    for pattern in patterns:
        for app in sorted(glob.glob(pattern)):
            exes = [p for p in (Path(app) / "Contents" / "MacOS").glob("*") if p.is_file()]
            if exes:
                return exes[0]
    for name in ("sm64coopdx", "sm64coopdx.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def cmd_setup(args):
    user_dir = find_user_dir(args.user_dir)
    if not user_dir.exists():
        print(f"SM64CoopDX-Ordner nicht gefunden ({user_dir}).")
        print("Bitte SM64CoopDX einmal starten und wieder schließen, dann setup erneut ausführen.")
        return
    print(f"Mod installiert: {install_mod(user_dir)}")
    ask_for_key_once()


def cmd_start(args):
    user_dir = find_user_dir(args.user_dir)
    game = find_game()
    if game is None:
        sys.exit("SM64CoopDX nicht gefunden. Bitte die App in den Ordner 'Programme' ziehen und nochmal starten.")
    if not user_dir.exists():
        sys.exit("SM64CoopDX wurde noch nie gestartet. Bitte einmal normal öffnen, die Spieldatei (.z64) "
                 "auswählen, schließen und dann nochmal hier starten.")
    install_mod(user_dir)
    ask_for_key_once()
    brain_name = args.brain or ("jev" if load_api_key() else "rule")

    # a running game still has the old mod loaded, so restart it
    subprocess.run(["pkill", "-f", str(game)], capture_output=True)
    time.sleep(1.5)
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / "game.log"
    log = open(log_path, "w")
    print("Starte das Spiel ...")
    proc = subprocess.Popen([str(game)] + GAME_ARGS, stdout=log, stderr=subprocess.STDOUT)
    try:
        run(GameBridge(user_dir), brain_name, args.budget, game_proc=proc, log_path=log_path)
    finally:
        log.close()


def cmd_play(args):
    run(GameBridge(find_user_dir(args.user_dir)), args.brain or "rule", args.budget)


def run(bridge: GameBridge, brain_name: str, budget: float, game_proc=None, log_path: Path | None = None):
    brain, client = make_brain(brain_name, budget)
    next_id = int(time.time() * 10) % 1_000_000_000
    hold_until = -1
    connected = False
    last_print = 0.0
    waiting_since = time.monotonic()
    hinted = False
    log_pos = 0
    print(f"Gehirn: {'Jev' if brain.name == 'jev' else 'einfache Regel (kostenlos)'}. Beenden mit Ctrl+C.")
    print("Warte auf das Spiel ...")
    try:
        while True:
            if game_proc is not None and game_proc.poll() is not None:
                print("Das Spiel wurde geschlossen.")
                break
            if log_path is not None:
                log_pos = report_mod_errors(log_path, log_pos)

            state = bridge.read_state()
            if state is None:
                if not connected and not hinted and time.monotonic() - waiting_since > 25:
                    hinted = True
                    print("Noch keine Daten vom Spiel. Falls Mario schon im Level steht, schick Claude bitte")
                    print(f"diese Zeile und die Datei {LOG_DIR / 'game.log'}. Info: {bridge.last_error}")
                time.sleep(0.03)
                continue
            if not connected:
                connected = True
                print("Verbunden! Mario wird jetzt gesteuert.")
                if state.get("v") != MOD_VERSION:
                    print(f"Achtung: Im Spiel läuft eine alte Mod-Version ({state.get('v')}). Spiel schließen "
                          f"und neu starten.")
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


def report_mod_errors(log_path: Path, pos: int) -> int:
    """Print new Lua errors of our mod from the game's log."""
    try:
        with open(log_path, errors="replace") as f:
            f.seek(pos)
            text = f.read()
            pos = f.tell()
    except OSError:
        return pos
    for line in text.splitlines():
        if line.startswith("[LUA]") or f"'{MOD_NAME}/main.lua'" in line:
            print(f"Spiel meldet: {line.strip()}")
    return pos


def cmd_sim(args):
    world = SimWorld(seed=args.seed)
    brain, client = make_brain(args.brain or "rule", args.budget)
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

    for name, func, helptext in (("start", cmd_start, "alles automatisch: Mod, Spiel, Steuerung"),
                                 ("play", cmd_play, "im laufenden Spiel steuern"),
                                 ("sim", cmd_sim, "in der Testwelt ohne Spiel ausprobieren")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--brain", choices=["rule", "jev"], default=None,
                       help="Standard: Jev, wenn ein Schlüssel gespeichert ist, sonst die Regel")
        p.add_argument("--budget", type=float, default=0.10, help="Höchstbetrag in Dollar für Jev (Standard 0.10)")
        p.set_defaults(func=func)
        if name == "sim":
            p.add_argument("--seconds", type=float, default=120)
            p.add_argument("--seed", type=int, default=0)
        else:
            p.add_argument("--user-dir", help="SM64CoopDX-Benutzerordner")

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
