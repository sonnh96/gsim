import ctypes as C

from retrodesk.app.layout import Rect, fit, to_pointer
from retrodesk.libretro import api
from retrodesk.libretro.core import Core, PointerState
from retrodesk.options import OptionStore
from retrodesk.systems import BY_ID, System, missing_bios


def bare_core(overrides=None) -> Core:
    """A Core with the Python-side state only, for exercising callbacks without a library."""
    core = Core.__new__(Core)
    core._option_overrides = dict(overrides or {})
    core._variables, core._variable_choices, core.option_descriptions = {}, {}, {}
    core.pointer = PointerState()
    core.input_mask = lambda port: 0
    return core


def test_fit_centres_and_keeps_aspect():
    r = fit(Rect(0, 0, 1000, 500), 4 / 3)
    assert (round(r.w), round(r.h)) == (667, 500) and round(r.x) == 167 and r.y == 0
    assert fit(Rect(0, 0, 0, 500), 1).w == 0


def test_pointer_matches_melonds_pixel_formula():
    view = Rect(40, 30, 512, 768)  # a 256x384 DS frame drawn at 2x
    for px, py in [(0, 0), (100, 242), (255, 383), (128, 192)]:
        x, y, inside = to_pointer(view, 40 + (px + 0.5) * 2, 30 + (py + 0.5) * 2)
        assert inside
        assert (x + 0x8000) * 256 // 0x10000 == px  # how melonDS turns pointer units into pixels
        assert (y + 0x8000) * 384 // 0x10000 == py
    x, y, inside = to_pointer(view, 10, 10)
    assert not inside and x == -api.POINTER_MAX and y == -api.POINTER_MAX


def test_input_state_reports_pointer_and_masks_subclassed_devices():
    core = bare_core()
    core.pointer = PointerState(-100, 200, True)
    pointer_subclass = (1 << 8) | api.DEVICE_POINTER
    assert core._input_state(0, pointer_subclass, 0, api.DEVICE_ID_POINTER_X) == -100
    assert core._input_state(0, api.DEVICE_POINTER, 0, api.DEVICE_ID_POINTER_Y) == 200
    assert core._input_state(0, api.DEVICE_POINTER, 0, api.DEVICE_ID_POINTER_PRESSED) == 1
    assert core._input_state(1, api.DEVICE_POINTER, 0, api.DEVICE_ID_POINTER_PRESSED) == 0
    core.input_mask = lambda port: 1 << api.JOYPAD["A"] if port == 1 else 0
    assert core._input_state(1, api.DEVICE_JOYPAD, 0, api.JOYPAD["A"]) == 1
    assert core._input_state(0, api.DEVICE_JOYPAD, 0, api.JOYPAD["A"]) == 0


def _v2_options(*defs):
    arr = (api.CoreOptionV2Definition * (len(defs) + 1))()
    for i, (key, desc, values, default) in enumerate(defs):
        arr[i].key, arr[i].desc, arr[i].default_value = key, desc, default
        for j, v in enumerate(values):
            arr[i].values[j].value = v
    return arr, api.CoreOptionsV2(None, C.cast(arr, C.POINTER(api.CoreOptionV2Definition)))


def test_core_options_v2_defaults_and_overrides():
    keep, opts = _v2_options((b"layout", b"Screen layout", [b"top", b"left"], b"left"),
                             (b"touch", b"Touch mode", [b"auto", b"touch"], None))
    core = bare_core({"touch": "touch", "layout": "not-a-choice"})
    core._register_options_v2(opts)
    assert core.variables == {"layout": "left", "touch": "touch"}
    assert core.variable_choices("layout") == ["top", "left"]
    assert core.option_descriptions["layout"] == "Screen layout"


def test_core_options_v0_variables():
    arr = (api.Variable * 2)()
    arr[0].key, arr[0].value = b"speed", b"Emulation speed; normal|fast"
    core = bare_core({"speed": "fast"})
    core._register_variables(C.cast(arr, C.POINTER(api.Variable)))
    assert core.variables == {"speed": "fast"} and core.option_descriptions["speed"] == "Emulation speed"


def test_option_store_merges_system_defaults_with_saved(tmp_path):
    store = OptionStore("/x/melonds_libretro.dylib", root=tmp_path)
    assert store.effective(BY_ID["nds"]) == {"melonds_touch_mode": "Touch"}
    store.set("melonds_touch_mode", "Mouse")
    store.set("melonds_screen_layout", "Left/Right")
    assert store.path == tmp_path / "melonds_libretro.json"
    assert store.effective(BY_ID["nds"]) == {"melonds_touch_mode": "Mouse", "melonds_screen_layout": "Left/Right"}
    store.path.write_text("{broken")
    assert store.load() == {}


def test_missing_bios_all_and_any(tmp_path):
    (tmp_path / "bios7.bin").write_bytes(b"")
    assert missing_bios(BY_ID["nds"], [tmp_path]) == ["bios9.bin", "firmware.bin"]
    psx = BY_ID["psx"]
    assert missing_bios(psx, [tmp_path]) == list(psx.bios)
    (tmp_path / "scph1001.bin").write_bytes(b"")
    assert missing_bios(psx, [tmp_path / "nope", tmp_path]) == []
    assert missing_bios(System("x", "X", (".x",), ("c",)), [tmp_path]) == []
