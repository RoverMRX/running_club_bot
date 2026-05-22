"""routers/events.py — мероприятия."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from database import get_db
from auth import get_current_user
from schemas import (
    EventOut, EventParticipantOut, EventTemplateOut,
    CreateEventRequest, OkResponse,
)
from notify import queue_message, queue_message_to_admins

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import Event, EventParticipant, EventTemplate, User, Moderator

router = APIRouter(prefix="/events", tags=["events"])


# ─── helpers ─────────────────────────────────────────────────

def _format_announce(ev: Event) -> str:
    date_str = ev.event_date.strftime("%d.%m.%Y в %H:%M") if ev.event_date else "—"
    lines = [f"📅 <b>{ev.title}</b>", "", f"🗓 <b>Дата:</b> {date_str}"]
    if ev.location:
        lines.append(f"📍 <b>Место:</b> {ev.location}")
    if ev.distance_km:
        lines.append(f"🏃 <b>Дистанция:</b> {ev.distance_km} км")
    if ev.description:
        lines += ["", ev.description]
    lines += ["", f"⭐ <b>XP за участие:</b> +{ev.xp_bonus} (×{ev.xp_multiplier} за км)"]
    return "\n".join(lines)


async def _enrich_event(
    ev: Event,
    db: AsyncSession,
    user_id: int | None = None,
    with_participants: bool = False,
) -> EventOut:
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
        user_status = us_res.scalar_one_or_none()

    created_by_nick = None
    if ev.created_by:
        nick_res = await db.execute(
            select(User.school_nick).where(User.tg_id == ev.created_by)
        )
        created_by_nick = nick_res.scalar_one_or_none()

    participants: list[EventParticipantOut] = []
    if with_participants:
        p_res = await db.execute(
            select(EventParticipant, User)
            .join(User, User.tg_id == EventParticipant.user_tg_id)
            .where(EventParticipant.event_id == ev.id)
            .order_by(EventParticipant.registered_at.asc())
        )
        for ep, u in p_res.all():
            participants.append(EventParticipantOut(
                tg_id=u.tg_id,
                username=u.username,
                school_nick=u.school_nick,
                status=ep.status,
            ))

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
        created_by=ev.created_by,
        created_by_nick=created_by_nick,
        participants=participants,
    )


# ─── Шаблоны ─────────────────────────────────────────────────

@router.get("/templates", response_model=list[EventTemplateOut])
async def get_templates(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventTemplateOut]:
    res = await db.execute(
        select(EventTemplate)
        .where(EventTemplate.is_active == True)
        .order_by(EventTemplate.name.asc())
    )
    return [
        EventTemplateOut(
            id=t.id, name=t.name, description=t.description,
            location=t.location, distance_km=t.distance_km,
            xp_bonus=t.xp_bonus or 100, xp_multiplier=t.xp_multiplier or 1.5,
            is_external=t.is_external or False,
        )
        for t in res.scalars().all()
    ]


# ─── Список мероприятий ──────────────────────────────────────

@router.get("", response_model=list[EventOut])
async def get_events(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    upcoming_only: bool = True,
) -> list[EventOut]:
    user_id = tg_user["id"]
    q = select(Event).where(Event.is_active == True)

    if upcoming_only:
        q = q.where(
            or_(Event.is_pending == False, Event.created_by == user_id),
            Event.event_date >= datetime.now(),
        ).order_by(Event.event_date.asc())
    else:
        q = q.where(
            Event.is_pending == False,
            Event.event_date < datetime.now(),
        ).order_by(Event.event_date.desc())

    res = await db.execute(q)
    return [await _enrich_event(ev, db, user_id) for ev in res.scalars().all()]


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    ev_res = await db.execute(select(Event).where(Event.id == event_id))
    ev = ev_res.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")
    return await _enrich_event(ev, db, tg_user["id"], with_participants=True)


# ─── Создание ────────────────────────────────────────────────

@router.post("", response_model=OkResponse)
async def create_event(
    body: CreateEventRequest,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]

    try:
        event_date = datetime.strptime(body.event_date, "%d.%m.%Y %H:%M")
    except ValueError:
        return OkResponse(ok=False, reason="Неверный формат даты. Используй ДД.ММ.ГГГГ ЧЧ:ММ")

    if event_date < datetime.now():
        return OkResponse(ok=False, reason="Дата не может быть в прошлом")

    title = body.title
    description = body.description
    location = body.location
    distance_km = body.distance_km
    xp_bonus = body.xp_bonus
    xp_multiplier = body.xp_multiplier

    if body.template_id:
        tpl_res = await db.execute(
            select(EventTemplate).where(EventTemplate.id == body.template_id)
        )
        tpl = tpl_res.scalar_one_or_none()
        if tpl:
            title         = body.title or tpl.name
            description   = body.description if body.description is not None else tpl.description
            location      = body.location    if body.location    is not None else tpl.location
            distance_km   = body.distance_km if body.distance_km is not None else tpl.distance_km
            xp_bonus      = tpl.xp_bonus      or 100
            xp_multiplier = tpl.xp_multiplier or 1.5

    ev = Event(
        title=title, description=description, location=location,
        event_date=event_date, distance_km=distance_km,
        created_by=user_id, is_active=True, is_pending=True,
        xp_bonus=xp_bonus, xp_multiplier=xp_multiplier,
        template_id=body.template_id,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    # Уведомляем модераторов через очередь (бот отправит сам)
    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(
            text="📢 Опубликовать в основную группу",
            callback_data=f"evt_pub_main:{ev.id}",
        )
        kb_builder.button(text="❌ Отклонить", callback_data=f"evt_reject:{ev.id}")
        kb_builder.adjust(1)

        nick_res = await db.execute(select(User.school_nick).where(User.tg_id == user_id))
        author_nick = nick_res.scalar_one_or_none() or f"ID {user_id}"

        msg_text = (
            f"🆕 <b>Новое мероприятие на модерации</b>\n\n"
            f"{_format_announce(ev)}\n\n"
            f"Создал: <b>{author_nick}</b>"
        )
        await queue_message_to_admins(db, msg_text, kb_builder.as_markup())
        await db.commit()
    except Exception as e:
        import logging
        logging.getLogger("events").warning(f"Ошибка постановки уведомления: {e}")

    return OkResponse(ok=True, reason="Мероприятие отправлено на модерацию!")


# ─── Участие ─────────────────────────────────────────────────

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
        db.add(EventParticipant(event_id=event_id, user_tg_id=user_id, status="going"))
    await db.commit()

    if ev.created_by and ev.created_by != user_id:
        nick_res = await db.execute(select(User.school_nick).where(User.tg_id == user_id))
        nick = nick_res.scalar_one_or_none() or "Участник"
        await queue_message(
            db, ev.created_by,
            f"🏃 <b>{nick}</b> записался на твоё мероприятие «{ev.title}»!",
        )
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