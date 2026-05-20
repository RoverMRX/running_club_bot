"""routers/challenges.py — челленджи."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import get_current_user
from schemas import ChallengeOut, ChallengeParticipantOut, JoinChallengeRequest, OkResponse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import Challenge, ChallengeParticipant, User

router = APIRouter(prefix="/challenges", tags=["challenges"])


async def _enrich_challenge(ch: Challenge, db: AsyncSession, viewer_id: int | None = None) -> ChallengeOut:
    """Дополняет челлендж данными об авторе и участниках."""
    # Автор
    author_res = await db.execute(select(User).where(User.tg_id == ch.user_id))
    author = author_res.scalar_one_or_none()

    # Участники
    parts_res = await db.execute(
        select(ChallengeParticipant, User)
        .join(User, User.tg_id == ChallengeParticipant.user_id)
        .where(ChallengeParticipant.challenge_id == ch.id)
        .order_by(ChallengeParticipant.joined_at)
    )
    participants = []
    for p, u in parts_res.all():
        participants.append(ChallengeParticipantOut(
            user_id=u.tg_id,
            username=u.username,
            school_nick=u.school_nick,
            penalty=p.penalty,
            current_runs=p.current_runs,
            current_value=p.current_value,
        ))

    return ChallengeOut(
        id=ch.id,
        title=ch.title,
        ch_type=ch.ch_type,
        min_per_run=ch.min_per_run or 0,
        min_minutes_per_run=ch.min_minutes_per_run or 0,
        goal_runs=ch.goal_runs or 0,
        goal_value=ch.goal_value or 0,
        goal_time=ch.goal_time,
        current_value=ch.current_value or 0,
        current_runs=ch.current_runs or 0,
        penalty=ch.penalty,
        is_active=ch.is_active,
        started_at=ch.started_at,
        deadline=ch.deadline,
        author_username=author.username if author else None,
        author_nick=author.school_nick if author else "?",
        participants=participants,
    )


# ─── Мои челленджи ───────────────────────────────────────────

@router.get("/my", response_model=list[ChallengeOut])
async def get_my_challenges(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    """Мои активные челленджи с прогрессом."""
    user_id = tg_user["id"]
    res = await db.execute(
        select(Challenge).where(
            Challenge.user_id == user_id,
            Challenge.is_active == True,
        ).order_by(Challenge.created_at.desc())
    )
    challenges = res.scalars().all()
    return [await _enrich_challenge(ch, db, user_id) for ch in challenges]


# ─── Публичные челленджи ─────────────────────────────────────

@router.get("/club", response_model=list[ChallengeOut])
async def get_club_challenges(
    db: AsyncSession = Depends(get_db),
    tg_user: dict = Depends(get_current_user),
    page: int = 0,
    page_size: int = 10,
) -> list[ChallengeOut]:
    """Все публичные активные челленджи клуба с пагинацией."""
    res = await db.execute(
        select(Challenge).where(
            Challenge.is_public == True,
            Challenge.is_active == True,
        )
        .order_by(Challenge.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    challenges = res.scalars().all()
    return [await _enrich_challenge(ch, db, tg_user["id"]) for ch in challenges]


@router.get("/club/count")
async def get_club_challenges_count(db: AsyncSession = Depends(get_db)) -> dict:
    """Общее количество публичных активных челленджей."""
    from sqlalchemy import func
    res = await db.execute(
        select(func.count()).where(
            Challenge.is_public == True,
            Challenge.is_active == True,
        )
    )
    return {"total": res.scalar()}


# ─── Карточка одного челленджа ───────────────────────────────

@router.get("/{challenge_id}", response_model=ChallengeOut)
async def get_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChallengeOut:
    res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = res.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Челлендж не найден")
    return await _enrich_challenge(ch, db, tg_user["id"])


# ─── Присоединиться к челленджу ──────────────────────────────

@router.post("/{challenge_id}/join", response_model=OkResponse)
async def join_challenge(
    challenge_id: int,
    body: JoinChallengeRequest,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]

    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch or not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж не найден или завершён.")
    if not ch.is_public:
        return OkResponse(ok=False, reason="Челлендж закрыт для присоединения.")
    if ch.user_id == user_id:
        return OkResponse(ok=False, reason="Это твой собственный челлендж.")

    # Уже участвует?
    exist_res = await db.execute(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == challenge_id,
            ChallengeParticipant.user_id == user_id,
        )
    )
    if exist_res.scalar_one_or_none():
        return OkResponse(ok=False, reason="Ты уже участвуешь в этом челлендже.")

    db.add(ChallengeParticipant(
        challenge_id=challenge_id,
        user_id=user_id,
        penalty=body.penalty,
    ))
    await db.commit()
    return OkResponse(ok=True, reason=f"Ты присоединился к «{ch.title}»!")