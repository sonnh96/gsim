import json
import struct

import numpy as np

from retrodesk.libretro import api
from retrodesk.libretro.core import Frame, Region, _reduce
from retrodesk.pokedex.pokeapi import PokeApi


def test_region_range_and_select_matching():
    ewram = Region(start=0x02000000, length=0x40000, select=0, disconnect=0, ptr=0x1000, offset=0, name="EWRAM")
    assert ewram.matches(0x0203FFFF) and not ewram.matches(0x02040000)
    assert ewram.host_address(0x02000010) == 0x1010
    mirrored = Region(start=0x03000000, length=0x8000, select=0xFF000000, disconnect=0, ptr=0x5000, offset=0,
                      name="IWRAM")
    assert mirrored.matches(0x03FFFFF0)
    assert mirrored.host_address(0x03008004) == 0x5004  # wraps within the 32 KiB mirror


def test_reduce_removes_disconnected_bits():
    assert _reduce(0b1011, 0b0100) == 0b111


def test_frame_conversions():
    from retrodesk.app.video import frame_to_rgba

    xrgb = Frame(bytes([0x10, 0x20, 0x30, 0x00]) * 2 + bytes(8), 2, 1, 16, api.PIXEL_XRGB8888)
    assert frame_to_rgba(xrgb).tolist() == [[[0x30, 0x20, 0x10, 255]] * 2]
    rgb565 = Frame(struct.pack("<HH", 0xF800, 0x07E0), 2, 1, 4, api.PIXEL_RGB565)
    assert frame_to_rgba(rgb565)[0, :, :3].tolist() == [[255, 0, 0], [0, 255, 0]]
    x1555 = Frame(struct.pack("<H", 0x001F), 1, 1, 2, api.PIXEL_0RGB1555)
    assert np.array_equal(frame_to_rgba(x1555)[0, 0], [0, 0, 255, 255])


def test_pokeapi_uses_cache_without_network(tmp_path):
    (tmp_path / "pokemon_25.json").write_text(json.dumps({
        "id": 25, "name": "pikachu", "height": 4, "weight": 60,
        "types": [{"slot": 1, "type": {"name": "electric"}}],
        "stats": [{"stat": {"name": "speed"}, "base_stat": 90}],
        "abilities": [{"ability": {"name": "static"}}],
        "sprites": {"front_default": None},
    }))
    (tmp_path / "pokemon-species_25.json").write_text(json.dumps({
        "flavor_text_entries": [{"language": {"name": "en"}, "flavor_text": "Stores\nelectricity."}],
    }))
    entry = PokeApi(cache_dir=tmp_path, timeout=0.01).entry(25)
    assert entry.types == ["electric"] and entry.stats == {"speed": 90}
    assert entry.flavor == "Stores electricity."
