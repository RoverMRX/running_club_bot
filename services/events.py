"""services/events.py — сервисный слой для мероприятий."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from aiogram import Bot
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    EVENTS_THREAD_ID,
    GROUP_ID,
    SECONDARY_GROUP_ID,
    SECONDARY_THREAD_ID,
)
from models import Event, EventParticipant, EventTemplate, Moderator


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


# ── Роли ─────────────────────────────────────────────────────

async def is_moderator(session: AsyncSession, tg_id: int) -> bool:
    result = await session.execute(
        select(Moderator).where(Moderator.tg_id == tg_id)
    )
    return result.scalar_one_or_none() is not None


# ── Шаблоны ──────────────────────────────────────────────────

async def create_event_template(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
    location: str | None,
    distance_km: float | None,
    is_external: bool,
    xp_bonus: int,
    xp_multiplier: float,
    created_by: int,
) -> EventTemplate:
    tpl = EventTemplate(
        name=name,
        description=description,
        location=location,
        distance_km=distance_km,
        is_external=is_external,
        xp_bonus=xp_bonus,
        xp_multiplier=xp_multiplier,
        created_by=created_by,
        is_active=True,
        created_at=_now(),
    )
    session.add(tpl)
    await session.commit()
    await session.refresh(tpl)
    return tpl


async def get_templates(session: AsyncSession) -> list[EventTemplate]:
    result = await session.execute(
        select(EventTemplate)
        .where(EventTemplate.is_active == True)  # noqa: E712
        .order_by(EventTemplate.created_at.desc())
    )
    return list(result.scalars().all())


async def get_template(session: AsyncSession, template_id: int) -> EventTemplate | None:
    return await session.get(EventTemplate, template_id)


# ── Мероприятия ──────────────────────────────────────────────

async def create_event_from_template(
    session: AsyncSession,
    *,
    template_id: int,
    event_date: datetime,
    created_by: int,
    # override-поля — если пользователь поправил при создании
    location: str | None = ...,       # type: ignore[assignment]
    distance_km: float | None = ...,  # type: ignore[assignment]
) -> Event:
    """
    Создаёт мероприятие на основе шаблона.
    location и distance_km берутся из шаблона, если не переданы явно
    (передать None — значит явно очистить поле).
    """
    tpl = await session.get(EventTemplate, template_id)
    if tpl is None:
        raise ValueError(f"Шаблон #{template_id} не найден")

    # Sentinel-паттерн: ... = не задано → берём из шаблона
    resolved_location    = tpl.location    if location    is ... else location
    resolved_distance_km = tpl.distance_km if distance_km is ... else distance_km

    event = Event(
        template_id=tpl.id,
        title=tpl.name,
        description=tpl.description,
        location=resolved_location,
        distance_km=resolved_distance_km,
        event_date=event_date,
        created_by=created_by,
        xp_bonus=tpl.xp_bonus,
        xp_multiplier=tpl.xp_multiplier,
        is_active=True,
        is_pending=True,
        created_at=_now(),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def create_event(
    session: AsyncSession,
    *,
    title: str,
    description: str | None,
    location: str | None,
    event_date: datetime,
    distance_km: float | None,
    created_by: int,
) -> Event:
    """Создаёт мероприятие вручную (без шаблона)."""
    event = Event(
        title=title,
        description=description,
        location=location,
        event_date=event_date,
        distance_km=distance_km,
        created_by=created_by,
        xp_bonus=100,
        xp_multiplier=1.5,
        is_active=True,
        is_pending=True,
        created_at=_now(),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def get_event(session: AsyncSession, event_id: int) -> Event | None:
    return await session.get(Event, event_id)


async def get_upcoming_events(session: AsyncSession) -> list[Event]:
    """Ближайшие опубликованные мероприятия (не на модерации)."""
    result = await session.execute(
        select(Event)
        .where(
            Event.is_active == True,    # noqa: E712
            Event.is_pending == False,  # noqa: E712
            Event.event_date >= _now(),
        )
        .order_by(Event.event_date.asc())
    )
    return list(result.scalars().all())


async def get_pending_events(session: AsyncSession) -> list[Event]:
    """Мероприятия, ожидающие публикации."""
    result = await session.execute(
        select(Event)
        .where(Event.is_pending == True)  # noqa: E712
        .order_by(Event.created_at.desc())
    )
    return list(result.scalars().all())


# ── Участие ──────────────────────────────────────────────────

StatusT = Literal["going", "not_going"]


async def join_event(
    session: AsyncSession,
    *,
    event_id: int,
    user_tg_id: int,
    status: StatusT,
) -> EventParticipant:
    result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_tg_id == user_tg_id,
        )
    )
    participant = result.scalar_one_or_none()

    if participant is None:
        participant = EventParticipant(
            event_id=event_id,
            user_tg_id=user_tg_id,
            status=status,
            registered_at=_now(),
        )
        session.add(participant)
    else:
        participant.status = status

    await session.commit()
    await session.refresh(participant)
    return participant


async def get_participant_counts(session: AsyncSession, event_id: int) -> tuple[int, int]:
    going_q = await session.execute(
        select(func.count(EventParticipant.id)).where(
            EventParticipant.event_id == event_id,
            EventParticipant.status == "going",
        )
    )
    not_going_q = await session.execute(
        select(func.count(EventParticipant.id)).where(
            EventParticipant.event_id == event_id,
            EventParticipant.status == "not_going",
        )
    )
    return going_q.scalar_one(), not_going_q.scalar_one()


# ── Форматирование ────────────────────────────────────────────

def format_announce(event: Event) -> str:
    date_str = event.event_date.strftime("%d.%m.%Y в %H:%M")
    lines = [f"📅 <b>{event.title}</b>", "", f"🗓 <b>Дата:</b> {date_str}"]
    if event.location:
        lines.append(f"📍 <b>Место:</b> {event.location}")
    if event.distance_km:
        lines.append(f"🏃 <b>Дистанция:</b> {event.distance_km} км")
    if event.description:
        lines += ["", event.description]
    lines += [
        "",
        f"⭐ <b>XP за участие:</b> +{event.xp_bonus} (×{event.xp_multiplier} за км)",
    ]
    return "\n".join(lines)


# ── Публикация ────────────────────────────────────────────────

async def publish_to_main_group(
    session: AsyncSession,
    event_id: int,
    bot: Bot,
) -> int:
    """Публикует анонс в основную группу с кнопками участия. Возвращает message_id."""
    from keyboards import get_event_participants_kb

    event = await session.get(Event, event_id)
    if event is None:
        raise ValueError(f"Мероприятие #{event_id} не найдено")

    text = format_announce(event)
    going, not_going = await get_participant_counts(session, event_id)
    kb = get_event_participants_kb(event_id, going, not_going)

    msg = await bot.send_message(
        chat_id=GROUP_ID,
        text=text,
        reply_markup=kb,
        message_thread_id=EVENTS_THREAD_ID,
        parse_mode="HTML",
    )
    event.announce_msg_id = msg.message_id
    event.is_pending = False
    await session.commit()
    return msg.message_id


async def publish_to_secondary_group(
    session: AsyncSession,
    event_id: int,
    bot: Bot,
    club_invite_link: str = "https://t.me/+HLikNXKlA3YwNDRi",
) -> int:
    """Публикует анонс во все вторичные группы из SECONDARY_TARGETS. Возвращает последний message_id."""
    from config import SECONDARY_TARGETS
    event = await session.get(Event, event_id)
    if event is None:
        raise ValueError(f"Мероприятие #{event_id} не найдено")

    text = (
        f"{format_announce(event)}\n\n"
        f"👟 Хочешь бегать вместе? Вступай в клуб: {club_invite_link}"
    )

    last_msg_id = 0
    for group_id, thread_id in SECONDARY_TARGETS:
        try:
            msg = await bot.send_message(
                chat_id=group_id,
                text=text,
                message_thread_id=thread_id if thread_id and thread_id != 1 else None,
                parse_mode="HTML",
            )
            last_msg_id = msg.message_id
        except Exception as e:
            import logging
            logging.getLogger("events").warning(
                "Не удалось опубликовать в группу %s тред %s: %s", group_id, thread_id, e
            )

    event.repost_msg_id = last_msg_id
    await session.commit()
    return last_msg_id