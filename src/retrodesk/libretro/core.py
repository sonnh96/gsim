"""A single loaded libretro core driven from Python."""

from __future__ import annotations

import ctypes as C
import io
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import api


MAX_MESSAGES = 16


class CoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class Region:
    """One memory descriptor published through RETRO_ENVIRONMENT_SET_MEMORY_MAPS."""

    start: int
    length: int
    select: int
    disconnect: int
    ptr: int
    offset: int
    name: str

    def matches(self, addr: int) -> bool:
        if self.select:
            return ((addr ^ self.start) & self.select) == 0
        return self.start <= addr < self.start + self.length

    def host_address(self, addr: int) -> int:
        rel = _reduce((addr - self.start) & ~self.select if self.select else addr - self.start, self.disconnect)
        if self.length:
            rel %= self.length
        return self.ptr + self.offset + rel


def _reduce(addr: int, mask: int) -> int:
    # Same bit-compaction rule RetroArch applies to `disconnect` masks.
    while mask:
        tmp = (mask - 1) & ~mask
        addr = (addr & tmp) | ((addr >> 1) & ~tmp)
        mask = (mask & (mask - 1)) >> 1
    return addr


@dataclass
class PointerState:
    """Absolute pointer (touch screen) in libretro units: -0x7fff..0x7fff across the frame."""

    x: int = 0
    y: int = 0
    pressed: bool = False


@dataclass
class Frame:
    data: bytes
    width: int
    height: int
    pitch: int
    pixel_format: int


class Core:
    """Owns one dlopen()ed libretro core and the game loaded into it.

    libretro cores keep global state, so a process should drive one Core per
    shared library at a time.
    """

    def __init__(self, core_path: str | Path, system_dir: str | Path, save_dir: str | Path,
                 options: dict[str, str] | None = None) -> None:
        self.path = Path(core_path)
        self._lib = C.CDLL(str(self.path.resolve()))
        api.declare(self._lib)
        if self._lib.retro_api_version() != api.API_VERSION:
            raise CoreError(f"{self.path.name}: unsupported libretro API version")

        Path(system_dir).mkdir(parents=True, exist_ok=True)
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        # Strings handed to the core point into these bytes objects, which must
        # stay alive (and unchanged) for as long as the core may read them.
        self._system_dir = str(Path(system_dir).resolve()).encode()
        self._save_dir = str(Path(save_dir).resolve()).encode()
        self._option_overrides = dict(options or {})
        self._variables: dict[str, str] = {}
        self._variable_choices: dict[str, list[str]] = {}
        self._variable_buffers: dict[str, bytes] = {}
        self._variables_dirty = False

        self.pixel_format = api.PIXEL_0RGB1555
        self.regions: list[Region] = []
        self.frame: Frame | None = None
        self.frame_count = 0
        self._audio: list[bytes] = []
        self.input_mask: Callable[[int], int] = lambda port: 0
        self.pointer = PointerState()
        self.messages: list[str] = []          # on-screen messages from the core
        self.shutdown_requested = False
        self.fast_forwarding = False
        self.option_descriptions: dict[str, str] = {}
        self._game_buffer: C.Array | None = None
        self._game_loaded = False

        # Keep every callback object alive for as long as the core may call it.
        self._cb_env = api.EnvironmentCb(self._environment)
        self._cb_video = api.VideoRefreshCb(self._video_refresh)
        self._cb_sample = api.AudioSampleCb(self._audio_sample)
        self._cb_batch = api.AudioSampleBatchCb(self._audio_batch)
        self._cb_poll = api.InputPollCb(lambda: None)
        self._cb_state = api.InputStateCb(self._input_state)

        self._lib.retro_set_environment(self._cb_env)
        self._lib.retro_init()
        self._lib.retro_set_video_refresh(self._cb_video)
        self._lib.retro_set_audio_sample(self._cb_sample)
        self._lib.retro_set_audio_sample_batch(self._cb_batch)
        self._lib.retro_set_input_poll(self._cb_poll)
        self._lib.retro_set_input_state(self._cb_state)

        info = api.SystemInfo()
        self._lib.retro_get_system_info(C.byref(info))
        self.name = (info.library_name or b"").decode()
        self.version = (info.library_version or b"").decode()
        self.extensions = (info.valid_extensions or b"").decode()
        self.need_fullpath = bool(info.need_fullpath)
        self.block_extract = bool(info.block_extract)
        self.av_info = api.SystemAvInfo()

    # -- lifecycle -------------------------------------------------------

    def load_game(self, rom_path: str | Path) -> None:
        rom = Path(rom_path).resolve()
        info = api.GameInfo(path=str(rom).encode(), data=None, size=0, meta=None)
        if not self.need_fullpath:
            data = self._read_content(rom)
            self._game_buffer = C.create_string_buffer(data, len(data))
            info.data = C.cast(self._game_buffer, C.c_void_p)
            info.size = len(data)
        if not self._lib.retro_load_game(C.byref(info)):
            raise CoreError(f"{self.name} rejected {rom.name}")
        self._game_loaded = True
        for port in range(api.MAX_PORTS):
            self._lib.retro_set_controller_port_device(port, api.DEVICE_JOYPAD)
        self._lib.retro_get_system_av_info(C.byref(self.av_info))

    def _read_content(self, rom: Path) -> bytes:
        """ROM bytes for cores that take content in memory, unpacking a zip when allowed."""
        if rom.suffix.lower() == ".zip" and not self.block_extract and zipfile.is_zipfile(rom):
            wanted = {e.lower() for e in self.extensions.split("|") if e and e != "zip"}
            with zipfile.ZipFile(rom) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                pick = next((n for n in names if n.rsplit(".", 1)[-1].lower() in wanted), None) or (names or [None])[0]
                if pick is None:
                    raise CoreError(f"{rom.name} is an empty archive")
                return zf.read(pick)
        return rom.read_bytes()

    def close(self) -> None:
        if self._game_loaded:
            self._lib.retro_unload_game()
            self._game_loaded = False
        if self._lib is not None:
            self._lib.retro_deinit()
            self._lib = None

    def __enter__(self) -> "Core":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def fps(self) -> float:
        return self.av_info.timing.fps or 60.0

    @property
    def sample_rate(self) -> float:
        return self.av_info.timing.sample_rate or 32768.0

    def run(self, frames: int = 1) -> None:
        for _ in range(frames):
            self._lib.retro_run()
            self.frame_count += 1

    def reset(self) -> None:
        self._lib.retro_reset()

    def drain_audio(self) -> bytes:
        out = b"".join(self._audio)
        self._audio.clear()
        return out

    # -- save states -----------------------------------------------------

    def save_state(self) -> bytes:
        size = self._lib.retro_serialize_size()
        buf = C.create_string_buffer(size)
        if not self._lib.retro_serialize(buf, size):
            raise CoreError("retro_serialize failed")
        return buf.raw

    def load_state(self, data: bytes) -> None:
        buf = C.create_string_buffer(data, len(data))
        if not self._lib.retro_unserialize(buf, len(data)):
            raise CoreError("retro_unserialize failed")

    # -- memory ----------------------------------------------------------

    def memory(self, kind: int) -> memoryview | None:
        ptr = self._lib.retro_get_memory_data(kind)
        size = self._lib.retro_get_memory_size(kind)
        if not ptr or not size:
            return None
        return memoryview((C.c_ubyte * size).from_address(ptr)).cast("B")

    def read(self, addr: int, size: int) -> bytes:
        """Read guest memory at a system address using the core's memory map."""
        for region in self.regions:
            if region.matches(addr) and region.matches(addr + size - 1):
                return C.string_at(region.host_address(addr), size)
        raise CoreError(f"address 0x{addr:08X} is not mapped by {self.name}")

    def u8(self, addr: int) -> int:
        return self.read(addr, 1)[0]

    def u16(self, addr: int) -> int:
        return struct.unpack("<H", self.read(addr, 2))[0]

    def u32(self, addr: int) -> int:
        return struct.unpack("<I", self.read(addr, 4))[0]

    # -- options ---------------------------------------------------------

    @property
    def variables(self) -> dict[str, str]:
        return dict(self._variables)

    def variable_choices(self, key: str) -> list[str]:
        return list(self._variable_choices.get(key, []))

    def set_variable(self, key: str, value: str) -> None:
        if key not in self._variables:
            raise KeyError(key)
        self._variables[key] = value
        self._variables_dirty = True

    # -- callbacks -------------------------------------------------------

    def _environment(self, cmd: int, data: int) -> bool:
        try:
            return self._handle_environment(cmd, data)
        except Exception:  # an exception must never unwind into C
            return False

    def _handle_environment(self, cmd: int, data: int) -> bool:
        if cmd == api.ENV_GET_CAN_DUPE:
            C.cast(data, C.POINTER(C.c_bool))[0] = True
            return True
        if cmd == api.ENV_SET_PIXEL_FORMAT:
            fmt = C.cast(data, C.POINTER(C.c_int))[0]
            if fmt not in (api.PIXEL_0RGB1555, api.PIXEL_XRGB8888, api.PIXEL_RGB565):
                return False
            self.pixel_format = fmt
            return True
        if cmd == api.ENV_GET_SYSTEM_DIRECTORY:
            C.cast(data, C.POINTER(C.c_char_p))[0] = self._system_dir
            return True
        if cmd == api.ENV_GET_SAVE_DIRECTORY:
            C.cast(data, C.POINTER(C.c_char_p))[0] = self._save_dir
            return True
        if cmd == api.ENV_SET_VARIABLES:
            self._register_variables(C.cast(data, C.POINTER(api.Variable)))
            return True
        if cmd == api.ENV_GET_VARIABLE:
            var = C.cast(data, C.POINTER(api.Variable))[0]
            key = (var.key or b"").decode()
            if key not in self._variables:
                return False
            value = self._variables[key].encode()
            if self._variable_buffers.get(key) != value:
                self._variable_buffers[key] = value
            C.cast(data, C.POINTER(api.Variable))[0].value = self._variable_buffers[key]
            return True
        if cmd == api.ENV_GET_VARIABLE_UPDATE:
            C.cast(data, C.POINTER(C.c_bool))[0] = self._variables_dirty
            self._variables_dirty = False
            return True
        if cmd == api.ENV_SET_MEMORY_MAPS:
            self._register_memory_map(C.cast(data, C.POINTER(api.MemoryMap))[0])
            return True
        if cmd == api.ENV_GET_INPUT_BITMASKS:
            return True
        if cmd == api.ENV_GET_CORE_OPTIONS_VERSION:
            C.cast(data, C.POINTER(C.c_uint))[0] = 2
            return True
        if cmd == api.ENV_SET_CORE_OPTIONS:
            self._register_options_v1(C.cast(data, C.POINTER(api.CoreOptionDefinition)))
            return True
        if cmd == api.ENV_SET_CORE_OPTIONS_INTL:
            self._register_options_v1(C.cast(data, C.POINTER(api.CoreOptionsIntl))[0].us)
            return True
        if cmd == api.ENV_SET_CORE_OPTIONS_V2:
            self._register_options_v2(C.cast(data, C.POINTER(api.CoreOptionsV2))[0])
            return True
        if cmd == api.ENV_SET_CORE_OPTIONS_V2_INTL:
            self._register_options_v2(C.cast(data, C.POINTER(api.CoreOptionsV2Intl))[0].us[0])
            return True
        if cmd == api.ENV_SET_VARIABLE:
            if not data:
                return True  # capability query
            var = C.cast(data, C.POINTER(api.Variable))[0]
            key = (var.key or b"").decode()
            if key in self._variables:
                self._variables[key] = (var.value or b"").decode()
            return True
        if cmd == api.ENV_SET_MESSAGE:
            self._push_message(C.cast(data, C.POINTER(api.Message))[0].msg)
            return True
        if cmd == api.ENV_GET_MESSAGE_INTERFACE_VERSION:
            C.cast(data, C.POINTER(C.c_uint))[0] = 1
            return True
        if cmd == api.ENV_SET_MESSAGE_EXT:
            self._push_message(C.cast(data, C.POINTER(api.MessageExt))[0].msg)
            return True
        if cmd == api.ENV_SHUTDOWN:
            self.shutdown_requested = True
            return True
        if cmd == api.ENV_GET_CORE_ASSETS_DIRECTORY:
            C.cast(data, C.POINTER(C.c_char_p))[0] = self._system_dir
            return True
        if cmd == api.ENV_GET_INPUT_MAX_USERS:
            C.cast(data, C.POINTER(C.c_uint))[0] = api.MAX_PORTS
            return True
        if cmd == api.ENV_GET_INPUT_DEVICE_CAPABILITIES:
            C.cast(data, C.POINTER(C.c_uint64))[0] = (1 << api.DEVICE_JOYPAD) | (1 << api.DEVICE_POINTER)
            return True
        if cmd == api.ENV_GET_FASTFORWARDING:
            C.cast(data, C.POINTER(C.c_bool))[0] = self.fast_forwarding
            return True
        if cmd == api.ENV_GET_USERNAME:
            C.cast(data, C.POINTER(C.c_char_p))[0] = b"retrodesk"
            return True
        if cmd in (api.ENV_SET_CORE_OPTIONS_DISPLAY, api.ENV_SET_SUBSYSTEM_INFO,
                   api.ENV_SET_SERIALIZATION_QUIRKS, api.ENV_SET_CONTENT_INFO_OVERRIDE,
                   api.ENV_SET_MINIMUM_AUDIO_LATENCY):
            return True
        # SET_HW_RENDER is refused on purpose (phase 3); cores with a software
        # renderer fall back to it. Disk control, VFS, perf and rumble are
        # refused too, which cores must tolerate.
        if cmd == api.ENV_GET_AUDIO_VIDEO_ENABLE:
            if data:
                C.cast(data, C.POINTER(C.c_int))[0] = 3
            return True
        if cmd == api.ENV_SET_SYSTEM_AV_INFO:
            C.memmove(C.byref(self.av_info), data, C.sizeof(api.SystemAvInfo))
            return True
        if cmd == api.ENV_SET_GEOMETRY:
            C.memmove(C.byref(self.av_info.geometry), data, C.sizeof(api.GameGeometry))
            return True
        if cmd == api.ENV_GET_LANGUAGE:
            C.cast(data, C.POINTER(C.c_uint))[0] = 0  # English
            return True
        if cmd in (api.ENV_SET_INPUT_DESCRIPTORS, api.ENV_SET_CONTROLLER_INFO,
                   api.ENV_SET_PERFORMANCE_LEVEL, api.ENV_SET_SUPPORT_NO_GAME):
            return True
        # GET_LOG_INTERFACE is unsupported on purpose: its callback is
        # variadic, which ctypes cannot receive. Cores fall back to stderr.
        return False

    def _push_message(self, raw: bytes | None) -> None:
        self.messages.append((raw or b"").decode(errors="replace"))
        del self.messages[:-MAX_MESSAGES]  # some cores post one every frame

    def _register_variables(self, vars_ptr: C.POINTER(api.Variable)) -> None:
        i = 0
        while vars_ptr[i].key:
            key = vars_ptr[i].key.decode()
            spec = (vars_ptr[i].value or b"").decode()
            desc, _, opts = spec.partition("; ")
            self._set_option(key, [o for o in opts.split("|") if o], None, desc)
            i += 1

    def _set_option(self, key: str, choices: list[str], default: str | None, desc: str | None) -> None:
        choices = choices or [""]
        self._variable_choices[key] = choices
        override = self._option_overrides.get(key)
        if override in choices:
            self._variables[key] = override
        elif default in choices:
            self._variables[key] = default
        else:
            self._variables[key] = choices[0]
        if desc:
            self.option_descriptions[key] = desc

    @staticmethod
    def _values(values: C.Array) -> list[str]:
        out = []
        for v in values:
            if not v.value:
                break
            out.append(v.value.decode())
        return out

    def _register_options_v1(self, defs: C.POINTER(api.CoreOptionDefinition)) -> None:
        i = 0
        while defs[i].key:
            d = defs[i]
            self._set_option(d.key.decode(), self._values(d.values),
                             d.default_value.decode() if d.default_value else None,
                             d.desc.decode() if d.desc else None)
            i += 1

    def _register_options_v2(self, opts: api.CoreOptionsV2) -> None:
        defs = opts.definitions
        i = 0
        while defs[i].key:
            d = defs[i]
            self._set_option(d.key.decode(), self._values(d.values),
                             d.default_value.decode() if d.default_value else None,
                             d.desc.decode() if d.desc else None)
            i += 1

    def _register_memory_map(self, mmap: api.MemoryMap) -> None:
        regions = []
        for i in range(mmap.num_descriptors):
            d = mmap.descriptors[i]
            if not d.ptr:
                continue
            regions.append(Region(
                start=d.start, length=d.len, select=d.select, disconnect=d.disconnect,
                ptr=d.ptr, offset=d.offset, name=(d.addrspace or b"").decode(),
            ))
        self.regions = regions

    def _video_refresh(self, data: int, width: int, height: int, pitch: int) -> None:
        if not data:
            return  # duplicate of the previous frame
        self.frame = Frame(C.string_at(data, pitch * height), width, height, pitch, self.pixel_format)

    def _audio_sample(self, left: int, right: int) -> None:
        self._audio.append(struct.pack("<hh", left, right))

    def _audio_batch(self, data: C.POINTER(C.c_int16), frames: int) -> int:
        self._audio.append(C.string_at(data, frames * 4))
        return frames

    def _input_state(self, port: int, device: int, index: int, ident: int) -> int:
        device &= api.DEVICE_TYPE_MASK
        if device == api.DEVICE_POINTER:
            return self._pointer_state(port, index, ident)
        if device != api.DEVICE_JOYPAD or index != 0 or port >= api.MAX_PORTS:
            return 0
        mask = self.input_mask(port)
        if ident == api.DEVICE_ID_JOYPAD_MASK:
            return mask & 0xFFFF
        return (mask >> ident) & 1

    def _pointer_state(self, port: int, index: int, ident: int) -> int:
        p = self.pointer
        if port != 0 or index != 0:
            return 0
        if ident == api.DEVICE_ID_POINTER_X:
            return p.x
        if ident == api.DEVICE_ID_POINTER_Y:
            return p.y
        if ident in (api.DEVICE_ID_POINTER_PRESSED, api.DEVICE_ID_POINTER_COUNT):
            return int(p.pressed)
        return 0
