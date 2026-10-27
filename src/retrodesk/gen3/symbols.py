"""Generation 3 ROM identification and pret decomp symbol tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SYM_DIR = Path(__file__).resolve().parents[3] / "data" / "sym"


@dataclass(frozen=True)
class Gen3Game:
    code: str          # 4-byte GBA game code from the ROM header
    revision: int
    title: str
    sym_file: str
    species_table: str  # base stats symbol (renamed across decomps)
    national_table: str


# Only builds whose layout matches a published pret `symbols` branch.
SUPPORTED = {
    ("BPEE", 0): Gen3Game("BPEE", 0, "Pokemon Emerald (USA)", "emerald.sym", "gSpeciesInfo",
                          "sSpeciesToNationalPokedexNum"),
    ("BPRE", 0): Gen3Game("BPRE", 0, "Pokemon FireRed (USA) 1.0", "firered.sym", "gSpeciesInfo",
                          "sSpeciesToNationalPokedexNum"),
    ("AXVE", 0): Gen3Game("AXVE", 0, "Pokemon Ruby (USA) 1.0", "ruby.sym", "gBaseStats",
                          "gSpeciesToNationalPokedexNum"),
}


class UnsupportedRom(ValueError):
    pass


def identify(rom: bytes) -> Gen3Game:
    if len(rom) < 0xC0:
        raise UnsupportedRom("file is too small to be a GBA ROM")
    code = rom[0xAC:0xB0].decode("ascii", "replace")
    revision = rom[0xBC]
    game = SUPPORTED.get((code, revision))
    if game is None:
        raise UnsupportedRom(f"no symbol table for game code {code} revision {revision}")
    return game


class Symbols:
    """Name -> addresses parsed from a pret `.sym` file.

    Local (static) symbols can repeat across translation units, so every name
    maps to all of its addresses.
    """

    def __init__(self, entries: dict[str, list[int]]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> "Symbols":
        return cls.parse(path.read_text())

    @classmethod
    def parse(cls, text: str) -> "Symbols":
        entries: dict[str, list[int]] = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) != 4:
                continue
            addr, _, _, name = parts
            entries.setdefault(name, []).append(int(addr, 16))
        return cls(entries)

    def all(self, name: str) -> list[int]:
        return list(self._entries.get(name, []))

    def __getitem__(self, name: str) -> int:
        addrs = self._entries.get(name)
        if not addrs:
            raise KeyError(name)
        if len(addrs) > 1:
            raise KeyError(f"{name} is ambiguous; use nearest()")
        return addrs[0]

    def nearest(self, name: str, anchor: str) -> int:
        """Resolve a repeated static symbol to the copy closest to `anchor`.

        Battle controller input handlers share names across player, safari and
        link controllers; the player copy sits in the same unit as the anchor.
        """
        target = self[anchor]
        return min(self.all(name) or [self[name]], key=lambda a: abs(a - target))
