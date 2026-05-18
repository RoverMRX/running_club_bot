"""
services/xp.py — единая система начисления XP.

Функции для начисления XP за разные события,
без привязки к конкретному хендлеру.
"""

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import config
from models import User, PersonalRecord, Challenge, ChallengeParticipant


async def give_xp_for_training(
    session: AsyncSession,
    user_tg_id: int,
    km: float,
    duration_min: int | None = None,
    event_bonus: int = 0,
    event_multiplier: float = 1.0,
) -> int:
    """
    Начисляет XP за тренировку.
    
    Args:
        session: БД сессия
        user_tg_id: ID пользователя
        km: дистанция
        duration_min: минуты (опционально)
        event_bonus: бонус за мероприятие (обычно 100 или 75)
        event_multiplier: множитель XP за км (обычно 1.0 или 1.5 для события)
    
    Returns:
        Всего выданно XP
    """
    # XP за км
    km_xp = int(km * config.XP_PER_KM * event_multiplier)
    total_xp = km_xp + event_bonus
    
    # Обновляем XP пользователя
    u_res = await session.execute(select(User).where(User.tg_id == user_tg_id))
    user = u_res.scalar_one_or_none()
    if user:
        user.xp += total_xp
        user.season_xp += total_xp
    
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
    # При подсчёте стрика в digest: 
    # u.streak увеличивается ДО этой функции
    # Поэтому текущий стрик уже в u.streak
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