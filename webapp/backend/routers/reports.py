"""routers/reports.py — лента отчётов."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import get_current_user
from schemas import ReportOut

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import Report, User

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportOut])
async def get_reports(
    db: AsyncSession = Depends(get_db),
    tg_user: dict = Depends(get_current_user),
    page: int = 0,
    page_size: int = 20,
) -> list[ReportOut]:
    """Лента последних отчётов клуба."""
    res = await db.execute(
        select(Report, User)
        .join(User, User.tg_id == Report.user_tg_id)
        .order_by(Report.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    result = []
    for report, user in res.all():
        result.append(ReportOut(
            id=report.id,
            user_tg_id=report.user_tg_id,
            username=user.username,
            school_nick=user.school_nick,
            km=report.km,
            duration_sec=getattr(report, "duration_sec", None),
            is_approved=report.is_approved,
            is_rejected=report.is_rejected,
            created_at=report.created_at,
        ))
    return result


@router.get("/my", response_model=list[ReportOut])
async def get_my_reports(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = 0,
    page_size: int = 20,
) -> list[ReportOut]:
    """Мои отчёты."""
    user_id = tg_user["id"]
    res = await db.execute(
        select(Report, User)
        .join(User, User.tg_id == Report.user_tg_id)
        .where(Report.user_tg_id == user_id)
        .order_by(Report.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    result = []
    for report, user in res.all():
        result.append(ReportOut(
            id=report.id,
            user_tg_id=report.user_tg_id,
            username=user.username,
            school_nick=user.school_nick,
            km=report.km,
            duration_sec=getattr(report, "duration_sec", None),
            is_approved=report.is_approved,
            is_rejected=report.is_rejected,
            created_at=report.created_at,
        ))
    return result

@router.get("/my/stats")
async def get_my_stats(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Статистика пробежек: по дням за последние 30 дней и по неделям за последние 12 недель."""
    return await _get_stats(tg_user["id"], db)


async def _get_stats(user_id: int, db: AsyncSession) -> dict:
    from sqlalchemy import func, text
    from datetime import datetime, timedelta

    now = datetime.now()

    # ── По дням — последние 30 дней ──────────────────────────────────
    daily_res = await db.execute(
        text("""
            SELECT
                DATE(created_at) as day,
                SUM(km)          as total_km,
                COUNT(*)         as runs
            FROM reports
            WHERE user_tg_id = :uid
              AND is_approved = 1
              AND created_at >= :since
            GROUP BY DATE(created_at)
            ORDER BY day
        """),
        {"uid": user_id, "since": (now - timedelta(days=30)).isoformat()}
    )
    daily = [
        {"date": str(r.day), "km": round(float(r.total_km), 2), "runs": r.runs}
        for r in daily_res.fetchall()
    ]

    # ── По неделям — последние 12 недель ─────────────────────────────
    weekly_res = await db.execute(
        text("""
            SELECT
                STRFTIME('%Y-W%W', created_at) as week,
                SUM(km)                        as total_km,
                COUNT(*)                       as runs
            FROM reports
            WHERE user_tg_id = :uid
              AND is_approved = 1
              AND created_at >= :since
            GROUP BY STRFTIME('%Y-W%W', created_at)
            ORDER BY week
        """),
        {"uid": user_id, "since": (now - timedelta(weeks=12)).isoformat()}
    )
    weekly = [
        {"week": str(r.week), "km": round(float(r.total_km), 2), "runs": r.runs}
        for r in weekly_res.fetchall()
    ]

    # ── Итоги ─────────────────────────────────────────────────────────
    totals_res = await db.execute(
        text("""
            SELECT
                COUNT(*)  as total_runs,
                SUM(km)   as total_km,
                MAX(km)   as best_km,
                AVG(km)   as avg_km
            FROM reports
            WHERE user_tg_id = :uid AND is_approved = 1
        """),
        {"uid": user_id}
    )
    t = totals_res.fetchone()

    return {
        "daily":      daily,
        "weekly":     weekly,
        "total_runs": t.total_runs or 0,
        "total_km":   round(float(t.total_km or 0), 2),
        "best_km":    round(float(t.best_km or 0), 2),
        "avg_km":     round(float(t.avg_km or 0), 2),
    }
