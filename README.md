# retrodesk

A desktop (Linux, macOS) multi-system libretro front-end in Python, with a
closed-loop **Generation 3 Pokemon AutoBot** and a **Pokedex** backed by PokeAPI
as an optional extra for GBA games.

## Systems

| System | Extensions | Core (first installed wins) | Status |
|---|---|---|---|
| NES / Famicom | .nes .fds .unf | mesen, fceumm, nestopia | runs |
| SNES | .sfc .smc .fig | snes9x, bsnes | runs |
| Game Boy / Color | .gb .gbc | gambatte, mgba, sameboy | runs |
| Game Boy Advance | .gba | mgba | runs |
| Nintendo DS | .nds .dsi | melondsds, melonds | runs; both screens, mouse = touch screen, built-in FreeBIOS |
| PlayStation | .cue .chd .pbp .m3u | pcsx_rearmed (software), swanstation | loads; untested with a disc, needs BIOS |
| Neo Geo | .zip (folder named `neogeo`) | fbneo | loads; needs `neogeo.zip` |
| Arcade | .zip | mame2003_plus, mame2010, mame | loads; needs matching ROM sets |
| PSP / 3DS / PS2 | .iso .cso / .3ds / .iso | ppsspp / citra / play | blocked: need hw_render (`fetch_assets.py --hw`) |

Ambiguous extensions (`.zip`, `.iso`, `.bin`, `.chd`) are resolved by a parent
folder name (`nes/`, `Neo Geo/`, `psp/`, ...) or `--system` on the CLI.
The table lives in `src/retrodesk/systems.py`.

The bot reads game state from emulated RAM using symbol addresses from the
[pret](https://github.com/pret) decompilations and presses one button at a time,
re-reading state after every press. It never patches the game.

## Status

| Area | State |
|---|---|
| libretro bridge (ctypes): video, audio, 2 joypads, core options v1/v2, memory maps, save states, battery saves, zip content | runs mGBA, Mesen, Snes9x, Gambatte headlessly (test ROMs); FBNeo, MAME2003+, PCSX-ReARMed, melonDS initialise |
| SDL2 + ImGui front-end: library, viewport, HUD, Pokedex, RAM viewer, hotkeys, controllers | launches and plays NES/SNES/GB/GBA on macOS |
| Touch screen (libretro pointer), core options window saved per core, BIOS check per system | runs; touch verified end-to-end on melonDS DS |
| hw_render (OpenGL), analog sticks, disk control | not started; gates PS1-hw, PSP, 3DS, PS2 |
| Gen 3 state reader (Emerald US, FireRed US 1.0, Ruby US 1.0) | tested on synthetic RAM with the real Emerald symbol table; **not yet verified on a ROM** |
| AutoBot: auto move, auto grind, shiny hunt, HP stop, stuck watchdog | tested with synthetic snapshots |
| Pokedex (PokeAPI + local cache) | tested from cache |
| NDS (Gen 4/5) bot | not started; waits on the melonDS memory spike |

Known bot limits: move-learning and "switch Pokemon?" prompts are not handled
— the bot pauses after 60 s without a battle decision. Damage scoring ignores
abilities, weather, items and crits. Double battles always use the default
target.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/fetch_assets.py   # libretro cores + pret symbol tables
```

Bring your own ROMs and BIOS files; none are included or downloaded.

## Use

```bash
.venv/bin/retrodesk path/to/emerald.gba        # or: retrodesk --library ~/roms
.venv/bin/retrodesk-cli spike game.nes          # run 600 frames headless and report core/memory info
.venv/bin/retrodesk-cli spike roms/mslug.zip --system neogeo
.venv/bin/retrodesk-cli inspect game.gba --state battle.state
.venv/bin/retrodesk-cli bot game.gba --state grass.state --mode shiny_hunt --frames 200000
```

Keys: arrows, X = A, Z = B, S = X, A = Y, Q/W = L/R, E/R = L2/R2, D/F = L3/R3,
Enter = Start, Backspace = Select. F1 side panel, F3 Pokedex, F5 core
options, P pause, Tab fast forward.

Save states: 0-9 pick a slot, F2 saves, F4 loads, F7 undoes the last load,
F6 opens a window with a picture and time for every slot. Opening a game
selects the most recently saved slot, so F4 right away continues where you
left off. SDL game controllers
work by button position (triggers = L2/R2, stick clicks = L3/R3); a second
controller drives player 2.

Nintendo DS: click or drag on the bottom screen to touch. With melonDS DS,
F (R3) cycles screen layouts; with the legacy melonDS core, R (R2) swaps
screens. Core options (F5) are saved per core in `options/<core>.json`.

BIOS files go in the `system` folder inside the data directory below; the side
panel says which ones a system is missing and whether the core can do without.

Data lives in `~/.local/share/retrodesk` (Linux) or
`~/Library/Application Support/retrodesk` (macOS).

## Tests

```bash
.venv/bin/python -m pytest -q
```

## License

GPL-3.0-or-later. Cores are separate GPL/MPL programs loaded at runtime.
Pokemon is a trademark of Nintendo/Game Freak/Creatures; this project is not
affiliated with them or with any commercial emulator app.
