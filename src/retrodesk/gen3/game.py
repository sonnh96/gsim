"""Live view of a running Generation 3 game."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from .model import BattleMon, Memory, PartyMon, RomTables, read_battle_mons, read_party, read_rom_tables
from .symbols import SYM_DIR, Gen3Game, Symbols, identify

ROM_BASE = 0x08000000


class Phase(enum.Enum):
    UNKNOWN = "unknown"
    OVERWORLD = "overworld"
    BATTLE = "battle"            # battle running, no player decision pending
    CHOOSE_ACTION = "choose_action"
    CHOOSE_MOVE = "choose_move"
    CHOOSE_TARGET = "choose_target"


@dataclass(frozen=True)
class BattleSnapshot:
    phase: Phase
    player: BattleMon | None
    opponent: BattleMon | None
    action_cursor: int
    move_cursor: int
    wild: bool


BATTLE_TYPE_DOUBLE = 1 << 0
BATTLE_TYPE_TRAINER = 1 << 3


class Gen3Session:
    """Reads Gen 3 state through a guest memory map plus the ROM image."""

    def __init__(self, rom: bytes, ram: Memory, sym_dir: Path = SYM_DIR) -> None:
        self.game: Gen3Game = identify(rom)
        self.rom = rom
        self.ram = ram
        s = Symbols.load(sym_dir / self.game.sym_file)
        self.sym = s
        self.addr = {
            "battle_mons": s["gBattleMons"],
            "battlers_count": s["gBattlersCount"],
            "battle_type": s["gBattleTypeFlags"],
            "controller_funcs": s["gBattlerControllerFuncs"],
            "action_cursor": s["gActionSelectionCursor"],
            "move_cursor": s["gMoveSelectionCursor"],
            "player_party": s["gPlayerParty"],
            "enemy_party": s["gEnemyParty"],
            "main": s["gMain"],
        }
        thumb = 1  # function pointers carry the Thumb bit
        self._handlers = {
            s.nearest("HandleInputChooseAction", "HandleInputChooseMove") | thumb: Phase.CHOOSE_ACTION,
            s["HandleInputChooseMove"] | thumb: Phase.CHOOSE_MOVE,
            s.nearest("HandleInputChooseTarget", "HandleInputChooseMove") | thumb: Phase.CHOOSE_TARGET,
        }
        self._battle_cb2 = s["BattleMainCB2"] | thumb
        self._overworld_cb2 = s.nearest("CB2_Overworld", "BattleMainCB2") | thumb
        self.tables: RomTables = read_rom_tables(
            rom,
            moves_addr=s["gBattleMoves"], move_names_addr=s["gMoveNames"],
            species_info_addr=s[self.game.species_table], species_names_addr=s["gSpeciesNames"],
            type_chart_addr=s["gTypeEffectiveness"], national_addr=s[self.game.national_table],
        )

    def _u8(self, addr: int) -> int:
        return self.ram.read(addr, 1)[0]

    def _u32(self, addr: int) -> int:
        return int.from_bytes(self.ram.read(addr, 4), "little")

    def phase(self) -> Phase:
        cb2 = self._u32(self.addr["main"] + 4)
        if cb2 == self._overworld_cb2:
            return Phase.OVERWORLD
        if cb2 != self._battle_cb2:
            return Phase.UNKNOWN
        handler = self._u32(self.addr["controller_funcs"])  # battler 0 = player
        return self._handlers.get(handler, Phase.BATTLE)

    def party(self) -> list[PartyMon | None]:
        return read_party(self.ram, self.addr["player_party"])

    def enemy_party(self) -> list[PartyMon | None]:
        return read_party(self.ram, self.addr["enemy_party"])

    def battle(self) -> BattleSnapshot:
        phase = self.phase()
        if phase in (Phase.OVERWORLD, Phase.UNKNOWN):
            return BattleSnapshot(phase, None, None, 0, 0, False)
        count = min(max(self._u8(self.addr["battlers_count"]), 2), 4)
        mons = read_battle_mons(self.ram, self.addr["battle_mons"], count)
        flags = self._u32(self.addr["battle_type"])
        return BattleSnapshot(
            phase=phase,
            player=mons[0],
            opponent=mons[1],
            action_cursor=self._u8(self.addr["action_cursor"]),
            move_cursor=self._u8(self.addr["move_cursor"]),
            wild=not flags & BATTLE_TYPE_TRAINER,
        )
