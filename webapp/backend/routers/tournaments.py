"""routers/tournaments.py — турниры."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import get_current_user
from schemas import TournamentOut, TournamentParticipantOut, OkResponse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import WeeklyTournament, TournamentParticipant, User

router = APIRouter(prefix="/tournaments", tags=["tournaments"])

TOUR_TYPE_NAMES = {
    "km":      "🏃 Больше километров",
    "minutes": "⏱ Больше минут",
    "days":    "📅 Больше дней",
    "team_km": "👥 Командные км",
}


async def _build_leaderboard(tournament_id: int, db: AsyncSession) -> list[TournamentParticipantOut]:
    res = await db.execute(
        select(TournamentParticipant, User)
        .join(User, User.tg_id == TournamentParticipant.user_tg_id)
        .where(TournamentParticipant.tournament_id == tournament_id)
        .order_by(TournamentParticipant.score.desc())
        .limit(20)
    )
    result = []
    for pos, (p, u) in enumerate(res.all(), 1):
        result.append(TournamentParticipantOut(
            position=pos,
            user_tg_id=u.tg_id,
            username=u.username,
            school_nick=u.school_nick,
            score=p.score,
        ))
    return result


@router.get("", response_model=list[TournamentOut])
async def get_tournaments(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    active_only: bool = True,
) -> list[TournamentOut]:
    """Список турниров."""
    user_id = tg_user["id"]
    q = select(WeeklyTournament)
    if active_only:
        q = q.where(WeeklyTournament.is_active == True)
    q = q.order_by(WeeklyTournament.created_at.desc())
    res = await db.execute(q)
    tournaments = res.scalars().all()

    result = []
    for t in tournaments:
        # Проверяем участие
        joined_res = await db.execute(
            select(TournamentParticipant).where(
                TournamentParticipant.tournament_id == t.id,
                TournamentParticipant.user_tg_id == user_id,
            )
        )
        user_joined = joined_res.scalar_one_or_none() is not None
        leaderboard = await _build_leaderboard(t.id, db)

        result.append(TournamentOut(
            id=t.id,
            title=t.title,
            tournament_type=t.tournament_type,
            start_date=t.start_date,
            end_date=t.end_date,
            is_active=t.is_active,
            leaderboard=leaderboard,
            user_joined=user_joined,
        ))
    return result


@router.get("/{tournament_id}", response_model=TournamentOut)
async def get_tournament(
    tournament_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TournamentOut:
    user_id = tg_user["id"]
    res = await db.execute(
        select(WeeklyTournament).where(WeeklyTournament.id == tournament_id)
    )
    t = res.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Турнир не найден")

    joined_res = await db.execute(
        select(TournamentParticipant).where(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.user_tg_id == user_id,
        )
    )
    user_joined = joined_res.scalar_one_or_none() is not None
    leaderboard = await _build_leaderboard(tournament_id, db)

    return TournamentOut(
        id=t.id,
        title=t.title,
        tournament_type=t.tournament_type,
        start_date=t.start_date,
        end_date=t.end_date,
        is_active=t.is_active,
        leaderboard=leaderboard,
        user_joined=user_joined,
    )


@router.post("/{tournament_id}/join", response_model=OkResponse)
async def join_tournament(
    tournament_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]

    t_res = await db.execute(
        select(WeeklyTournament).where(WeeklyTournament.id == tournament_id)
    )
    t = t_res.scalar_one_or_none()
    if not t or not t.is_active:
        return OkResponse(ok=False, reason="Турнир не найден или завершён.")

    exist_res = await db.execute(
        select(TournamentParticipant).where(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.user_tg_id == user_id,
        )
    )
    if exist_res.scalar_one_or_none():
        return OkResponse(ok=False, reason="Ты уже участвуешь!")

    db.add(TournamentParticipant(
        tournament_id=tournament_id,
        user_tg_id=user_id,
        score=0.0,
    ))
    await db.commit()
    return OkResponse(ok=True, reason="Ты в турнире!")