"""File bridge between Python and the jev-mario Lua mod.

The game writes Mario's state into `sav/jev-mario.modfs` (a zip archive).
We answer with one command line in `sav/jev-cmd.modfs`, which the mod reloads.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from jev_player.paths import CMD_MODFS, MOD_NAME

CMD_PROPERTIES = {
    "isPublic": True,
    "files": {"cmd.txt": {"isPublic": True, "isText": True}},
}


@dataclass
class Command:
    id: int
    act: str  # walk | jump | longjump | dive | stop
    tx: float = 0.0
    tz: float = 0.0
    frames: int = 20

    def to_line(self) -> str:
        return f"id={self.id} act={self.act} tx={self.tx:.0f} tz={self.tz:.0f} frames={self.frames}"


class GameBridge:
    def __init__(self, user_dir: Path):
        self.sav_dir = user_dir / "sav"
        self.state_path = self.sav_dir / f"{MOD_NAME}.modfs"
        self.cmd_path = self.sav_dir / f"{CMD_MODFS}.modfs"
        self._last_t = None

    def read_state(self) -> dict | None:
        """Newest state from the game, or None if nothing new (or mid-write)."""
        try:
            data = self.state_path.read_bytes()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                state = json.loads(zf.read("state.json"))
        except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            return None
        if state.get("t") == self._last_t:
            return None
        self._last_t = state.get("t")
        return state

    def send(self, cmd: Command) -> None:
        """Write the command atomically so the game never sees a half-written file."""
        self.sav_dir.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("cmd.txt", cmd.to_line())
            zf.writestr("properties.json", json.dumps(CMD_PROPERTIES))
        tmp = self.cmd_path.with_suffix(".tmp")
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, self.cmd_path)

    def clear(self) -> None:
        """Remove the command file so an old command is not replayed next time."""
        try:
            self.cmd_path.unlink()
        except FileNotFoundError:
            pass
