"""SDL2 + Dear ImGui desktop front-end."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from pathlib import Path

import OpenGL.GL as gl
import sdl2
from imgui_bundle import imgui
from imgui_bundle.python_backends.sdl2_backend import SDL2Renderer

from ..bot.autobot import Mode
from ..bot.battle import rank_moves
from ..gen3.model import TYPE_NAMES, BattleMon
from ..paths import CORES_BY_EXTENSION
from ..pokedex.pokeapi import DexEntry, PokeApi
from ..session import GameSession
from ..systems import CONTROL_HINTS
from .input import InputState
from .layout import Rect, fit, to_pointer
from .video import FrameTexture

# Number row selects a save-state slot: 1..9 then 0, as printed on the keyboard.
SLOT_KEYS = {getattr(sdl2, f"SDL_SCANCODE_{d}"): d for d in range(10)}
PREVIEW_WIDTH = 150

SPEED_LEVELS = (1.5, 2.0, 3.0, 4.0, 8.0, 16.0)
DEFAULT_SPEED_INDEX = 1
MAX_CATCHUP_FRAMES = 4  # per 1x of speed; bounds work after a stall
MAX_AUDIO_LATENCY_S = 0.15
SRAM_FLUSH_INTERVAL_S = 30
HUD_WIDTH = 360


class Pokedex:
    """Background PokeAPI lookups so the render loop never blocks on the network."""

    def __init__(self) -> None:
        self.api = PokeApi()
        self.query = ""
        self.entry: DexEntry | None = None
        self.error: str | None = None
        self.loading = False

    def lookup(self, key: int | str) -> None:
        if self.loading or str(key).strip() == "":
            return
        self.loading, self.error = True, None

        def work() -> None:
            try:
                self.entry = self.api.entry(key)
            except Exception as exc:
                self.error = f"lookup failed: {exc}"
            finally:
                self.loading = False

        threading.Thread(target=work, daemon=True).start()


class App:
    def __init__(self, rom: Path | None, library_dir: Path | None) -> None:
        self.library_dir = library_dir or (rom.parent if rom else Path.home())
        self.library: list[Path] = []
        self.game: GameSession | None = None
        self.load_error: str | None = None
        self.input = InputState()
        self.dex = Pokedex()
        self.show_hud = True
        self.show_dex = False
        self.show_ram = False
        self.show_options = False
        self.option_filter = ""
        self.view = Rect(0, 0, 0, 0)  # where the game image was last drawn
        self.ram_addr = "02024084"
        self.fast_forward = False
        self.speed_index = DEFAULT_SPEED_INDEX
        self.paused = False
        self.slot = 0
        self.show_states = False
        self._previews: dict[int, tuple[float, FrameTexture]] = {}  # slot -> (mtime, texture)
        self.status = ""
        self._init_window()
        self.texture = FrameTexture()
        self.audio_dev = 0
        self.scan_library()
        if rom:
            self.open_game(rom)

    # -- setup -----------------------------------------------------------

    def _init_window(self) -> None:
        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_AUDIO | sdl2.SDL_INIT_GAMECONTROLLER) < 0:
            raise RuntimeError(sdl2.SDL_GetError().decode())
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DOUBLEBUFFER, 1)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_FLAGS, sdl2.SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_PROFILE_MASK, sdl2.SDL_GL_CONTEXT_PROFILE_CORE)
        self.window = sdl2.SDL_CreateWindow(b"retrodesk", sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
                                            1280, 760, sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_RESIZABLE)
        if not self.window:
            raise RuntimeError(sdl2.SDL_GetError().decode())
        self.gl_context = sdl2.SDL_GL_CreateContext(self.window)
        sdl2.SDL_GL_MakeCurrent(self.window, self.gl_context)
        sdl2.SDL_GL_SetSwapInterval(1)
        imgui.create_context()
        imgui.get_io().config_flags |= imgui.ConfigFlags_.nav_enable_keyboard.value
        self.renderer = SDL2Renderer(self.window)

    def _open_audio(self, rate: int) -> None:
        self._close_audio()
        want = sdl2.SDL_AudioSpec(rate, sdl2.AUDIO_S16LSB, 2, 1024)
        have = sdl2.SDL_AudioSpec(0, 0, 0, 0)
        self.audio_dev = sdl2.SDL_OpenAudioDevice(None, 0, want, have, 0)
        if self.audio_dev:
            sdl2.SDL_PauseAudioDevice(self.audio_dev, 0)
        self._bytes_per_second = rate * 4

    def _close_audio(self) -> None:
        if self.audio_dev:
            sdl2.SDL_CloseAudioDevice(self.audio_dev)
            self.audio_dev = 0

    # -- game lifecycle --------------------------------------------------

    def scan_library(self) -> None:
        if not self.library_dir.is_dir():
            self.library = []
            return
        self.library = sorted(p for p in self.library_dir.rglob("*")
                              if p.is_file() and p.suffix.lower() in CORES_BY_EXTENSION)

    def open_game(self, rom: Path) -> None:
        self.close_game()
        try:
            self.game = GameSession(rom)
        except Exception as exc:
            self.load_error = f"{rom.name}: {exc}"
            return
        self.load_error = None
        self._open_audio(int(self.game.core.sample_rate))
        self._next_frame_at = time.perf_counter()
        self._last_sram_flush = time.perf_counter()
        sdl2.SDL_SetWindowTitle(self.window, f"retrodesk — {rom.name} [{self.game.system.name} / {self.game.core.name}]".encode())
        latest = self.game.states.latest()
        self.slot = latest if latest is not None else 0
        if latest is not None:
            self.status = f"F4 continues from {self.game.states.info(latest).describe()}"

    def close_game(self) -> None:
        self._close_audio()
        self._drop_previews()
        if self.game is not None:
            self.game.close()
            self.game = None

    # -- main loop -------------------------------------------------------

    def run(self) -> None:
        event = sdl2.SDL_Event()
        running = True
        while running:
            while sdl2.SDL_PollEvent(ctypes.byref(event)):
                if event.type == sdl2.SDL_QUIT:
                    running = False
                elif event.type == sdl2.SDL_CONTROLLERDEVICEADDED:
                    self.input.open_controller(event.cdevice.which)
                elif event.type == sdl2.SDL_CONTROLLERDEVICEREMOVED:
                    self.input.close_controller(event.cdevice.which)
                elif event.type == sdl2.SDL_KEYDOWN and not event.key.repeat:
                    self._hotkey(event.key.keysym.scancode)
                self.renderer.process_event(event)
            self.renderer.process_inputs()
            self._emulate()
            self._draw()
        self.close_game()
        self.texture.delete()
        self.renderer.shutdown()
        sdl2.SDL_GL_DeleteContext(self.gl_context)
        sdl2.SDL_DestroyWindow(self.window)
        sdl2.SDL_Quit()

    def _hotkey(self, scancode: int) -> None:
        if scancode == sdl2.SDL_SCANCODE_F1:
            self.show_hud = not self.show_hud
        elif scancode == sdl2.SDL_SCANCODE_F2:
            self._save_state()
        elif scancode == sdl2.SDL_SCANCODE_F4:
            self._load_state()
        elif scancode == sdl2.SDL_SCANCODE_F6:
            self.show_states = not self.show_states
        elif scancode == sdl2.SDL_SCANCODE_F7:
            self._undo_load()
        elif scancode in SLOT_KEYS and not imgui.get_io().want_text_input:
            self._select_slot(SLOT_KEYS[scancode])
        elif scancode == sdl2.SDL_SCANCODE_F3:
            self.show_dex = not self.show_dex
        elif scancode == sdl2.SDL_SCANCODE_F5:
            self.show_options = not self.show_options
        elif scancode == sdl2.SDL_SCANCODE_P:
            self.paused = not self.paused
        elif scancode == sdl2.SDL_SCANCODE_TAB:
            self.fast_forward = not self.fast_forward
            self.status = f"speed {self.speed:g}x"
        elif scancode in (sdl2.SDL_SCANCODE_LEFTBRACKET, sdl2.SDL_SCANCODE_RIGHTBRACKET):
            step = 1 if scancode == sdl2.SDL_SCANCODE_RIGHTBRACKET else -1
            self.speed_index = min(max(self.speed_index + step, 0), len(SPEED_LEVELS) - 1)
            self.fast_forward = True
            self.status = f"speed {self.speed:g}x"

    @property
    def speed(self) -> float:
        return SPEED_LEVELS[self.speed_index] if self.fast_forward else 1.0

    def _select_slot(self, slot: int) -> None:
        self.slot = slot
        if self.game:
            self.status = self.game.states.info(slot).describe()

    def _save_state(self, slot: int | None = None) -> None:
        if not self.game:
            return
        self.slot = self.slot if slot is None else slot
        try:
            self.game.save_state(self.slot)
            self.status = f"saved slot {self.slot}"
        except Exception as exc:
            self.status = f"save failed: {exc}"

    def _load_state(self, slot: int | None = None) -> None:
        if not self.game:
            return
        self.slot = self.slot if slot is None else slot
        try:
            self.game.load_state(self.slot)
            self.status = f"loaded slot {self.slot} (F7 undoes)"
        except FileNotFoundError:
            self.status = f"slot {self.slot} is empty"
            return
        except Exception as exc:
            self.status = f"load failed: {exc}"
            return
        self._show_still(self.game.states.preview(self.slot))

    def _undo_load(self) -> None:
        if self.game and self.game.can_undo_load:
            self.game.undo_load()
            self.status = "back to before the last load"
            self._show_still(None)

    def _show_still(self, rgba) -> None:  # noqa: ANN001
        """While paused no frame is emulated, so show the slot's picture (or the last frame) instead."""
        if not self.paused:
            return
        if rgba is not None:
            self.texture.upload_rgba(rgba)
        elif self.game and self.game.core.frame is not None:
            self.texture.upload(self.game.core.frame)

    def _drop_previews(self) -> None:
        for _, tex in self._previews.values():
            tex.delete()
        self._previews.clear()

    def _preview_texture(self, slot: int, info) -> FrameTexture | None:  # noqa: ANN001
        if info.empty:
            return None
        stamp = info.saved_at.timestamp()
        cached = self._previews.get(slot)
        if cached and cached[0] == stamp:
            return cached[1]
        if cached:
            cached[1].delete()
            del self._previews[slot]
        rgba = self.game.states.preview(slot) if self.game else None
        if rgba is None:
            return None
        tex = FrameTexture()
        tex.upload_rgba(rgba)
        self._previews[slot] = (stamp, tex)
        return tex

    def _emulate(self) -> None:
        game = self.game
        if game is None or self.paused:
            return
        typing = imgui.get_io().want_text_input
        game.human_masks = self.input.masks(keyboard_enabled=not typing, ports=len(game.human_masks))
        self._feed_pointer(game)
        now = time.perf_counter()
        speed = self.speed
        game.core.fast_forwarding = self.fast_forward
        frame_time = 1.0 / (game.core.fps * speed)
        max_frames = int(MAX_CATCHUP_FRAMES * speed)
        frames = 0
        while self._next_frame_at <= now and frames < max_frames:
            self._next_frame_at += frame_time
            frames += 1
        if self._next_frame_at < now:  # fell too far behind; resync instead of spiralling
            self._next_frame_at = now
        for _ in range(frames):
            game.run_frame()
        audio = game.core.drain_audio()
        if self.audio_dev and audio and not self.fast_forward:
            queued = sdl2.SDL_GetQueuedAudioSize(self.audio_dev)
            if queued < self._bytes_per_second * MAX_AUDIO_LATENCY_S:
                sdl2.SDL_QueueAudio(self.audio_dev, audio, len(audio))
        if game.core.frame is not None and frames:
            self.texture.upload(game.core.frame)
        if game.core.messages:
            self.status = game.core.messages[-1]
            game.core.messages.clear()
        if game.core.shutdown_requested:
            self.close_game()
            return
        if now - self._last_sram_flush > SRAM_FLUSH_INTERVAL_S:
            game.save_sram()
            self._last_sram_flush = now

    def _feed_pointer(self, game: GameSession) -> None:
        """Mouse over the game image becomes the libretro pointer (DS touch screen)."""
        io = imgui.get_io()
        x, y, inside = to_pointer(self.view, io.mouse_pos.x, io.mouse_pos.y)
        pointer = game.core.pointer
        pointer.x, pointer.y = x, y
        pointer.pressed = inside and imgui.is_mouse_down(0) and not io.want_capture_mouse

    # -- UI --------------------------------------------------------------

    def _draw(self) -> None:
        imgui.new_frame()
        self._menu_bar()
        self._viewport()
        if self.game is None:
            self._library_window()
        elif self.show_hud:
            self._hud_window()
        if self.show_dex:
            self._dex_window()
        if self.show_ram and self.game:
            self._ram_window()
        if self.show_options and self.game:
            self._options_window()
        if self.show_states and self.game:
            self._states_window()
        w, h = ctypes.c_int(), ctypes.c_int()
        sdl2.SDL_GL_GetDrawableSize(self.window, ctypes.byref(w), ctypes.byref(h))
        gl.glViewport(0, 0, w.value, h.value)
        gl.glClearColor(0.08, 0.08, 0.1, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        self.renderer.render(imgui.get_draw_data())
        sdl2.SDL_GL_SwapWindow(self.window)

    def _menu_bar(self) -> None:
        if not imgui.begin_main_menu_bar():
            return
        if imgui.begin_menu("Game"):
            if imgui.menu_item("Library", "", False, True)[0]:
                self.close_game()
                self.scan_library()
            if imgui.menu_item("Reset", "", False, self.game is not None)[0] and self.game:
                self.game.core.reset()
            imgui.separator()
            if imgui.menu_item(f"Save state (slot {self.slot})", "F2", False, self.game is not None)[0]:
                self._save_state()
            if imgui.menu_item(f"Load state (slot {self.slot})", "F4", False, self.game is not None)[0]:
                self._load_state()
            can_undo = bool(self.game and self.game.can_undo_load)
            if imgui.menu_item("Undo load", "F7", False, can_undo)[0]:
                self._undo_load()
            if imgui.menu_item("Save states...", "F6", self.show_states, self.game is not None)[0]:
                self.show_states = not self.show_states
            if self.game and imgui.begin_menu("Slot"):
                for info in self.game.states.all():
                    label = info.describe().capitalize()
                    if imgui.menu_item(label, str(info.slot), self.slot == info.slot, True)[0]:
                        self._select_slot(info.slot)
                imgui.end_menu()
            imgui.end_menu()
        if imgui.begin_menu("View"):
            self.show_hud = imgui.menu_item("Side panel", "F1", self.show_hud, True)[1]
            self.show_options = imgui.menu_item("Core options", "F5", self.show_options, True)[1]
            self.show_dex = imgui.menu_item("Pokedex", "F3", self.show_dex, True)[1]
            self.show_ram = imgui.menu_item("RAM viewer", "", self.show_ram, True)[1]
            imgui.end_menu()
        self.paused = imgui.menu_item("Pause", "P", self.paused, True)[1]
        if imgui.begin_menu(f"Speed {self.speed:g}x"):
            self.fast_forward = imgui.menu_item("Fast forward", "Tab", self.fast_forward, True)[1]
            imgui.separator()
            for i, level in enumerate(SPEED_LEVELS):
                if imgui.menu_item(f"{level:g}x", "", self.speed_index == i, True)[0]:
                    self.speed_index, self.fast_forward = i, True
            imgui.text_disabled("[ / ] change speed")
            imgui.end_menu()
        if self.game:
            imgui.text_disabled(f"Slot {self.slot}")
        if self.status:
            imgui.text_disabled(self.status)
        imgui.end_main_menu_bar()

    def _viewport(self) -> None:
        vp = imgui.get_main_viewport()
        top = imgui.get_frame_height()
        right = HUD_WIDTH if (self.game and self.show_hud) else 0
        avail_w, avail_h = vp.size.x - right, vp.size.y - top
        if not self.game or not self.texture.width or avail_w <= 0:
            self.view = Rect(0, 0, 0, 0)
            return
        geo = self.game.core.av_info.geometry
        aspect = geo.aspect_ratio if geo.aspect_ratio > 0 else self.texture.width / self.texture.height
        v = self.view = fit(Rect(vp.pos.x, vp.pos.y + top, avail_w, avail_h), aspect)
        imgui.get_background_draw_list().add_image(
            imgui.ImTextureRef(self.texture.id), imgui.ImVec2(v.x, v.y), imgui.ImVec2(v.x + v.w, v.y + v.h))

    def _library_window(self) -> None:
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(imgui.ImVec2(vp.pos.x + 40, vp.pos.y + 60), imgui.Cond_.first_use_ever)
        imgui.set_next_window_size(imgui.ImVec2(600, 500), imgui.Cond_.first_use_ever)
        imgui.begin("Library")
        changed, text = imgui.input_text("Folder", str(self.library_dir))
        if changed:
            self.library_dir = Path(text).expanduser()
        imgui.same_line()
        if imgui.button("Scan"):
            self.scan_library()
        if self.load_error:
            imgui.text_colored(imgui.ImVec4(1, 0.4, 0.4, 1), self.load_error)
        if not self.library:
            imgui.text_disabled("No ROM files found (" + " ".join(sorted(CORES_BY_EXTENSION)) + ").")
        for rom in self.library:
            if imgui.selectable(str(rom.relative_to(self.library_dir)), False)[0]:
                self.open_game(rom)
        imgui.end()

    def _hud_window(self) -> None:
        game = self.game
        assert game is not None
        vp = imgui.get_main_viewport()
        top = imgui.get_frame_height()
        imgui.set_next_window_pos(imgui.ImVec2(vp.pos.x + vp.size.x - HUD_WIDTH, vp.pos.y + top))
        imgui.set_next_window_size(imgui.ImVec2(HUD_WIDTH, vp.size.y - top))
        imgui.begin("Game", None, imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_resize
                    | imgui.WindowFlags_.no_collapse)
        self._game_info(game)
        if game.gen3 is None:
            if game.system.id == "gba":
                imgui.text_wrapped(f"AutoBot unavailable: {game.gen3_error or 'not a Gen 3 game'}")
            imgui.end()
            return
        imgui.separator_text("AutoBot")
        bot, tables, snap = game.bot, game.gen3.tables, game.snapshot
        assert bot is not None
        imgui.text(game.gen3.game.title)
        if game.gen3_error:
            imgui.text_colored(imgui.ImVec4(1, 0.6, 0.3, 1), game.gen3_error)
        imgui.separator_text("Mode")
        for mode, label in [(Mode.OFF, "Off"), (Mode.AUTO_MOVE, "Auto move"),
                            (Mode.AUTO_GRIND, "Auto grind"), (Mode.SHINY_HUNT, "Shiny hunt")]:
            if imgui.radio_button(label, bot.config.mode is mode):
                bot.set_mode(mode)
            imgui.same_line()
        imgui.new_line()
        if bot.paused_reason:
            imgui.text_colored(imgui.ImVec4(1, 0.8, 0.2, 1), f"Paused: {bot.paused_reason}")
            if imgui.button("Resume"):
                bot.resume()
        _, bot.config.stop_below_hp_percent = imgui.slider_int("Stop below HP %", bot.config.stop_below_hp_percent, 0, 90)
        if imgui.radio_button("Walk left/right", bot.config.walk_axis == "horizontal"):
            bot.config.walk_axis = "horizontal"
        imgui.same_line()
        if imgui.radio_button("Walk up/down", bot.config.walk_axis == "vertical"):
            bot.config.walk_axis = "vertical"

        imgui.separator_text("Battle")
        if snap is None:
            imgui.end()
            return
        imgui.text(f"Phase: {snap.phase.value}{'  (wild)' if snap.player and snap.wild else ''}")
        if snap.player and snap.opponent:
            self._mon_line("You", snap.player, tables)
            self._mon_line("Foe", snap.opponent, tables)
            if imgui.small_button("Open foe in Pokedex"):
                self.show_dex = True
                self.dex.lookup(tables.national_dex[snap.opponent.species])
            imgui.separator_text("Moves")
            ranked = {s.slot: s for s in rank_moves(snap.player, snap.opponent, tables)}
            for slot, move_id in enumerate(snap.player.moves):
                if move_id == 0:
                    continue
                move = tables.moves[move_id]
                score = ranked.get(slot)
                hint = f"x{score.effectiveness:g} ~{score.expected_damage:.0f}" if score else "no PP"
                allowed = slot in bot.config.allowed_slots
                changed, allowed = imgui.checkbox(f"{move.name} [{TYPE_NAMES[move.type]}] {hint}##m{slot}", allowed)
                if changed:
                    (bot.config.allowed_slots.add if allowed else bot.config.allowed_slots.discard)(slot)
        if bot.last_choice:
            imgui.text_wrapped(f"Last: {bot.last_choice}")
        imgui.separator_text("Party")
        try:
            for mon in game.gen3.party():
                if mon:
                    star = " *shiny*" if mon.shiny else ""
                    imgui.text(f"{mon.nickname or tables.species_name(mon.species)} Lv{mon.level} "
                               f"{mon.hp}/{mon.max_hp}{star}")
        except Exception as exc:
            imgui.text_disabled(f"party unreadable: {exc}")
        imgui.separator_text("Log")
        for line in list(bot.events)[-8:]:
            imgui.text_wrapped(line)
        imgui.end()

    def _game_info(self, game: GameSession) -> None:
        sysdef, core = game.system, game.core
        imgui.text(sysdef.name)
        imgui.text_disabled(f"{core.name} {core.version}")
        frame = core.frame
        if frame:
            imgui.text_disabled(f"{frame.width}x{frame.height} @ {core.fps:.2f} fps")
        if sysdef.bios:
            if game.missing_bios:
                color = imgui.ImVec4(1, 0.4, 0.4, 1) if sysdef.bios_required else imgui.ImVec4(1, 0.8, 0.3, 1)
                label = "BIOS missing" if sysdef.bios_required else "BIOS (optional) missing"
                imgui.text_colored(color, f"{label}: {', '.join(game.missing_bios)}")
                imgui.text_wrapped(f"Put it in {game.paths['system']}")
            else:
                imgui.text_colored(imgui.ImVec4(0.4, 1, 0.5, 1), "BIOS found")
        if sysdef.notes:
            imgui.text_wrapped(sysdef.notes)
        hint = CONTROL_HINTS.get(game.core_id)
        if hint:
            imgui.text_wrapped(hint)
        if imgui.button("Core options (F5)"):
            self.show_options = True

    def _states_window(self) -> None:
        game = self.game
        assert game is not None
        imgui.set_next_window_size(imgui.ImVec2(5 * (PREVIEW_WIDTH + 16) + 16, 0), imgui.Cond_.first_use_ever)
        opened, self.show_states = imgui.begin("Save states", self.show_states)
        if opened:
            imgui.text_disabled("Keys 0-9 pick a slot, F2 saves, F4 loads, F7 undoes a load. "
                                "Double-click a picture to load it.")
            frame = game.core.frame
            aspect = (frame.width / frame.height) if frame else 1.5
            geo = game.core.av_info.geometry
            if geo.aspect_ratio > 0:
                aspect = geo.aspect_ratio
            size = imgui.ImVec2(PREVIEW_WIDTH, PREVIEW_WIDTH / aspect)
            if imgui.begin_table("slots", 5):
                for info in game.states.all():
                    imgui.table_next_column()
                    slot = info.slot
                    selected = slot == self.slot
                    if selected:
                        imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.9, 0.6, 0.1, 1))
                    tex = self._preview_texture(slot, info)
                    if tex is not None:
                        clicked = imgui.image_button(f"slot{slot}", imgui.ImTextureRef(tex.id), size)
                    else:
                        clicked = imgui.button(f"{'Empty' if info.empty else 'No picture'}##slot{slot}",
                                               imgui.ImVec2(size.x + 8, size.y + 8))
                    if selected:
                        imgui.pop_style_color()
                    if clicked:
                        self._select_slot(slot)
                    if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0) and not info.empty:
                        self._load_state(slot)
                    imgui.text(f"{slot}  " + ("empty" if info.empty else f"{info.saved_at:%d/%m %H:%M}"))
                    if imgui.small_button(f"Save##s{slot}"):
                        self._save_state(slot)
                    if not info.empty:
                        imgui.same_line()
                        if imgui.small_button(f"Load##l{slot}"):
                            self._load_state(slot)
                imgui.end_table()
            if game.can_undo_load and imgui.button("Undo last load (F7)"):
                self._undo_load()
        imgui.end()

    def _options_window(self) -> None:
        game = self.game
        assert game is not None
        imgui.set_next_window_size(imgui.ImVec2(520, 480), imgui.Cond_.first_use_ever)
        opened, self.show_options = imgui.begin(f"Core options: {game.core.name}", self.show_options)
        if opened:
            _, self.option_filter = imgui.input_text("Filter", self.option_filter)
            needle = self.option_filter.lower()
            imgui.text_disabled(f"Saved to {game.options.path}")
            for key, value in game.core.variables.items():
                desc = game.core.option_descriptions.get(key, key)
                if needle and needle not in key.lower() and needle not in desc.lower():
                    continue
                choices = game.core.variable_choices(key)
                if imgui.begin_combo(f"{desc}##{key}", value):
                    for choice in choices:
                        if imgui.selectable(choice, choice == value)[0] and choice != value:
                            game.set_option(key, choice)
                    imgui.end_combo()
                if imgui.is_item_hovered():
                    imgui.set_tooltip(key)
        imgui.end()

    @staticmethod
    def _mon_line(label: str, mon: BattleMon, tables) -> None:  # noqa: ANN001
        types = "/".join(dict.fromkeys(TYPE_NAMES[t] for t in mon.types))
        star = " *shiny*" if mon.shiny else ""
        imgui.text(f"{label}: {tables.species_name(mon.species)} Lv{mon.level} {mon.hp}/{mon.max_hp} [{types}]{star}")

    def _dex_window(self) -> None:
        imgui.set_next_window_size(imgui.ImVec2(420, 420), imgui.Cond_.first_use_ever)
        opened, self.show_dex = imgui.begin("Pokedex", self.show_dex)
        if opened:
            entered, self.dex.query = imgui.input_text("Name or #", self.dex.query,
                                                       imgui.InputTextFlags_.enter_returns_true)
            imgui.same_line()
            if imgui.button("Search") or entered:
                self.dex.lookup(self.dex.query)
            if self.dex.loading:
                imgui.text_disabled("Loading…")
            if self.dex.error:
                imgui.text_colored(imgui.ImVec4(1, 0.4, 0.4, 1), self.dex.error)
            e = self.dex.entry
            if e:
                imgui.separator_text(f"#{e.id:03d} {e.name.title()}")
                imgui.text(f"Type: {' / '.join(t.title() for t in e.types)}")
                imgui.text(f"Abilities: {', '.join(e.abilities)}")
                imgui.text(f"Height {e.height_dm / 10:g} m   Weight {e.weight_hg / 10:g} kg")
                for stat, value in e.stats.items():
                    imgui.progress_bar(value / 255, imgui.ImVec2(160, 0), str(value))
                    imgui.same_line()
                    imgui.text(stat)
                imgui.text_wrapped(e.flavor)
            imgui.text_disabled("Data: PokeAPI (cached locally)")
        imgui.end()

    def _ram_window(self) -> None:
        game = self.game
        assert game is not None
        imgui.set_next_window_size(imgui.ImVec2(560, 360), imgui.Cond_.first_use_ever)
        opened, self.show_ram = imgui.begin("RAM viewer", self.show_ram)
        if opened:
            _, self.ram_addr = imgui.input_text("Address (hex)", self.ram_addr)
            try:
                base = int(self.ram_addr, 16) & ~0xF
                data = game.core.read(base, 256)
                for row in range(16):
                    chunk = data[row * 16:(row + 1) * 16]
                    imgui.text(f"{base + row * 16:08X}  {chunk.hex(' ')}")
            except Exception as exc:
                imgui.text_disabled(str(exc))
            if game.core.regions:
                imgui.separator_text("Memory map")
                for r in game.core.regions:
                    imgui.text(f"{r.start:08X} +{r.length:X} {r.name}")
        imgui.end()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="retrodesk", description="multi-system libretro front-end")
    parser.add_argument("rom", nargs="?", type=Path, help="ROM to start immediately")
    parser.add_argument("--library", type=Path, help="folder scanned for ROMs")
    args = parser.parse_args(argv)
    App(args.rom, args.library).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
