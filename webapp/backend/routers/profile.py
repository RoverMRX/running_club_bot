"""routers/profile.py — профиль пользователя."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import get_current_user
from schemas import UserProfile

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import User, PersonalRecord
from xp_utils import xp_progress, calc_level

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserProfile)
async def get_profile(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """Профиль текущего пользователя."""
    user_id = tg_user["id"]

    u_res = await db.execute(select(User).where(User.tg_id == user_id))
    user = u_res.scalar_one_or_none()

    if not user:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail="Пользователь не зарегистрирован. Напиши /start боту.",
        )

    pr_res = await db.execute(
        select(PersonalRecord).where(PersonalRecord.user_tg_id == user_id)
    )
    pr = pr_res.scalar_one_or_none()

    progress = xp_progress(user.xp)

    return UserProfile(
        tg_id=user.tg_id,
        username=user.username,
        full_name=user.full_name,
        school_nick=user.school_nick,
        xp=user.xp,
        level=progress["level"],
        season_xp=user.season_xp,
        streak=user.streak,
        best_km=pr.best_km if pr else None,
        xp_in_level=progress["xp_in_level"],
        xp_to_next=progress["xp_to_next"],
    )


@router.get("/leaderboard")
async def get_leaderboard(
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
) -> list[dict]:
    """Таблица лидеров по XP."""
    res = await db.execute(
        select(User).order_by(User.xp.desc()).limit(limit)
    )
    users = res.scalars().all()

    medals = ["🥇", "🥈", "🥉"]
    result = []
    for i, u in enumerate(users, 1):
        result.append({
            "position":    i,
            "medal":       medals[i - 1] if i <= 3 else None,
            "tg_id":       u.tg_id,
            "username":    u.username,
            "school_nick": u.school_nick,
            "xp":          u.xp,
            "level":       calc_level(u.xp),  # всегда актуальный уровень
            "streak":      u.streak,
        })
    return result