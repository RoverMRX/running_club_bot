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
            is_approved=report.is_approved,
            is_rejected=report.is_rejected,
            created_at=report.created_at,
        ))
    return result