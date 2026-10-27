import struct

import pytest

from retrodesk.gen3.model import (
    BadChecksum, decode_text, is_shiny, parse_battle_mon, parse_party_mon, read_party, read_rom_tables,
)
from retrodesk.gen3.symbols import Symbols, UnsupportedRom, identify

from gen3_fixtures import FakeMemory, battle_mon, encode_text, party_mon


def test_decode_text_stops_at_terminator():
    assert decode_text(encode_text("Pikachu 25") + b"\xFF\x00") == "Pikachu 25"


@pytest.mark.parametrize("personality", [0, 1, 7, 13, 23, 0xDEADBEEF])
def test_party_mon_roundtrip_for_every_substruct_order(personality):
    raw = party_mon(personality, 0x1234ABCD, species=277, level=12, hp=30, max_hp=34,
                    moves=(33, 43, 0, 0), pp=(35, 30, 0, 0), nickname="Treecko")
    mon = parse_party_mon(raw)
    assert mon is not None
    assert (mon.species, mon.level, mon.hp, mon.max_hp) == (277, 12, 30, 34)
    assert mon.moves == (33, 43, 0, 0) and mon.pp == (35, 30, 0, 0)
    assert mon.ivs == (31, 30, 29, 28, 27, 26)
    assert mon.nickname == "Treecko"


def test_party_mon_bad_checksum_is_reported_not_guessed():
    with pytest.raises(BadChecksum):
        parse_party_mon(party_mon(5, 6, species=1, level=5, hp=1, max_hp=1, corrupt=True))


def test_empty_party_slots():
    mem = FakeMemory()
    mem.write(0x02000000, party_mon(9, 9, species=25, level=5, hp=20, max_hp=20))
    party = read_party(mem, 0x02000000)
    assert party[0] is not None and party[0].species == 25
    assert party[1:] == [None] * 5


def test_shiny_formula():
    ot = (54321 << 16) | 12345
    assert is_shiny(((12345 ^ 54321) << 16) | 0, ot)
    assert not is_shiny(0x00000000, ot)


def test_battle_mon_layout():
    mon = parse_battle_mon(battle_mon(species=280, level=9, hp=21, max_hp=27, types=(14, 14),
                                      moves=(45, 93, 0, 0), pp=(40, 25, 0, 0), nickname="Ralts"))
    assert (mon.species, mon.level, mon.hp, mon.max_hp, mon.types) == (280, 9, 21, 27, (14, 14))
    assert mon.moves == (45, 93, 0, 0) and mon.nickname == "Ralts"


def test_rom_tables():
    rom = bytearray(0x1000)
    base = 0x08000000
    moves_at, names_at, info_at, sp_names_at, chart_at, nat_at = 0x100, 0x200, 0x400, 0x600, 0x800, 0x900
    struct.pack_into("<BBBBBBBbB3x", rom, moves_at + 12, 0, 40, 0, 100, 35, 0, 0, 0, 0)  # move 1
    rom[names_at + 13:names_at + 26] = (encode_text("Pound") + b"\xFF" * 13)[:13]
    rom[info_at + 28 + 6:info_at + 28 + 8] = bytes([12, 3])  # species 1 Grass/Poison
    rom[sp_names_at + 11:sp_names_at + 22] = (encode_text("Bulbasaur") + b"\xFF" * 11)[:11]
    rom[chart_at:chart_at + 10] = bytes([10, 12, 20, 0xFE, 0xFE, 0, 0, 7, 0, 0xFF])
    struct.pack_into("<H", rom, nat_at, 1)
    t = read_rom_tables(bytes(rom), base + moves_at, base + names_at, base + info_at, base + sp_names_at,
                        base + chart_at, base + nat_at, move_count=2, species_count=2)
    assert t.moves[1].name == "Pound" and t.moves[1].power == 40 and t.moves[1].physical
    assert t.species_name(1) == "Bulbasaur" and t.species_types[1] == (12, 3)
    assert t.national_dex == [0, 1]
    assert t.effectiveness(10, (12, 3)) == 2.0
    assert t.effectiveness(0, (7, 7)) == 0.0
    assert t.foresight_split == 1


def test_identify_rejects_unknown_builds():
    rom = bytearray(0x200)
    rom[0xAC:0xB0] = b"BPEE"
    assert identify(bytes(rom)).sym_file == "emerald.sym"
    rom[0xBC] = 1
    with pytest.raises(UnsupportedRom):
        identify(bytes(rom))


def test_symbols_nearest_resolves_duplicated_statics():
    sym = Symbols.parse("08057588 l 00000266 HandleInputChooseAction\n"
                        "081593d8 l 00000184 HandleInputChooseAction\n"
                        "08057bfc l 000003c0 HandleInputChooseMove\n")
    with pytest.raises(KeyError):
        sym["HandleInputChooseAction"]
    assert sym.nearest("HandleInputChooseAction", "HandleInputChooseMove") == 0x08057588
