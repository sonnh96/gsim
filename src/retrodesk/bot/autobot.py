"""Closed-loop Generation 3 bot: reads game state each frame, taps one button at a time."""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field

from ..gen3.game import BattleSnapshot, Phase
from ..gen3.model import RomTables
from ..libretro.api import JOYPAD
from .battle import rank_moves

HOLD_FRAMES = 3
RELEASE_FRAMES = 3
TEXT_TAP_INTERVAL = 20
STUCK_FRAMES = 60 * 60  # a minute without a player decision


class Mode(enum.Enum):
    OFF = "off"
    AUTO_MOVE = "auto_move"     # pick the best move whenever the player must act
    AUTO_GRIND = "auto_grind"   # walk to trigger encounters and win them
    SHINY_HUNT = "shiny_hunt"   # walk, flee non-shiny wild Pokemon, stop on a shiny


@dataclass
class BotConfig:
    mode: Mode = Mode.OFF
    allowed_slots: set[int] = field(default_factory=lambda: {0, 1, 2, 3})
    stop_below_hp_percent: int = 25
    walk_axis: str = "horizontal"  # or "vertical"
    walk_steps: int = 16           # frames per direction while walking


def _mask(*buttons: str) -> int:
    m = 0
    for b in buttons:
        m |= 1 << JOYPAD[b]
    return m


def _grid_step(cursor: int, target: int) -> str | None:
    """Direction that moves a 2x2 battle menu cursor toward `target`."""
    cx, cy, tx, ty = cursor & 1, cursor >> 1, target & 1, target >> 1
    if cy != ty:
        return "DOWN" if ty > cy else "UP"
    if cx != tx:
        return "RIGHT" if tx > cx else "LEFT"
    return None


ACTION_FIGHT = 0
ACTION_RUN = 3


class AutoBot:
    def __init__(self, tables: RomTables, config: BotConfig | None = None) -> None:
        self.tables = tables
        self.config = config or BotConfig()
        self._queue: deque[int] = deque()
        self._idle_frames = 0
        self._walk_frame = 0
        self.paused_reason: str | None = None
        self.events: deque[str] = deque(maxlen=50)
        self.last_choice: str | None = None

    @property
    def active(self) -> bool:
        return self.config.mode is not Mode.OFF and self.paused_reason is None

    def set_mode(self, mode: Mode) -> None:
        self.config.mode = mode
        self.resume()

    def resume(self) -> None:
        self.paused_reason = None
        self.clear_input()

    def clear_input(self) -> None:
        """Drop queued presses, e.g. after the game state jumped (state load)."""
        self._queue.clear()
        self._idle_frames = 0

    def _pause(self, reason: str) -> None:
        self.paused_reason = reason
        self._queue.clear()
        self.events.append(f"paused: {reason}")

    def _tap(self, *buttons: str) -> None:
        self._queue.extend([_mask(*buttons)] * HOLD_FRAMES + [0] * RELEASE_FRAMES)

    def step(self, snap: BattleSnapshot) -> int:
        """Advance one frame; returns the joypad mask the bot is holding."""
        if not self.active:
            return 0
        if self._queue:
            return self._queue.popleft()
        self._decide(snap)
        return self._queue.popleft() if self._queue else 0

    def _decide(self, snap: BattleSnapshot) -> None:
        mode = self.config.mode
        if snap.phase in (Phase.CHOOSE_ACTION, Phase.CHOOSE_MOVE, Phase.CHOOSE_TARGET):
            self._idle_frames = 0
        else:
            self._idle_frames += 1
            if snap.phase is Phase.BATTLE and self._idle_frames > STUCK_FRAMES:
                self._pause("no battle decision for 60s (move learning or switch prompt?)")
                return

        if snap.phase is Phase.CHOOSE_ACTION:
            self._choose_action(snap)
        elif snap.phase is Phase.CHOOSE_MOVE:
            self._choose_move(snap)
        elif snap.phase is Phase.CHOOSE_TARGET:
            self._tap("A")
        elif snap.phase is Phase.BATTLE:
            if mode is not Mode.AUTO_MOVE and self._idle_frames % TEXT_TAP_INTERVAL == 1:
                self._tap("B")  # advance battle text; B never confirms a menu
        elif snap.phase is Phase.OVERWORLD and mode in (Mode.AUTO_GRIND, Mode.SHINY_HUNT):
            self._walk()

    def _choose_action(self, snap: BattleSnapshot) -> None:
        player, opponent = snap.player, snap.opponent
        if player is None or opponent is None:
            return
        if self.config.mode is Mode.SHINY_HUNT and snap.wild:
            if opponent.shiny:
                name = self.tables.species_name(opponent.species)
                self._pause(f"shiny {name} found")
                return
            self._select(snap.action_cursor, ACTION_RUN)
            return
        if player.max_hp and player.hp * 100 < player.max_hp * self.config.stop_below_hp_percent:
            self._pause(f"{player.nickname} HP below {self.config.stop_below_hp_percent}%")
            return
        if not rank_moves(player, opponent, self.tables, self.config.allowed_slots):
            self._pause("no usable move in the selected slots")
            return
        self._select(snap.action_cursor, ACTION_FIGHT)

    def _choose_move(self, snap: BattleSnapshot) -> None:
        if snap.player is None or snap.opponent is None:
            return
        ranked = rank_moves(snap.player, snap.opponent, self.tables, self.config.allowed_slots)
        if not ranked:
            self._tap("B")  # back to the action menu, which pauses the bot
            return
        best = ranked[0]
        if snap.move_cursor == best.slot:
            self.last_choice = f"{best.name} (x{best.effectiveness:g}, ~{best.expected_damage:.0f} dmg)"
            self.events.append(f"use {self.last_choice}")
        self._select(snap.move_cursor, best.slot)

    def _select(self, cursor: int, target: int) -> None:
        direction = _grid_step(cursor, target)
        self._tap(direction) if direction else self._tap("A")

    def _walk(self) -> None:
        a, b = ("LEFT", "RIGHT") if self.config.walk_axis == "horizontal" else ("UP", "DOWN")
        direction = a if (self._walk_frame // self.config.walk_steps) % 2 == 0 else b
        self._walk_frame += 1
        self._queue.append(_mask(direction))
