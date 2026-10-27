"""Gen3Session against the real Emerald symbol table and a synthetic ROM/RAM."""

import pytest

from retrodesk.gen3.game import Gen3Session, Phase
from retrodesk.gen3.symbols import SYM_DIR, Symbols

from gen3_fixtures import FakeMemory, battle_mon

pytestmark = pytest.mark.skipif(not (SYM_DIR / "emerald.sym").exists(),
                                reason="run scripts/fetch_assets.py for pret symbols")


@pytest.fixture(scope="module")
def sym():
    return Symbols.load(SYM_DIR / "emerald.sym")


@pytest.fixture(scope="module")
def rom(sym):
    data = bytearray(0x400000)
    data[0xAC:0xB0] = b"BPEE"
    data[sym["gTypeEffectiveness"] - 0x08000000] = 0xFF
    return bytes(data)


def test_phase_and_battle_snapshot(sym, rom):
    mem = FakeMemory()
    session = Gen3Session(rom, mem)

    mem.write_u32(sym["gMain"] + 4, sym["CB2_Overworld"] | 1)
    assert session.phase() is Phase.OVERWORLD

    mem.write_u32(sym["gMain"] + 4, sym["BattleMainCB2"] | 1)
    mem.write(sym["gBattlersCount"], b"\x02")
    mem.write(sym["gBattleMons"], battle_mon(species=1, level=5, hp=20, max_hp=20)
              + battle_mon(species=4, level=3, hp=10, max_hp=12))
    assert session.phase() is Phase.BATTLE

    player_action = session.sym.nearest("HandleInputChooseAction", "HandleInputChooseMove")
    assert player_action == 0x08057588  # battle_controller_player.c, not the safari copy
    mem.write_u32(sym["gBattlerControllerFuncs"], player_action | 1)
    mem.write(sym["gActionSelectionCursor"], b"\x02")
    snap = session.battle()
    assert snap.phase is Phase.CHOOSE_ACTION
    assert snap.player.species == 1 and snap.opponent.species == 4
    assert snap.action_cursor == 2 and snap.wild

    mem.write_u32(sym["gBattlerControllerFuncs"], sym["HandleInputChooseMove"] | 1)
    mem.write_u32(sym["gBattleTypeFlags"], 1 << 3)
    snap = session.battle()
    assert snap.phase is Phase.CHOOSE_MOVE and not snap.wild
