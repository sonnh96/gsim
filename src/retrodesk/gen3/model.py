"""Generation 3 data structures, decoded from guest RAM and the ROM image.

Layouts follow the pret decompilations (pokeemerald, pokefirered, pokeruby),
which share these structures across Ruby/Sapphire, FireRed/LeafGreen and
Emerald.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Protocol

TYPE_NAMES = [
    "Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost", "Steel",
    "???", "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon", "Dark",
]
TYPE_MYSTERY = 9

_CHARSET = {0x00: " ", 0x1B: "é", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB0: "…",
            0xB1: "“", 0xB2: "”", 0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀", 0xB8: ",",
            0xBA: "/"}
_CHARSET.update({0xA1 + i: str(i) for i in range(10)})
_CHARSET.update({0xBB + i: chr(ord("A") + i) for i in range(26)})
_CHARSET.update({0xD5 + i: chr(ord("a") + i) for i in range(26)})


def decode_text(raw: bytes) -> str:
    out = []
    for b in raw:
        if b == 0xFF:
            break
        out.append(_CHARSET.get(b, "�"))
    return "".join(out)


class Memory(Protocol):
    def read(self, addr: int, size: int) -> bytes: ...


# -- party Pokemon (struct Pokemon, 100 bytes) -------------------------------

PARTY_MON_SIZE = 100
PARTY_SIZE = 6

# Substructure order per personality % 24: G=growth, A=attacks, E=EVs, M=misc.
_ORDERS = ["GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA", "AGEM", "AGME", "AEGM", "AEMG",
           "AMGE", "AMEG", "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG", "MGAE", "MGEA",
           "MAGE", "MAEG", "MEGA", "MEAG"]


class BadChecksum(ValueError):
    pass


@dataclass(frozen=True)
class PartyMon:
    personality: int
    ot_id: int
    nickname: str
    species: int
    held_item: int
    experience: int
    moves: tuple[int, int, int, int]
    pp: tuple[int, int, int, int]
    ivs: tuple[int, int, int, int, int, int]
    is_egg: bool
    level: int
    hp: int
    max_hp: int

    @property
    def shiny(self) -> bool:
        return is_shiny(self.personality, self.ot_id)


def is_shiny(personality: int, ot_id: int) -> bool:
    x = (ot_id & 0xFFFF) ^ (ot_id >> 16) ^ (personality & 0xFFFF) ^ (personality >> 16)
    return x < 8


def decrypt_substructs(raw: bytes) -> dict[str, bytes]:
    """Decrypt and reorder the 48-byte secure block of a struct Pokemon."""
    personality, ot_id = struct.unpack_from("<II", raw, 0)
    key = personality ^ ot_id
    words = struct.unpack_from("<12I", raw, 0x20)
    plain = struct.pack("<12I", *(w ^ key for w in words))
    checksum = struct.unpack_from("<H", raw, 0x1C)[0]
    if sum(struct.unpack("<24H", plain)) & 0xFFFF != checksum:
        raise BadChecksum(f"checksum mismatch for personality 0x{personality:08X}")
    order = _ORDERS[personality % 24]
    return {kind: plain[i * 12:(i + 1) * 12] for i, kind in enumerate(order)}


def parse_party_mon(raw: bytes) -> PartyMon | None:
    """Parse one party slot; None for an empty slot."""
    personality, ot_id = struct.unpack_from("<II", raw, 0)
    if personality == 0 and ot_id == 0:
        return None
    subs = decrypt_substructs(raw)
    species, item, exp = struct.unpack_from("<HHI", subs["G"], 0)
    if species == 0:
        return None
    moves = struct.unpack_from("<4H", subs["A"], 0)
    pp = struct.unpack_from("<4B", subs["A"], 8)
    iv_word = struct.unpack_from("<I", subs["M"], 4)[0]
    ivs = tuple((iv_word >> (5 * i)) & 0x1F for i in range(6))
    level = raw[0x54]
    hp, max_hp = struct.unpack_from("<HH", raw, 0x56)
    return PartyMon(personality, ot_id, decode_text(raw[8:18]), species, item, exp,
                    moves, pp, ivs, bool(iv_word >> 30 & 1), level, hp, max_hp)  # type: ignore[arg-type]


def read_party(mem: Memory, addr: int) -> list[PartyMon | None]:
    raw = mem.read(addr, PARTY_MON_SIZE * PARTY_SIZE)
    return [parse_party_mon(raw[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE]) for i in range(PARTY_SIZE)]


# -- in-battle Pokemon (struct BattlePokemon, 0x58 bytes) ---------------------

BATTLE_MON_SIZE = 0x58
MAX_BATTLERS = 4


@dataclass(frozen=True)
class BattleMon:
    species: int
    attack: int
    defense: int
    speed: int
    sp_attack: int
    sp_defense: int
    moves: tuple[int, int, int, int]
    stat_stages: tuple[int, ...]
    ability: int
    types: tuple[int, int]
    pp: tuple[int, int, int, int]
    hp: int
    level: int
    max_hp: int
    item: int
    nickname: str
    personality: int
    status1: int
    ot_id: int

    @property
    def shiny(self) -> bool:
        return is_shiny(self.personality, self.ot_id)


def parse_battle_mon(raw: bytes) -> BattleMon:
    species, atk, dfn, spe, spa, spd = struct.unpack_from("<6H", raw, 0)
    moves = struct.unpack_from("<4H", raw, 0x0C)
    stages = struct.unpack_from("<8b", raw, 0x18)
    ability, t1, t2 = raw[0x20], raw[0x21], raw[0x22]
    pp = struct.unpack_from("<4B", raw, 0x24)
    hp, level, _, max_hp, item = struct.unpack_from("<HBBHH", raw, 0x28)
    personality, status1, _, ot_id = struct.unpack_from("<IIII", raw, 0x48)
    return BattleMon(species, atk, dfn, spe, spa, spd, moves, stages, ability, (t1, t2), pp,  # type: ignore[arg-type]
                     hp, level, max_hp, item, decode_text(raw[0x30:0x3B]), personality, status1, ot_id)


def read_battle_mons(mem: Memory, addr: int, count: int) -> list[BattleMon]:
    raw = mem.read(addr, BATTLE_MON_SIZE * count)
    return [parse_battle_mon(raw[i * BATTLE_MON_SIZE:(i + 1) * BATTLE_MON_SIZE]) for i in range(count)]


# -- ROM tables ---------------------------------------------------------------

MOVE_ENTRY_SIZE = 12
SPECIES_INFO_SIZE = 28
SPECIES_NAME_LEN = 11
MOVE_NAME_LEN = 13


@dataclass(frozen=True)
class MoveInfo:
    id: int
    name: str
    effect: int
    power: int
    type: int
    accuracy: int
    pp: int
    priority: int

    @property
    def physical(self) -> bool:
        # Gen 3 splits physical/special by type, not by move.
        return self.type < TYPE_MYSTERY


@dataclass(frozen=True)
class RomTables:
    moves: list[MoveInfo]
    species_names: list[str]
    species_types: list[tuple[int, int]]
    national_dex: list[int]          # index = internal species id
    type_chart: dict[tuple[int, int], int]  # (attack, defend) -> 0/5/10/20
    foresight_split: int             # entries after this index ignore Foresight

    def species_name(self, species: int) -> str:
        return self.species_names[species] if 0 <= species < len(self.species_names) else f"#{species}"

    def effectiveness(self, attack_type: int, defend_types: tuple[int, int]) -> float:
        mult = 1.0
        seen = set()
        for t in defend_types:
            if t in seen:
                continue
            seen.add(t)
            mult *= self.type_chart.get((attack_type, t), 10) / 10
        return mult


def read_rom_tables(rom: bytes, moves_addr: int, move_names_addr: int, species_info_addr: int,
                    species_names_addr: int, type_chart_addr: int, national_addr: int,
                    move_count: int = 355, species_count: int = 412) -> RomTables:
    def off(addr: int) -> int:
        return addr - 0x08000000

    moves = []
    for i in range(move_count):
        e = rom[off(moves_addr) + i * MOVE_ENTRY_SIZE:][:MOVE_ENTRY_SIZE]
        name = decode_text(rom[off(move_names_addr) + i * MOVE_NAME_LEN:][:MOVE_NAME_LEN])
        moves.append(MoveInfo(i, name, e[0], e[1], e[2], e[3], e[4], struct.unpack_from("<b", e, 7)[0]))

    names, types = [], []
    for i in range(species_count):
        names.append(decode_text(rom[off(species_names_addr) + i * SPECIES_NAME_LEN:][:SPECIES_NAME_LEN]))
        base = off(species_info_addr) + i * SPECIES_INFO_SIZE
        types.append((rom[base + 6], rom[base + 7]))

    national = [0] + list(struct.unpack_from(f"<{species_count - 1}H", rom, off(national_addr)))

    chart: dict[tuple[int, int], int] = {}
    split = -1
    p = off(type_chart_addr)
    i = 0
    while rom[p] != 0xFF:
        if rom[p] == 0xFE:
            split = i
        else:
            chart[(rom[p], rom[p + 1])] = rom[p + 2]
            i += 1
        p += 3
    return RomTables(moves, names, types, national, chart, split)
