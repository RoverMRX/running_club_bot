"""
services/users.py — управление пользователями.

Функции:
  - get_or_create() — получить или создать пользователя
  - get_profile() — полный профиль с челленджами, отчётами
  - add_xp() — добавить XP и обновить level
  - add_streak() — увеличить стрик
  - reset_streak() — сбросить стрик в 0
  - get_leaderboard() — топ пользователей по XP
  - pause_challenges() — админ паузит все челленджи на N дней
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import User as TgUser

from database import async_session
from models import User, Challenge, ChallengeParticipant, Report

log = logging.getLogger(__name__)


async def get_or_create(session: AsyncSession, tg_user: TgUser, school_nick: str = None) -> User:
    """
    Получает пользователя из БД или создаёт нового.
    
    Args:
        session: БД сессия
        tg_user: объект User от Telegram
        school_nick: школьный ник (если это регистрация)
    
    Returns:
        User объект
    """
    res = await session.execute(select(User).where(User.tg_id == tg_user.id))
    user = res.scalar_one_or_none()
    
    if not user:
        # Новый пользователь
        user = User(
            tg_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            school_nick=school_nick or f"user_{tg_user.id}",  # На случай если не заполнили
            xp=0,
            level=0,
            season_xp=0,
            streak=0,
        )
        session.add(user)
        await session.flush()
    
    return user


async def get_user_by_id(session: AsyncSession, tg_id: int) -> User | None:
    """Получить пользователя по tg_id."""
    res = await session.execute(select(User).where(User.tg_id == tg_id))
    return res.scalar_one_or_none()


async def get_profile(tg_id: int) -> dict:
    """
    Получить полный профиль пользователя.
    
    Returns:
        {
            'user': User,
            'own_challenges': [...],
            'joined_challenges': [...],
            'active_reports': [...],
            'pr': float,
            'achievements': {...}
        }
    """
    async with async_session() as session:
        # Пользователь
        u_res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = u_res.scalar_one_or_none()
        
        if not user:
            return None
        
        # Свои челленджи
        own_res = await session.execute(
            select(Challenge).where(
                Challenge.user_id == tg_id,
                Challenge.is_active == True,
            )
        )
        own_challenges = own_res.scalars().all()
        
        # Чужие челленджи (присоединился)
        joined_res = await session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.user_id == tg_id
            )
        )
        joined_challenges = [p.challenge for p in joined_res.scalars().all()]
        
        # Последние отчёты
        reports_res = await session.execute(
            select(Report)
            .where(Report.user_tg_id == tg_id)
            .order_by(Report.created_at.desc())
            .limit(5)
        )
        recent_reports = reports_res.scalars().all()
        
        # Личный рекорд
        from models import PersonalRecord
        pr_res = await session.execute(
            select(PersonalRecord).where(PersonalRecord.user_tg_id == tg_id)
        )
        pr = pr_res.scalar_one_or_none()
        
        return {
            'user': user,
            'own_challenges': own_challenges,
            'joined_challenges': joined_challenges,
            'recent_reports': recent_reports,
            'pr': pr.best_km if pr else 0.0,
            'level': user.level,
            'xp': user.xp,
            'season_xp': user.season_xp,
            'streak': user.streak,
        }


async def add_xp(tg_id: int, amount: int) -> int:
    """
    Добавить XP пользователю и обновить level.
    
    Args:
        tg_id: ID пользователя
        amount: сколько XP добавить
    
    Returns:
        Новый level
    """
    async with async_session() as session:
        async with session.begin():
            u_res = await session.execute(select(User).where(User.tg_id == tg_id))
            user = u_res.scalar_one_or_none()
            
            if user:
                user.xp += amount
                user.season_xp += amount
                user.level = user.xp // 100  # Вычисляем новый level
                await session.flush()
                return user.level
    
    return 0


async def add_streak(tg_id: int) -> int:
    """Увеличить стрик на 1."""
    async with async_session() as session:
        async with session.begin():
            u_res = await session.execute(select(User).where(User.tg_id == tg_id))
            user = u_res.scalar_one_or_none()
            
            if user:
                user.streak += 1
                user.last_week_closed = datetime.now()
                await session.flush()
                return user.streak
    
    return 0


async def reset_streak(tg_id: int) -> int:
    """Сбросить стрик в 0."""
    async with async_session() as session:
        async with session.begin():
            u_res = await session.execute(select(User).where(User.tg_id == tg_id))
            user = u_res.scalar_one_or_none()
            
            if user:
                user.streak = 0
                await session.flush()
                return 0
    
    return 0


async def get_leaderboard(limit: int = 10) -> list[dict]:
    """
    Получить таблицу лидеров по XP (all-time).
    
    Returns:
        [
            {
                'position': 1,
                'school_nick': '@vasya_school',
                'username': '@vasya',
                'level': 47,
                'xp': 5320,
                'streak': 15,
            },
            ...
        ]
    """
    async with async_session() as session:
        res = await session.execute(
            select(User)
            .where(User.xp > 0)
            .order_by(User.xp.desc())
            .limit(limit)
        )
        users = res.scalars().all()
    
    leaderboard = []
    for pos, user in enumerate(users, 1):
        leaderboard.append({
            'position': pos,
            'school_nick': user.school_nick,
            'username': f"@{user.username}" if user.username else "unknown",
            'level': user.level,
            'xp': user.xp,
            'streak': user.streak,
        })
    
    return leaderboard


async def get_season_leaderboard(limit: int = 10) -> list[dict]:
    """
    Таблица лидеров по квартальному XP.
    
    Returns:
        [
            {
                'position': 1,
                'school_nick': '@vasya_school',
                'username': '@vasya',
                'season_xp': 450,
                'level': 4,
            },
            ...
        ]
    """
    async with async_session() as session:
        res = await session.execute(
            select(User)
            .where(User.season_xp > 0)
            .order_by(User.season_xp.desc())
            .limit(limit)
        )
        users = res.scalars().all()
    
    leaderboard = []
    for pos, user in enumerate(users, 1):
        leaderboard.append({
            'position': pos,
            'school_nick': user.school_nick,
            'username': f"@{user.username}" if user.username else "unknown",
            'season_xp': user.season_xp,
            'level': user.level,
        })
    
    return leaderboard


async def pause_challenges(tg_id: int, days: int) -> int:
    """
    Админ паузит все челленджи пользователя на N дней (форс-мажор).
    
    Args:
        tg_id: ID пользователя
        days: на сколько дней паузировать
    
    Returns:
        Количество запаузированных челленджей
    """
    async with async_session() as session:
        async with session.begin():
            ch_res = await session.execute(
                select(Challenge).where(
                    Challenge.user_id == tg_id,
                    Challenge.is_active == True,
                )
            )
            challenges = ch_res.scalars().all()
            
            pause_until = datetime.now() + timedelta(days=days)
            for ch in challenges:
                ch.pause_until = pause_until
            
            await session.flush()
            return len(challenges)


async def reset_season_xp() -> int:
    """
    Сбросить квартальный XP для всех пользователей.
    Вызывается в начале каждого квартала.
    
    Returns:
        Количество пользователей
    """
    async with async_session() as session:
        async with session.begin():
            await session.execute(update(User).values(season_xp=0))
            
            res = await session.execute(select(func.count(User.id)))
            count = res.scalar()
            return count


async def exists_school_nick(school_nick: str) -> bool:
    """Проверить существует ли школьный ник."""
    async with async_session() as session:
        res = await session.execute(
            select(func.count(User.id)).where(User.school_nick == school_nick)
        )
        return res.scalar() > 0


async def update_school_nick(tg_id: int, new_nick: str) -> bool:
    """Обновить школьный ник пользователя."""
    if await exists_school_nick(new_nick):
        return False  # Ник уже занят
    
    async with async_session() as session:
        async with session.begin():
            u_res = await session.execute(select(User).where(User.tg_id == tg_id))
            user = u_res.scalar_one_or_none()
            
            if user:
                user.school_nick = new_nick
                await session.flush()
                return True
    
    return False