"""Emulated systems: file extensions, candidate libretro cores, BIOS needs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class System:
    id: str
    name: str
    extensions: tuple[str, ...]
    cores: tuple[str, ...]              # libretro core basenames, preferred first
    bios: tuple[str, ...] = ()          # files expected in the system directory
    notes: str = ""
    ports: int = 2                      # joypad ports to plug in
    bios_required: bool = False         # False: the core has a built-in/HLE fallback
    bios_any: bool = False              # True: one of `bios` is enough (e.g. PS1 regions)
    options: tuple[tuple[str, str], ...] = ()  # core option defaults retrodesk prefers
    touch: bool = False                 # mouse clicks on the image act as a touch screen
    bios_subdirs: tuple[str, ...] = ()  # system/ subfolders some cores also search


SYSTEMS: tuple[System, ...] = (
    System("nes", "Nintendo Entertainment System", (".nes", ".fds", ".unf", ".unif"),
           ("mesen", "fceumm", "nestopia"), bios=("disksys.rom",), notes="disksys.rom only for FDS"),
    System("snes", "Super Nintendo", (".sfc", ".smc", ".fig", ".swc", ".bs"),
           ("snes9x", "bsnes")),
    System("gb", "Game Boy", (".gb",), ("gambatte", "mgba", "sameboy")),
    System("gbc", "Game Boy Color", (".gbc",), ("gambatte", "mgba", "sameboy")),
    System("gba", "Game Boy Advance", (".gba",), ("mgba",), bios=("gba_bios.bin",),
           notes="BIOS optional; mGBA has a HLE fallback"),
    System("nds", "Nintendo DS", (".nds", ".dsi", ".ids"), ("melondsds", "melonds"),
           bios=("bios7.bin", "bios9.bin", "firmware.bin"),
           notes="melonDS falls back to FreeBIOS; real BIOS/firmware improves compatibility",
           # "Touch" is the old melonds core's absolute-pointer mode; melondsds ignores
           # the value (not one of its choices) and keeps its own "auto".
           options=(("melonds_touch_mode", "Touch"),), touch=True, bios_subdirs=("melonDS DS",)),
    System("psx", "PlayStation", (".cue", ".chd", ".pbp", ".m3u", ".ecm", ".img"),
           ("pcsx_rearmed", "swanstation", "mednafen_psx"),
           bios=("scph5501.bin", "scph1001.bin", "scph7001.bin"), bios_any=True,
           notes="pcsx_rearmed has an HLE BIOS; a real one is more compatible"),
    System("neogeo", "Neo Geo", (".zip", ".7z"), ("fbneo",), bios=("neogeo.zip",), bios_required=True,
           bios_subdirs=("fbneo",),
           notes="neogeo.zip goes next to the game zip or in the system directory"),
    System("arcade", "Arcade (MAME 2003 Plus)", (".zip",), ("mame2003_plus", "mame2010", "mame"),
           notes="ROM sets must match the core's MAME version"),
    System("psp", "PlayStation Portable", (".iso", ".cso", ".pbp", ".chd"), ("ppsspp",),
           notes="needs hw_render (phase 3)"),
    System("3ds", "Nintendo 3DS", (".3ds", ".3dsx", ".cci", ".cxi"), ("citra",),
           notes="needs hw_render (phase 3)"),
    System("ps2", "PlayStation 2", (".iso", ".bin", ".cso", ".chd"), ("play",),
           bios=(), notes="experimental core; needs hw_render (phase 3)"),
)

BY_ID = {s.id: s for s in SYSTEMS}

# Extra buttons worth telling the player about, by core basename. Keys: E=L2 R=R2 D=L3 F=R3.
CONTROL_HINTS = {
    "melondsds": "Click the bottom screen to touch. F (R3) cycles screen layouts.",
    "melonds": "Click the bottom screen to touch. R (R2) swaps screens, D (L3) closes the lid.",
}

# Extensions that several systems claim; the user (or a folder name) must disambiguate.
AMBIGUOUS = {".zip", ".iso", ".bin", ".chd", ".pbp", ".cso"}

# Default system for an ambiguous extension when nothing else decides.
DEFAULT_FOR_EXTENSION = {".zip": "arcade", ".iso": "psp", ".bin": "psx", ".chd": "psx",
                         ".pbp": "psx", ".cso": "psp"}

def missing_bios(system: System, search: list[Path]) -> list[str]:
    """BIOS files of `system` not found in any of the `search` directories."""
    found = [name for name in system.bios if any((d / name).is_file() for d in search)]
    if system.bios_any:
        return [] if found or not system.bios else list(system.bios)
    return [name for name in system.bios if name not in found]


EXTENSIONS: frozenset[str] = frozenset(ext for s in SYSTEMS for ext in s.extensions)

_FOLDER_ALIASES = {
    "nes": "nes", "famicom": "nes", "fds": "nes",
    "snes": "snes", "sfc": "snes", "superfamicom": "snes", "supernintendo": "snes",
    "gb": "gb", "gameboy": "gb", "gbc": "gbc", "gameboycolor": "gbc", "gba": "gba", "gameboyadvance": "gba",
    "nds": "nds", "ds": "nds", "3ds": "3ds",
    "psx": "psx", "ps1": "psx", "playstation": "psx", "psp": "psp", "ps2": "ps2",
    "neogeo": "neogeo", "mame": "arcade", "arcade": "arcade", "fbneo": "neogeo",
}


def system_for(rom: Path, hint: str | None = None) -> System:
    """Pick the system for a ROM from an explicit hint, its parent folder names, or its extension."""
    if hint:
        try:
            return BY_ID[hint.lower()]
        except KeyError:
            raise ValueError(f"unknown system '{hint}'; known: {', '.join(BY_ID)}") from None
    ext = rom.suffix.lower()
    candidates = [s for s in SYSTEMS if ext in s.extensions]
    if not candidates:
        raise ValueError(f"no system handles {ext or 'files without extension'}")
    if len(candidates) > 1:
        for part in reversed(rom.resolve().parts[:-1]):
            key = part.lower().replace(" ", "").replace("_", "").replace("-", "")
            if key in _FOLDER_ALIASES and BY_ID[_FOLDER_ALIASES[key]] in candidates:
                return BY_ID[_FOLDER_ALIASES[key]]
        default = DEFAULT_FOR_EXTENSION.get(ext)
        if default:
            return BY_ID[default]
    return candidates[0]
