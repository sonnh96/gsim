"""Move selection for Generation 3 battles."""

from __future__ import annotations

from dataclasses import dataclass

from ..gen3.model import BattleMon, RomTables

VARIABLE_POWER = 1  # Gen 3 stores 1 for moves whose power is computed at runtime
VARIABLE_POWER_GUESS = 40


@dataclass(frozen=True)
class MoveScore:
    slot: int
    move_id: int
    name: str
    expected_damage: float
    effectiveness: float


def estimate_damage(user: BattleMon, target: BattleMon, move_id: int, tables: RomTables) -> tuple[float, float]:
    """Expected damage (accuracy-weighted, capped at target HP) and type multiplier.

    Uses the Gen 3 base formula with STAB and type effectiveness; ignores
    random spread, crits, abilities, weather and held items.
    """
    move = tables.moves[move_id]
    power = VARIABLE_POWER_GUESS if move.power == VARIABLE_POWER else move.power
    eff = tables.effectiveness(move.type, target.types)
    if power == 0 or eff == 0:
        return 0.0, eff
    attack, defense = (user.attack, target.defense) if move.physical else (user.sp_attack, target.sp_defense)
    base = ((2 * user.level // 5 + 2) * power * attack // max(defense, 1)) // 50 + 2
    stab = 1.5 if move.type in user.types else 1.0
    damage = base * stab * eff
    accuracy = (move.accuracy or 100) / 100
    return min(damage, target.hp) * accuracy, eff


def rank_moves(user: BattleMon, target: BattleMon, tables: RomTables,
               allowed: set[int] | None = None) -> list[MoveScore]:
    """Usable moves sorted best first. `allowed` limits choice to move slots."""
    scores = []
    for slot, (move_id, pp) in enumerate(zip(user.moves, user.pp)):
        if move_id == 0 or pp == 0 or (allowed is not None and slot not in allowed):
            continue
        dmg, eff = estimate_damage(user, target, move_id, tables)
        scores.append(MoveScore(slot, move_id, tables.moves[move_id].name, dmg, eff))
    # Prefer damage, then higher remaining PP as a tie-break.
    scores.sort(key=lambda s: (s.expected_damage, user.pp[s.slot]), reverse=True)
    return scores
