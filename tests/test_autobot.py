from retrodesk.bot.autobot import HOLD_FRAMES, RELEASE_FRAMES, STUCK_FRAMES, AutoBot, BotConfig, Mode
from retrodesk.bot.battle import rank_moves
from retrodesk.gen3.game import BattleSnapshot, Phase
from retrodesk.gen3.model import MoveInfo, RomTables, parse_battle_mon
from retrodesk.libretro.api import JOYPAD

from gen3_fixtures import battle_mon

NORMAL, FIRE, WATER, GRASS = 0, 10, 11, 12
TACKLE, EMBER, WATER_GUN, GROWL = 1, 2, 3, 4


def tables() -> RomTables:
    moves = [MoveInfo(0, "-", 0, 0, 0, 0, 0, 0),
             MoveInfo(TACKLE, "Tackle", 0, 35, NORMAL, 95, 35, 0),
             MoveInfo(EMBER, "Ember", 0, 40, FIRE, 100, 25, 0),
             MoveInfo(WATER_GUN, "Water Gun", 0, 40, WATER, 100, 25, 0),
             MoveInfo(GROWL, "Growl", 0, 0, NORMAL, 100, 40, 0)]
    chart = {(FIRE, GRASS): 20, (WATER, GRASS): 5, (FIRE, WATER): 5, (WATER, FIRE): 20}
    return RomTables(moves, ["-", "Mon", "Foe"], [(0, 0)] * 3, [0, 1, 2], chart, -1)


def mon(types, moves=(TACKLE, EMBER, WATER_GUN, GROWL), pp=(10, 10, 10, 10), hp=50, max_hp=50, shiny=False):
    personality = 0x00000000 if shiny else 0x12345678
    ot = 0 if shiny else 0x0BADF00D
    return parse_battle_mon(battle_mon(1, 20, hp, max_hp, types=types, moves=moves, pp=pp,
                                       personality=personality, ot_id=ot))


def snap(phase, player=None, opponent=None, action=0, move=0, wild=True):
    return BattleSnapshot(phase, player, opponent, action, move, wild)


def pressed(bot, s):
    """Collect the buttons of the next tap."""
    masks = [bot.step(s) for _ in range(HOLD_FRAMES + RELEASE_FRAMES)]
    names = {n for n, bit in JOYPAD.items() if masks[0] >> bit & 1}
    assert all(m == masks[0] for m in masks[:HOLD_FRAMES]) and not any(masks[HOLD_FRAMES:])
    return names


def test_rank_moves_prefers_super_effective_and_skips_status_and_empty_pp():
    ranked = rank_moves(mon((FIRE, FIRE), pp=(10, 10, 0, 10)), mon((GRASS, GRASS)), tables())
    assert [s.name for s in ranked][:2] == ["Ember", "Tackle"]
    assert ranked[0].effectiveness == 2.0
    assert "Water Gun" not in [s.name for s in ranked]
    assert ranked[-1].name == "Growl" and ranked[-1].expected_damage == 0


def test_rank_moves_respects_allowed_slots():
    ranked = rank_moves(mon((FIRE, FIRE)), mon((GRASS, GRASS)), tables(), allowed={0})
    assert [s.name for s in ranked] == ["Tackle"]


def test_auto_move_navigates_grid_then_confirms():
    bot = AutoBot(tables(), BotConfig(mode=Mode.AUTO_MOVE))
    player, foe = mon((FIRE, FIRE)), mon((GRASS, GRASS))  # best: Ember, slot 1 (top right)
    assert pressed(bot, snap(Phase.CHOOSE_ACTION, player, foe, action=1)) == {"LEFT"}
    assert pressed(bot, snap(Phase.CHOOSE_ACTION, player, foe, action=0)) == {"A"}
    assert pressed(bot, snap(Phase.CHOOSE_MOVE, player, foe, move=2)) == {"UP"}
    assert pressed(bot, snap(Phase.CHOOSE_MOVE, player, foe, move=0)) == {"RIGHT"}
    assert pressed(bot, snap(Phase.CHOOSE_MOVE, player, foe, move=1)) == {"A"}
    assert bot.last_choice.startswith("Ember")


def test_shiny_hunt_runs_from_normal_and_stops_on_shiny():
    bot = AutoBot(tables(), BotConfig(mode=Mode.SHINY_HUNT))
    player = mon((FIRE, FIRE))
    assert pressed(bot, snap(Phase.CHOOSE_ACTION, player, mon((GRASS, GRASS)), action=0)) == {"DOWN"}
    assert pressed(bot, snap(Phase.CHOOSE_ACTION, player, mon((GRASS, GRASS)), action=2)) == {"RIGHT"}
    assert pressed(bot, snap(Phase.CHOOSE_ACTION, player, mon((GRASS, GRASS)), action=3)) == {"A"}
    assert bot.step(snap(Phase.CHOOSE_ACTION, player, mon((GRASS, GRASS), shiny=True))) == 0
    assert bot.paused_reason and "shiny" in bot.paused_reason
    assert bot.step(snap(Phase.OVERWORLD)) == 0  # stays paused until resumed


def test_grind_pauses_on_low_hp():
    bot = AutoBot(tables(), BotConfig(mode=Mode.AUTO_GRIND, stop_below_hp_percent=25))
    assert bot.step(snap(Phase.CHOOSE_ACTION, mon((FIRE, FIRE), hp=10, max_hp=50), mon((GRASS, GRASS)))) == 0
    assert "HP below" in bot.paused_reason


def test_grind_walks_in_overworld_and_mashes_b_in_battle_text():
    bot = AutoBot(tables(), BotConfig(mode=Mode.AUTO_GRIND, walk_steps=2))
    walk = [bot.step(snap(Phase.OVERWORLD)) for _ in range(4)]
    assert walk == [1 << JOYPAD["LEFT"]] * 2 + [1 << JOYPAD["RIGHT"]] * 2
    bot = AutoBot(tables(), BotConfig(mode=Mode.AUTO_GRIND))
    assert pressed(bot, snap(Phase.BATTLE)) == {"B"}


def test_stuck_battle_pauses():
    bot = AutoBot(tables(), BotConfig(mode=Mode.AUTO_MOVE))
    for _ in range(STUCK_FRAMES + 1):
        bot.step(snap(Phase.BATTLE))
    assert bot.paused_reason and "60s" in bot.paused_reason
