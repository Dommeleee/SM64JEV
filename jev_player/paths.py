"""Where SM64CoopDX keeps its user files on each operating system."""

from __future__ import annotations

import os
import sys
from pathlib import Path

MOD_NAME = "jev-mario"
CMD_MODFS = "jev-cmd"


def coopdx_user_dirs() -> list[Path]:
    """Candidate SM64CoopDX user directories, most likely first."""
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return [base / "sm64coopdx", base / "sm64ex-coop"]


def find_user_dir(override: str | None = None) -> Path:
    """The SM64CoopDX user directory (contains `mods/` and `sav/`)."""
    if override:
        return Path(override).expanduser()
    candidates = coopdx_user_dirs()
    for path in candidates:
        if path.is_dir() and any(path.iterdir()):
            return path
    return candidates[0]
