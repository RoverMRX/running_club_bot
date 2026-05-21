"""
webapp/backend/xp_utils.py — формулы прогрессивной шкалы XP/уровней.

Дублирует логику из services/xp.py, но без зависимостей на aiogram/SQLAlchemy —
нужно потому что webapp/backend работает в отдельном контейнере без services/.

Прогрессивная шкала:
    XP для перехода с уровня N на N+1 = 100 × (N + 1)
    total_xp_for_level(N) = 100 × N × (N + 1) / 2

    0→1: 100 XP, 1→2: 200 XP, 2→3: 300 XP, ...
"""
import math


def total_xp_for_level(level: int) -> int:
    """Суммарный XP для достижения уровня level."""
    return 100 * level * (level + 1) // 2


def xp_for_next_level(level: int) -> int:
    """XP нужно чтобы перейти с level на level+1."""
    return 100 * (level + 1)


def calc_level(total_xp: int) -> int:
    """Уровень по суммарному XP."""
    if total_xp <= 0:
        return 0
    n = int((-1 + math.sqrt(1 + total_xp / 50)) / 1)
    while total_xp_for_level(n + 1) <= total_xp:
        n += 1
    return n


def xp_progress(total_xp: int) -> dict:
    """Прогресс внутри текущего уровня.

    Returns:
        {"level": int, "xp_in_level": int, "xp_to_next": int}
    """
    level = calc_level(total_xp)
    base = total_xp_for_level(level)
    needed = xp_for_next_level(level)
    return {
        "level": level,
        "xp_in_level": total_xp - base,
        "xp_to_next": needed,
    }