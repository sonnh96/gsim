"""User data locations and ROM -> core selection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .systems import EXTENSIONS, System, system_for

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_SUFFIX = ".dylib" if sys.platform == "darwin" else ".so"

# Kept for callers that only need "is this a ROM?"; see systems.py for the full table.
CORES_BY_EXTENSION = {ext: None for ext in EXTENSIONS}


def data_dir() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "retrodesk"


def cores_dir() -> Path:
    env = os.environ.get("RETRODESK_CORES")
    return Path(env) if env else REPO_ROOT / "cores"


def core_path(name: str) -> Path:
    return cores_dir() / f"{name}_libretro{CORE_SUFFIX}"


def installed_cores(system: System) -> list[Path]:
    return [p for name in system.cores if (p := core_path(name)).exists()]


def core_for(rom: Path, system: str | None = None) -> Path:
    sysdef = system_for(rom, system)
    found = installed_cores(sysdef)
    if not found:
        raise FileNotFoundError(
            f"no core installed for {sysdef.name}; wanted one of {', '.join(sysdef.cores)} "
            f"in {cores_dir()} (run scripts/fetch_assets.py)")
    return found[0]


def rom_paths(rom: Path) -> dict[str, Path]:
    base = data_dir()
    return {
        "system": base / "system",
        "saves": base / "saves",
        "sram": base / "saves" / f"{rom.stem}.srm",
        "states": base / "states" / rom.stem,
    }
