"""routers/challenges.py — челленджи."""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user
from schemas import ChallengeOut, ChallengeParticipantOut, JoinChallengeRequest, OkResponse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import Challenge, ChallengeParticipant, User

router = APIRouter(prefix="/challenges", tags=["challenges"])

# Автодедлайны для спринтов
_SPRINT_DAYS = {"daily_km": 1, "weekly_km": 7, "monthly_km": 30}


async def _enrich_challenge(
    ch: Challenge,
    db: AsyncSession,
    viewer_id: int | None = None,
) -> ChallengeOut:
    """Дополняет челлендж данными об авторе, участниках и прогрессе."""
    author_res = await db.execute(select(User).where(User.tg_id == ch.user_id))
    author = author_res.scalar_one_or_none()

    parts_res = await db.execute(
        select(ChallengeParticipant, User)
        .join(User, User.tg_id == ChallengeParticipant.user_id)
        .where(ChallengeParticipant.challenge_id == ch.id)
        .order_by(ChallengeParticipant.joined_at)
    )
    participants = []
    is_participant = False
    for p, u in parts_res.all():
        if viewer_id and u.tg_id == viewer_id:
            is_participant = True
        participants.append(ChallengeParticipantOut(
            user_id=u.tg_id,
            username=u.username,
            school_nick=u.school_nick,
            penalty=p.penalty,
            current_runs=p.current_runs,
            current_value=p.current_value,
        ))

    is_owner = viewer_id is not None and ch.user_id == viewer_id

    # Дней до дедлайна
    days_left: int | None = None
    if ch.deadline:
        delta = ch.deadline - datetime.now()
        days_left = max(0, delta.days)

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
        is_owner=is_owner,
        is_participant=is_participant,
        days_left=days_left,
        participants=participants,
    )


# ─── Мои активные ────────────────────────────────────────────

@router.get("/my", response_model=list[ChallengeOut])
async def get_my_challenges(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    """Мои активные челленджи (автор) + активные в которых участвую."""
    user_id = tg_user["id"]

    # Свои активные
    own_res = await db.execute(
        select(Challenge).where(
            Challenge.user_id == user_id,
            Challenge.is_active == True,
        ).order_by(Challenge.created_at.desc())
    )
    own = own_res.scalars().all()

    # Присоединился (активные, чужие)
    joined_res = await db.execute(
        select(Challenge)
        .join(ChallengeParticipant, ChallengeParticipant.challenge_id == Challenge.id)
        .where(
            ChallengeParticipant.user_id == user_id,
            Challenge.user_id != user_id,
            Challenge.is_active == True,
        )
        .order_by(Challenge.created_at.desc())
    )
    joined = joined_res.scalars().all()

    all_ch = list(own) + list(joined)
    return [await _enrich_challenge(ch, db, user_id) for ch in all_ch]


# ─── История завершённых ──────────────────────────────────────

@router.get("/my/history", response_model=list[ChallengeOut])
async def get_my_history(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    """Завершённые челленджи (свои + участвовал)."""
    user_id = tg_user["id"]

    own_res = await db.execute(
        select(Challenge).where(
            Challenge.user_id == user_id,
            Challenge.is_active == False,
        ).order_by(Challenge.created_at.desc()).limit(30)
    )
    own = own_res.scalars().all()

    joined_res = await db.execute(
        select(Challenge)
        .join(ChallengeParticipant, ChallengeParticipant.challenge_id == Challenge.id)
        .where(
            ChallengeParticipant.user_id == user_id,
            Challenge.user_id != user_id,
            Challenge.is_active == False,
        )
        .order_by(Challenge.created_at.desc()).limit(20)
    )
    joined = joined_res.scalars().all()

    all_ch = list(own) + list(joined)
    return [await _enrich_challenge(ch, db, user_id) for ch in all_ch]


# ─── Публичные ───────────────────────────────────────────────

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
    res = await db.execute(
        select(func.count()).where(
            Challenge.is_public == True,
            Challenge.is_active == True,
        )
    )
    return {"total": res.scalar()}


# ─── Карточка ────────────────────────────────────────────────

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


# ─── Создание ────────────────────────────────────────────────

@router.post("", response_model=OkResponse)
async def create_challenge(
    body: dict,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """
    Создать челлендж.

    Body (общие поля):
      title, ch_type, penalty?, is_public?

    По типу:
      weekly_runs:          goal_runs, min_per_run?, min_minutes_per_run?, deadline?
      daily/weekly/monthly: goal_value  (deadline вычисляется автоматически)
      race:                 goal_value, deadline
    """
    user_id = tg_user["id"]
    ch_type = body.get("ch_type", "")
    title   = (body.get("title") or "").strip()

    if not title:
        return OkResponse(ok=False, reason="Введи название челленджа")
    if ch_type not in ("weekly_runs", "daily_km", "weekly_km", "monthly_km", "race"):
        return OkResponse(ok=False, reason="Неизвестный тип челленджа")

    # Парсим поля
    goal_runs           = int(body.get("goal_runs") or 0)
    goal_value          = float(body.get("goal_value") or 0)
    min_per_run         = float(body.get("min_per_run") or 0)
    min_minutes_per_run = int(body.get("min_minutes_per_run") or 0)
    penalty             = (body.get("penalty") or "").strip() or None
    is_public           = bool(body.get("is_public", True))
    started_at          = datetime.now()

    # Дедлайн
    deadline: datetime | None = None
    if ch_type in _SPRINT_DAYS:
        deadline = started_at + timedelta(days=_SPRINT_DAYS[ch_type])
    elif ch_type in ("weekly_runs", "race") and body.get("deadline"):
        try:
            deadline = datetime.strptime(body["deadline"], "%d.%m.%Y")
        except ValueError:
            return OkResponse(ok=False, reason="Неверный формат даты. Используй ДД.ММ.ГГГГ")
        if deadline < started_at:
            return OkResponse(ok=False, reason="Дата не может быть в прошлом")

    # Валидация по типу
    if ch_type == "weekly_runs" and goal_runs <= 0:
        return OkResponse(ok=False, reason="Укажи количество пробежек в неделю")
    if ch_type in ("daily_km", "weekly_km", "monthly_km", "race") and goal_value <= 0:
        return OkResponse(ok=False, reason="Укажи целевую дистанцию")

    ch = Challenge(
        user_id=user_id,
        title=title,
        ch_type=ch_type,
        min_per_run=min_per_run,
        min_minutes_per_run=min_minutes_per_run,
        goal_runs=goal_runs,
        goal_value=goal_value,
        penalty=penalty,
        is_public=is_public,
        is_active=True,
        started_at=started_at,
        deadline=deadline,
    )
    db.add(ch)
    await db.commit()
    return OkResponse(ok=True, reason="Челлендж создан!")


# ─── Присоединиться ──────────────────────────────────────────

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


# ─── Покинуть (участник) ─────────────────────────────────────

@router.post("/{challenge_id}/leave", response_model=OkResponse)
async def leave_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]

    part_res = await db.execute(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == challenge_id,
            ChallengeParticipant.user_id == user_id,
        )
    )
    part = part_res.scalar_one_or_none()
    if not part:
        return OkResponse(ok=False, reason="Ты не участвуешь в этом челлендже.")

    await db.delete(part)
    await db.commit()
    return OkResponse(ok=True, reason="Ты вышел из челленджа.")


# ─── Закрыть свой (автор) ────────────────────────────────────

@router.post("/{challenge_id}/close", response_model=OkResponse)
async def close_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]

    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return OkResponse(ok=False, reason="Челлендж не найден.")
    if ch.user_id != user_id:
        return OkResponse(ok=False, reason="Только автор может закрыть челлендж.")
    if not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж уже завершён.")

    ch.is_active = False
    await db.commit()
    return OkResponse(ok=True, reason="Челлендж завершён.")