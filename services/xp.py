"""
services/xp.py — единая система начисления XP.

Функции для начисления XP за разные события,
без привязки к конкретному хендлеру.

Прогрессивная шкала уровней:
    XP для перехода с уровня N на N+1 = 100 × (N + 1)
    Т.е. 0→1: 100 XP, 1→2: 200 XP, 2→3: 300 XP, ...

    total_xp_for_level(N) = 100 × N × (N + 1) / 2
    Уровень по total XP: N = floor((-1 + sqrt(1 + total_xp/50)) / 1)
    (решаем N(N+1)/2 × 100 ≤ total_xp)
"""

import math
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import config
from models import User, PersonalRecord, Challenge, ChallengeParticipant


# ──────────────────────────────────────────────────────────────
# Формулы уровней (чистые функции, без БД)
# ──────────────────────────────────────────────────────────────

def total_xp_for_level(level: int) -> int:
    """Сколько суммарного XP нужно чтобы достичь этого уровня.

    level=0 → 0, level=1 → 100, level=2 → 300, level=3 → 600, ...
    Формула: 100 × level × (level + 1) / 2
    """
    return 100 * level * (level + 1) // 2


def xp_for_next_level(level: int) -> int:
    """Сколько XP нужно чтобы перейти с level на level+1.

    level=0 → 100, level=1 → 200, level=2 → 300, ...
    """
    return 100 * (level + 1)


def calc_level(total_xp: int) -> int:
    """Вычислить уровень по суммарному XP.

    Решаем 100 × N × (N+1) / 2 ≤ total_xp
    N² + N - total_xp/50 ≤ 0
    N = floor((-1 + sqrt(1 + 4 × total_xp/100)) / 2)
    """
    if total_xp <= 0:
        return 0
    # Упрощённо: N = floor((-1 + sqrt(1 + total_xp/50)) / 1)
    # Точная формула через квадратное уравнение N(N+1)/2 = total_xp/100
    n = int((-1 + math.sqrt(1 + total_xp / 50)) / 1)
    # Гарантируем что не вышли за рамки
    while total_xp_for_level(n + 1) <= total_xp:
        n += 1
    return n


def xp_progress(total_xp: int) -> dict:
    """Прогресс внутри текущего уровня.

    Returns:
        {
            "level": int,
            "xp_in_level": int,   # XP накоплено в этом уровне
            "xp_to_next":  int,   # XP нужно для следующего уровня
        }
    """
    level = calc_level(total_xp)
    base = total_xp_for_level(level)
    needed = xp_for_next_level(level)
    return {
        "level": level,
        "xp_in_level": total_xp - base,
        "xp_to_next": needed,
    }


# ──────────────────────────────────────────────────────────────
# Начисление XP (с записью в БД)
# ──────────────────────────────────────────────────────────────

async def give_xp_for_training(
    session: AsyncSession,
    user_tg_id: int,
    km: float,
    duration_min: int | None = None,
    event_bonus: int = 0,
    event_multiplier: float = 1.0,
) -> int:
    """
    Начисляет XP за тренировку и пересчитывает уровень.

    Args:
        session: БД сессия
        user_tg_id: ID пользователя
        km: дистанция
        duration_min: минуты (опционально)
        event_bonus: бонус за мероприятие (обычно 100 или 75)
        event_multiplier: множитель XP за км (обычно 1.0 или 1.5 для события)

    Returns:
        Всего выдано XP
    """
    km_xp = int(km * config.XP_PER_KM * event_multiplier)
    total_xp = km_xp + event_bonus

    u_res = await session.execute(select(User).where(User.tg_id == user_tg_id))
    user = u_res.scalar_one_or_none()
    if user:
        user.xp += total_xp
        user.season_xp += total_xp
        user.level = calc_level(user.xp)

    await session.flush()
    return total_xp


async def check_and_update_pr(
    session: AsyncSession,
    user_tg_id: int,
    km: float,
) -> tuple[bool, int]:
    """
    Проверяет и обновляет личный рекорд.

    Returns:
        (is_new_pr, xp_bonus)
    """
    pr_res = await session.execute(
        select(PersonalRecord).where(PersonalRecord.user_tg_id == user_tg_id)
    )
    pr = pr_res.scalar_one_or_none()

    is_new_pr = False
    xp_bonus = 0

    if not pr:
        pr = PersonalRecord(user_tg_id=user_tg_id, best_km=km, set_at=datetime.now())
        session.add(pr)
        is_new_pr = True
        xp_bonus = config.XP_PR_BONUS
    elif km > pr.best_km:
        pr.best_km = km
        pr.set_at = datetime.now()
        is_new_pr = True
        xp_bonus = config.XP_PR_BONUS

    await session.flush()
    return is_new_pr, xp_bonus


async def check_streak_milestone(user_xp: int) -> tuple[bool, int]:
    """
    Проверяет есть ли milestone на текущий стрик.

    Returns:
        (has_milestone, xp_bonus)
    """
    for milestone_weeks, xp in sorted(config.STREAK_MILESTONES.items()):
        if milestone_weeks == 4 and user_xp < 500:
            return True, xp
        elif milestone_weeks == 8 and user_xp < 1500:
            return True, xp
        elif milestone_weeks == 12 and user_xp < 3000:
            return True, xp
        elif milestone_weeks == 20 and user_xp < 6000:
            return True, xp
    return False, 0