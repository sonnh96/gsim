import os
import time
from pathlib import Path

import numpy as np
import pytest

from retrodesk.states import StateSlots, read_png, write_png

ROOT = Path(__file__).resolve().parents[1]


def test_png_round_trip(tmp_path):
    rgba = np.random.default_rng(1).integers(0, 256, (37, 23, 4), dtype=np.uint8)
    write_png(tmp_path / "a.png", rgba)
    assert np.array_equal(read_png(tmp_path / "a.png"), rgba)


def test_slots_info_latest_and_previews(tmp_path):
    slots = StateSlots(tmp_path / "states")
    assert slots.latest() is None and slots.info(3).empty
    slots.write(5, b"five", np.zeros((2, 2, 4), np.uint8))
    slots.write(0, b"zero")
    old = time.time() - 3600
    os.utime(slots.path(0), (old, old))
    assert slots.latest() == 5
    assert slots.read(5) == b"five" and slots.preview(5).shape == (2, 2, 4)
    assert slots.preview(0) is None
    assert "empty" in slots.info(9).describe() and "saved" in slots.info(5).describe()
    slots.write(5, b"again")  # no picture this time: the old one must not linger
    assert slots.preview(5) is None


@pytest.mark.skipif(not (ROOT / "testroms" / "arm.gba").exists(), reason="needs testroms/arm.gba")
def test_session_save_load_undo_with_real_core(tmp_path, monkeypatch):
    import retrodesk.session as session
    from retrodesk.paths import installed_cores
    from retrodesk.systems import BY_ID

    if not installed_cores(BY_ID["gba"]):
        pytest.skip("mgba core not installed")
    monkeypatch.setattr(session, "rom_paths", lambda rom: {
        "system": tmp_path / "system", "saves": tmp_path / "saves",
        "sram": tmp_path / "saves" / "x.srm", "states": tmp_path / "states"})
    game = session.GameSession(ROOT / "testroms" / "arm.gba")
    try:
        game.core.run(30)
        game.save_state(2)
        assert game.states.latest() == 2 and game.states.preview(2) is not None
        saved_at = game.core.save_state()
        game.core.run(60)
        before_load = game.core.save_state()
        assert not game.can_undo_load
        game.load_state(2)
        assert game.core.save_state() == saved_at
        game.undo_load()
        assert game.core.save_state() == before_load and not game.can_undo_load
        with pytest.raises(FileNotFoundError):
            game.load_state(7)
    finally:
        game.core.close()
