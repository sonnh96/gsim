"""Headless commands: core spike checks, state inspection and unattended bot runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bot.autobot import Mode
from .gen3.model import TYPE_NAMES
from .libretro import api
from .session import GameSession


def _open(args: argparse.Namespace) -> GameSession:
    game = GameSession(args.rom, args.core, getattr(args, "system", None))
    if args.state:
        game.core.load_state(Path(args.state).read_bytes())
    return game


def cmd_spike(args: argparse.Namespace) -> int:
    """Go/no-go check: does the core expose the memory AutoBot needs?"""
    game = _open(args)
    try:
        game.core.run(args.frames)
        sysram = game.core.memory(api.MEMORY_SYSTEM_RAM)
        report = {
            "system": game.system.id,
            "core": f"{game.core.name} {game.core.version}",
            "pixel_format": game.core.pixel_format,
            "options": len(game.core.variables),
            "messages": game.core.messages[-5:],
            "fps": game.core.fps,
            "sample_rate": game.core.sample_rate,
            "frame": game.core.frame and [game.core.frame.width, game.core.frame.height],
            "system_ram_bytes": len(sysram) if sysram is not None else None,
            "save_ram_bytes": len(m) if (m := game.core.memory(api.MEMORY_SAVE_RAM)) is not None else None,
            "memory_map": [{"start": f"0x{r.start:08X}", "length": f"0x{r.length:X}", "name": r.name}
                           for r in game.core.regions],
            "state_bytes": len(game.core.save_state()),
            "gen3": game.gen3.game.title if game.gen3 else game.gen3_error,
        }
        print(json.dumps(report, indent=2))
        return 0
    finally:
        game.core.close()


def cmd_inspect(args: argparse.Namespace) -> int:
    game = _open(args)
    try:
        game.core.run(args.frames)
        if game.gen3 is None:
            print(f"not a supported Gen 3 game: {game.gen3_error}", file=sys.stderr)
            return 2
        tables = game.gen3.tables
        snap = game.gen3.battle()
        print(f"game: {game.gen3.game.title}\nphase: {snap.phase.value}")
        for label, mon in (("player", snap.player), ("opponent", snap.opponent)):
            if mon:
                types = "/".join(dict.fromkeys(TYPE_NAMES[t] for t in mon.types))
                moves = ", ".join(tables.moves[m].name for m in mon.moves if m)
                print(f"{label}: {tables.species_name(mon.species)} Lv{mon.level} HP {mon.hp}/{mon.max_hp} "
                      f"[{types}] shiny={mon.shiny} moves: {moves}")
        for i, mon in enumerate(game.gen3.party()):
            if mon:
                print(f"party[{i}]: {tables.species_name(mon.species)} Lv{mon.level} "
                      f"HP {mon.hp}/{mon.max_hp} shiny={mon.shiny} ivs={mon.ivs}")
        return 0
    finally:
        game.core.close()


def cmd_bot(args: argparse.Namespace) -> int:
    game = _open(args)
    try:
        if game.bot is None:
            print(f"AutoBot unavailable: {game.gen3_error}", file=sys.stderr)
            return 2
        game.bot.set_mode(Mode(args.mode))
        seen = 0
        for frame in range(args.frames):
            game.run_frame()
            events = list(game.bot.events)
            for line in events[seen:] if len(events) > seen else []:
                print(f"[{frame:>7}] {line}")
            seen = len(events)
            if game.bot.paused_reason:
                break
        if args.save_state:
            Path(args.save_state).write_bytes(game.core.save_state())
        print(f"stopped after {frame + 1} frames; phase={game.snapshot.phase.value if game.snapshot else '?'}"
              f"; paused={game.bot.paused_reason}")
        return 0
    finally:
        game.core.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retrodesk-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn, frames in (("spike", cmd_spike, 600), ("inspect", cmd_inspect, 1), ("bot", cmd_bot, 36000)):
        p = sub.add_parser(name)
        p.add_argument("rom", type=Path)
        p.add_argument("--core", type=Path, help="libretro core (default: chosen by ROM extension)")
        p.add_argument("--system", help="system id when the extension is ambiguous (nes, snes, psx, arcade, ...)")
        p.add_argument("--state", type=Path, help="save state to load first")
        p.add_argument("--frames", type=int, default=frames)
        p.set_defaults(fn=fn)
        if name == "bot":
            p.add_argument("--mode", choices=[m.value for m in Mode if m is not Mode.OFF], default="auto_grind")
            p.add_argument("--save-state", type=Path, help="write a state when the run ends")
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
