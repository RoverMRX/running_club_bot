"""routers/events.py — мероприятия."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from auth import get_current_user
from schemas import EventOut, CreateEventRequest, OkResponse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import Event, EventParticipant, User

router = APIRouter(prefix="/events", tags=["events"])


async def _enrich_event(ev: Event, db: AsyncSession, user_id: int | None = None) -> EventOut:
    going_res = await db.execute(
        select(func.count()).where(
            EventParticipant.event_id == ev.id,
            EventParticipant.status == "going",
        )
    )
    not_going_res = await db.execute(
        select(func.count()).where(
            EventParticipant.event_id == ev.id,
            EventParticipant.status == "not_going",
        )
    )

    user_status = None
    if user_id:
        us_res = await db.execute(
            select(EventParticipant.status).where(
                EventParticipant.event_id == ev.id,
                EventParticipant.user_tg_id == user_id,
            )
        )
        row = us_res.scalar_one_or_none()
        user_status = row if row else None

    return EventOut(
        id=ev.id,
        title=ev.title,
        description=ev.description,
        location=ev.location,
        event_date=ev.event_date,
        distance_km=ev.distance_km,
        xp_bonus=ev.xp_bonus or 0,
        xp_multiplier=ev.xp_multiplier or 1.0,
        is_active=ev.is_active,
        is_pending=ev.is_pending,
        going_count=going_res.scalar() or 0,
        not_going_count=not_going_res.scalar() or 0,
        user_status=user_status,
    )


# ─── Список мероприятий ──────────────────────────────────────

@router.get("", response_model=list[EventOut])
async def get_events(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    upcoming_only: bool = True,
) -> list[EventOut]:
    """Ближайшие мероприятия."""
    q = select(Event).where(
        Event.is_active == True,
        Event.is_pending == False,
    )
    if upcoming_only:
        q = q.where(Event.event_date >= datetime.now())
    q = q.order_by(Event.event_date.asc())
    res = await db.execute(q)
    events = res.scalars().all()
    return [await _enrich_event(ev, db, tg_user["id"]) for ev in events]


@router.get("/pending", response_model=list[EventOut])
async def get_pending_events(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventOut]:
    """Мероприятия на модерации (только для админа/модератора)."""
    from config import ADMIN_IDS
    user_id = tg_user["id"]

    # Проверяем права
    is_admin = user_id in ADMIN_IDS
    if not is_admin:
        # Проверяем модератора через БД
        from models import Moderator
        mod_res = await db.execute(select(Moderator).where(Moderator.tg_id == user_id))
        if not mod_res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Нет прав")

    res = await db.execute(
        select(Event).where(Event.is_pending == True).order_by(Event.created_at.desc())
    )
    events = res.scalars().all()
    return [await _enrich_event(ev, db, user_id) for ev in events]


# ─── Создание мероприятия ────────────────────────────────────

@router.post("", response_model=OkResponse)
async def create_event(
    body: CreateEventRequest,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Создать мероприятие (уходит на модерацию)."""
    user_id = tg_user["id"]

    try:
        event_date = datetime.strptime(body.event_date, "%d.%m.%Y %H:%M")
    except ValueError:
        return OkResponse(ok=False, reason="Неверный формат даты. Используй ДД.ММ.ГГГГ ЧЧ:ММ")

    ev = Event(
        title=body.title,
        description=body.description,
        location=body.location,
        event_date=event_date,
        distance_km=body.distance_km,
        created_by=user_id,
        is_active=True,
        is_pending=True,  # ждёт модерации
        xp_bonus=100,
        xp_multiplier=1.5,
    )
    db.add(ev)
    await db.commit()
    return OkResponse(ok=True, reason="Мероприятие отправлено на модерацию!")


# ─── Регистрация на мероприятие ──────────────────────────────

@router.post("/{event_id}/join", response_model=OkResponse)
async def join_event(
    event_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]

    ev_res = await db.execute(select(Event).where(Event.id == event_id))
    ev = ev_res.scalar_one_or_none()
    if not ev or not ev.is_active or ev.is_pending:
        return OkResponse(ok=False, reason="Мероприятие не найдено.")

    part_res = await db.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_tg_id == user_id,
        )
    )
    participant = part_res.scalar_one_or_none()
    if participant:
        participant.status = "going"
    else:
        db.add(EventParticipant(
            event_id=event_id,
            user_tg_id=user_id,
            status="going",
        ))
    await db.commit()
    return OkResponse(ok=True, reason="Ты зарегистрирован!")


@router.post("/{event_id}/leave", response_model=OkResponse)
async def leave_event(
    event_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]
    part_res = await db.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_tg_id == user_id,
        )
    )
    participant = part_res.scalar_one_or_none()
    if participant:
        participant.status = "not_going"
        await db.commit()
    return OkResponse(ok=True, reason="Ты отменил участие.")


# ─── Модерация (апрув/отклонение) ───────────────────────────

@router.post("/{event_id}/approve", response_model=OkResponse)
async def approve_event(
    event_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Опубликовать мероприятие (только модератор/админ)."""
    from config import ADMIN_IDS
    user_id = tg_user["id"]
    is_admin = user_id in ADMIN_IDS
    if not is_admin:
        from models import Moderator
        mod_res = await db.execute(select(Moderator).where(Moderator.tg_id == user_id))
        if not mod_res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Нет прав")

    ev_res = await db.execute(select(Event).where(Event.id == event_id))
    ev = ev_res.scalar_one_or_none()
    if not ev:
        return OkResponse(ok=False, reason="Мероприятие не найдено.")

    ev.is_pending = False
    await db.commit()
    return OkResponse(ok=True, reason="Мероприятие опубликовано!")


@router.post("/{event_id}/reject", response_model=OkResponse)
async def reject_event(
    event_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Отклонить мероприятие (только модератор/админ)."""
    from config import ADMIN_IDS
    user_id = tg_user["id"]
    is_admin = user_id in ADMIN_IDS
    if not is_admin:
        from models import Moderator
        mod_res = await db.execute(select(Moderator).where(Moderator.tg_id == user_id))
        if not mod_res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Нет прав")

    ev_res = await db.execute(select(Event).where(Event.id == event_id))
    ev = ev_res.scalar_one_or_none()
    if not ev:
        return OkResponse(ok=False, reason="Мероприятие не найдено.")

    ev.is_active = False
    ev.is_pending = False
    await db.commit()
    return OkResponse(ok=True, reason="Мероприятие отклонено.")