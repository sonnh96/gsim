"""One running game: core, battery save, save states, and the optional Gen 3 bot."""

from __future__ import annotations

from pathlib import Path

from .bot.autobot import AutoBot
from .gen3.game import BattleSnapshot, Gen3Session, Phase
from .gen3.symbols import UnsupportedRom
from .libretro import api
from .libretro.core import Core
from .frames import frame_to_rgba
from .options import OptionStore
from .states import SLOTS, StateSlots
from .paths import core_for, rom_paths
from .systems import System, missing_bios, system_for

STATE_SLOTS = SLOTS


class GameSession:
    def __init__(self, rom_path: str | Path, core_path: str | Path | None = None,
                 system: str | None = None) -> None:
        self.rom_path = Path(rom_path).resolve()
        self.system: System = system_for(self.rom_path, system)
        self.paths = rom_paths(self.rom_path)
        self.states = StateSlots(self.paths["states"])
        self._undo_state: bytes | None = None  # what was running before the last load
        core_file = Path(core_path) if core_path else core_for(self.rom_path, system)
        self.core_id = core_file.stem.removesuffix("_libretro")
        self.options = OptionStore(core_file)
        sysdir = self.paths["system"]
        self.missing_bios = missing_bios(
            self.system, [sysdir, *(sysdir / d for d in self.system.bios_subdirs), self.rom_path.parent])
        self.core = Core(core_file, self.paths["system"], self.paths["saves"],
                         options=self.options.effective(self.system))
        try:
            self.core.load_game(self.rom_path)
        except Exception:
            self.core.close()
            raise
        self._load_sram()

        self.gen3: Gen3Session | None = None
        self.bot: AutoBot | None = None
        self.gen3_error: str | None = None
        if self.system.id == "gba":
            try:
                self.gen3 = Gen3Session(self.rom_path.read_bytes(), self.core)
                self.bot = AutoBot(self.gen3.tables)
            except (UnsupportedRom, FileNotFoundError) as exc:
                self.gen3_error = str(exc)
        self.human_mask = 0           # port 0
        self.human_masks: list[int] = [0, 0]
        self.bot_mask = 0
        self.snapshot: BattleSnapshot | None = None
        self.core.input_mask = self._port_mask

    def _port_mask(self, port: int) -> int:
        if port == 0:
            return self.human_mask | self.human_masks[0] | self.bot_mask
        return self.human_masks[port] if port < len(self.human_masks) else 0

    def set_option(self, key: str, value: str) -> None:
        """Change a core option now and remember it for every game on this core."""
        self.core.set_variable(key, value)
        self.options.set(key, value)

    def run_frame(self) -> None:
        if self.gen3 is not None:
            try:
                self.snapshot = self.gen3.battle()
            except Exception as exc:  # memory map missing or mid-transition garbage
                self.snapshot = BattleSnapshot(Phase.UNKNOWN, None, None, 0, 0, False)
                self.gen3_error = f"state read failed: {exc}"
            self.bot_mask = self.bot.step(self.snapshot) if self.bot else 0
        self.core.run()

    # -- persistence -----------------------------------------------------

    def _load_sram(self) -> None:
        mem = self.core.memory(api.MEMORY_SAVE_RAM)
        path = self.paths["sram"]
        if mem is None or not path.exists():
            return
        data = path.read_bytes()[:len(mem)]
        mem[:len(data)] = data

    def save_sram(self) -> None:
        mem = self.core.memory(api.MEMORY_SAVE_RAM)
        if mem is None:
            return
        path = self.paths["sram"]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".srm.tmp")
        tmp.write_bytes(bytes(mem))
        tmp.replace(path)

    def state_path(self, slot: int) -> Path:
        return self.states.path(slot)

    def save_state(self, slot: int) -> Path:
        frame = self.core.frame
        preview = None
        if frame is not None:
            preview = frame_to_rgba(frame)
        return self.states.write(slot, self.core.save_state(), preview)

    def load_state(self, slot: int) -> None:
        data = self.states.read(slot)  # raises FileNotFoundError for an empty slot
        undo = self.core.save_state()
        self.core.load_state(data)
        self._undo_state = undo
        if self.bot:
            self.bot.clear_input()

    @property
    def can_undo_load(self) -> bool:
        return self._undo_state is not None

    def undo_load(self) -> None:
        """Go back to the moment before the last load_state."""
        if self._undo_state is None:
            return
        self.core.load_state(self._undo_state)
        self._undo_state = None
        if self.bot:
            self.bot.clear_input()

    def close(self) -> None:
        try:
            self.save_sram()
        finally:
            self.core.close()
