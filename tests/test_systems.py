from pathlib import Path

import pytest

from retrodesk.systems import BY_ID, SYSTEMS, system_for


def test_every_listed_system_has_cores_and_extensions():
    for s in SYSTEMS:
        assert s.cores and s.extensions
        assert all(e.startswith(".") for e in s.extensions)


def test_unambiguous_extensions():
    assert system_for(Path("x/game.nes")).id == "nes"
    assert system_for(Path("x/game.SFC")).id == "snes"
    assert system_for(Path("x/game.gbc")).id == "gbc"
    assert system_for(Path("x/game.nds")).id == "nds"
    assert system_for(Path("x/game.cue")).id == "psx"


def test_ambiguous_extension_uses_folder_then_default(tmp_path):
    assert system_for(tmp_path / "Neo Geo" / "mslug.zip").id == "neogeo"
    assert system_for(tmp_path / "mame" / "pacman.zip").id == "arcade"
    assert system_for(tmp_path / "psp" / "game.iso").id == "psp"
    assert system_for(tmp_path / "PS2" / "game.iso").id == "ps2"
    assert system_for(tmp_path / "misc" / "thing.zip").id == "arcade"


def test_hint_wins_and_unknown_hint_fails():
    assert system_for(Path("a.zip"), "neogeo") is BY_ID["neogeo"]
    with pytest.raises(ValueError):
        system_for(Path("a.zip"), "dreamcast")
    with pytest.raises(ValueError):
        system_for(Path("a.txt"))
