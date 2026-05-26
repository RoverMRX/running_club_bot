"""routers/profile.py — профиль пользователя."""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user
from schemas import UserProfile

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import User, PersonalRecord, Report
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


def _period_start(period: str) -> datetime | None:
    """Возвращает дату начала периода или None для alltime."""
    now = datetime.now()
    if period == "week":
        # Начало текущей недели (понедельник)
        return now - timedelta(days=now.weekday(), hours=now.hour,
                               minutes=now.minute, seconds=now.second)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "season":
        # Сезон — текущий квартал
        quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        return now.replace(month=quarter_start_month, day=1,
                           hour=0, minute=0, second=0, microsecond=0)
    return None  # alltime


@router.get("/leaderboard")
async def get_leaderboard(
    db: AsyncSession = Depends(get_db),
    tg_user: dict = Depends(get_current_user),
    period: str = Query("alltime", pattern="^(alltime|season|month|week)$"),
    sort_by: str = Query("xp", pattern="^(xp|km|streak|runs)$"),
    limit: int = Query(30, ge=1, le=100),
) -> list[dict]:
    """
    Расширенная таблица лидеров.

    period: alltime | season | month | week
    sort_by: xp | km | streak | runs
    """
    medals = ["🥇", "🥈", "🥉"]
    since = _period_start(period)

    # --- Для xp/streak сортируем по полям User ---
    if sort_by in ("xp", "streak") and period == "alltime":
        sort_col = User.xp if sort_by == "xp" else User.streak
        res = await db.execute(
            select(User).order_by(sort_col.desc()).limit(limit)
        )
        users = res.scalars().all()

        result = []
        for i, u in enumerate(users, 1):
            result.append({
                "position":    i,
                "medal":       medals[i - 1] if i <= 3 else None,
                "tg_id":       u.tg_id,
                "username":    u.username,
                "school_nick": u.school_nick,
                "xp":          u.xp,
                "season_xp":   u.season_xp,
                "level":       calc_level(u.xp),
                "streak":      u.streak,
                "km":          None,
                "runs":        None,
            })
        return result

    # --- Для km/runs или с фильтром периода — агрегируем отчёты ---
    # Базовый запрос одобренных отчётов
    q = select(
        Report.user_tg_id,
        func.sum(Report.km).label("total_km"),
        func.count(Report.id).label("total_runs"),
    ).where(Report.is_approved == True)  # noqa: E712

    if since:
        q = q.where(Report.created_at >= since)

    q = q.group_by(Report.user_tg_id)

    if sort_by == "km":
        q = q.order_by(func.sum(Report.km).desc())
    else:  # runs
        q = q.order_by(func.count(Report.id).desc())

    q = q.limit(limit)

    rows = (await db.execute(q)).all()

    # Для season xp — берём season_xp из User, для week/month нет колонки
    # Грузим профили пользователей одним запросом
    user_ids = [r.user_tg_id for r in rows]
    if not user_ids:
        return []

    users_res = await db.execute(select(User).where(User.tg_id.in_(user_ids)))
    users_map = {u.tg_id: u for u in users_res.scalars().all()}

    # Для xp по периоду season — сортируем по season_xp
    if sort_by == "xp" and period == "season":
        # Дополнительно получаем season_xp — пересортируем
        season_rows = sorted(
            [(uid, users_map[uid].season_xp) for uid in user_ids if uid in users_map],
            key=lambda x: x[1], reverse=True
        )
        result = []
        for i, (uid, s_xp) in enumerate(season_rows, 1):
            u = users_map.get(uid)
            if not u:
                continue
            result.append({
                "position":    i,
                "medal":       medals[i - 1] if i <= 3 else None,
                "tg_id":       u.tg_id,
                "username":    u.username,
                "school_nick": u.school_nick,
                "xp":          u.xp,
                "season_xp":   s_xp,
                "level":       calc_level(u.xp),
                "streak":      u.streak,
                "km":          None,
                "runs":        None,
            })
        return result

    # Для xp по week/month — XP не считаем из отчётов (нет таблицы xp_log)
    # Показываем топ по км/пробежкам за период, XP берём текущий
    result = []
    for i, row in enumerate(rows, 1):
        u = users_map.get(row.user_tg_id)
        if not u:
            continue
        result.append({
            "position":    i,
            "medal":       medals[i - 1] if i <= 3 else None,
            "tg_id":       u.tg_id,
            "username":    u.username,
            "school_nick": u.school_nick,
            "xp":          u.xp,
            "season_xp":   u.season_xp,
            "level":       calc_level(u.xp),
            "streak":      u.streak,
            "km":          round(float(row.total_km), 2),
            "runs":        row.total_runs,
        })
    return result


@router.get("/achievements")
async def get_achievements(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Все ачивки с флагом earned для текущего пользователя."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from services.achievements import get_user_achievements
    return await get_user_achievements(tg_user["id"])
