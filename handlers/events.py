"""handlers/events.py — мероприятия, шаблоны, регистрация, анонсы."""

import logging
from datetime import datetime
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

import config
from database import async_session
from models import User, Event, EventTemplate, EventParticipant
from keyboards import get_main_kb, get_cancel_kb, get_event_participants_kb

router = Router()
log = logging.getLogger(__name__)


class EventSetup(StatesGroup):
    title = State()
    description = State()
    location = State()
    event_date = State()
    distance = State()


class TemplateSetup(StatesGroup):
    name = State()
    description = State()
    rules = State()
    is_external = State()
    xp_bonus = State()
    xp_multiplier = State()


# ──────────────────────────────────────────
# Список мероприятий
# ──────────────────────────────────────────

@router.message(F.text == "📅 Мероприятия")
async def cmd_events(message: types.Message):
    """Показывает грядущие мероприятия."""
    async with async_session() as session:
        ev_res = await session.execute(
            select(Event)
            .where(Event.is_active == True, Event.event_date >= datetime.now())
            .order_by(Event.event_date)
            .limit(10)
        )
        events = ev_res.scalars().all()

        if not events:
            return await message.answer(
                "📅 Ближайших мероприятий пока нет.\nСледи за анонсами! 🏃"
            )

        for ev in events:
            # Считаем участников
            part_res = await session.execute(
                select(func.count(EventParticipant.id)).where(
                    EventParticipant.event_id == ev.id,
                    EventParticipant.status == "going",
                )
            )
            going = part_res.scalar()

            skip_res = await session.execute(
                select(func.count(EventParticipant.id)).where(
                    EventParticipant.event_id == ev.id,
                    EventParticipant.status == "not_going",
                )
            )
            skipping = skip_res.scalar()

            # Проверяем статус текущего пользователя
            my_res = await session.execute(
                select(EventParticipant).where(
                    EventParticipant.event_id == ev.id,
                    EventParticipant.user_tg_id == message.from_user.id,
                )
            )
            my_status = my_res.scalar_one_or_none()
            joined = my_status and my_status.status == "going"

            date_str = ev.event_date.strftime("%d.%m %H:%M")
            loc_str = f"\n📍 {ev.location}" if ev.location else ""
            dist_str = f"\n🏁 {ev.distance_km} км" if ev.distance_km else ""
            desc_str = f"\n\n{ev.description}" if ev.description else ""

            text = (
                f"📅 <b>{ev.title}</b>\n"
                f"⏰ {date_str}{loc_str}{dist_str}{desc_str}"
            )
            await message.answer(
                text,
                reply_markup=get_event_participants_kb(ev.id, going, skipping),
            )


# ──────────────────────────────────────────
# Регистрация на мероприятие
# ──────────────────────────────────────────

@router.callback_query(F.data.startswith("event_join:"))
async def cb_event_join(callback: types.CallbackQuery):
    """Участник записывается на мероприятие."""
    event_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        async with session.begin():
            # Создаём пользователя если нужно
            u_res = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
            user = u_res.scalar_one_or_none()
            if not user:
                user = User(
                    tg_id=callback.from_user.id,
                    username=callback.from_user.username,
                    full_name=callback.from_user.full_name,
                )
                session.add(user)
                await session.flush()

            # Проверяем уже ли записан
            part_res = await session.execute(
                select(EventParticipant).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.user_tg_id == callback.from_user.id,
                )
            )
            existing = part_res.scalar_one_or_none()

            if existing:
                if existing.status == "going":
                    return await callback.answer("Ты уже записан!")
                else:
                    # Было "не пойду", меняем на "пойду"
                    existing.status = "going"
            else:
                part = EventParticipant(
                    event_id=event_id,
                    user_tg_id=callback.from_user.id,
                    status="going",
                )
                session.add(part)

            await session.flush()

            # Считаем участников
            going_res = await session.execute(
                select(func.count(EventParticipant.id)).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.status == "going",
                )
            )
            going = going_res.scalar()

            skip_res = await session.execute(
                select(func.count(EventParticipant.id)).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.status == "not_going",
                )
            )
            skipping = skip_res.scalar()

    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_event_participants_kb(event_id, going, skipping)
        )
    except Exception:
        pass

    await callback.answer(f"✅ Записал тебя! ({going} участников)")


@router.callback_query(F.data.startswith("event_skip:"))
async def cb_event_skip(callback: types.CallbackQuery):
    """Участник говорит что не пойдёт."""
    event_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        async with session.begin():
            u_res = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
            user = u_res.scalar_one_or_none()
            if not user:
                user = User(
                    tg_id=callback.from_user.id,
                    username=callback.from_user.username,
                    full_name=callback.from_user.full_name,
                )
                session.add(user)
                await session.flush()

            part_res = await session.execute(
                select(EventParticipant).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.user_tg_id == callback.from_user.id,
                )
            )
            existing = part_res.scalar_one_or_none()

            if existing:
                existing.status = "not_going"
            else:
                try:
                    part = EventParticipant(
                        event_id=event_id,
                        user_tg_id=callback.from_user.id,
                        status="not_going",
                    )
                    session.add(part)
                except IntegrityError:
                    await session.rollback()
                    return await callback.answer("Ошибка.")

            await session.flush()

            going_res = await session.execute(
                select(func.count(EventParticipant.id)).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.status == "going",
                )
            )
            going = going_res.scalar()

            skip_res = await session.execute(
                select(func.count(EventParticipant.id)).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.status == "not_going",
                )
            )
            skipping = skip_res.scalar()

    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_event_participants_kb(event_id, going, skipping)
        )
    except Exception:
        pass

    await callback.answer("Записал что не пойдёшь 👍")


# ──────────────────────────────────────────
# Создание мероприятия (админ)
# ──────────────────────────────────────────

async def start_event_creation(message: types.Message, state: FSMContext, from_template: int = None):
    """Начало создания мероприятия."""
    if message.chat.type != "private":
        return await message.reply("Создание мероприятия — только в личке!")
    
    if from_template:
        await state.update_data(template_id=from_template)
    
    await state.set_state(EventSetup.title)
    await message.answer(
        "📅 <b>Создание мероприятия</b>\n\n"
        "Название (например: «Long Run 10км»):",
        reply_markup=get_cancel_kb(),
    )


@router.message(EventSetup.title)
async def ev_title(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    await state.update_data(title=message.text.strip())
    await state.set_state(EventSetup.description)
    await message.answer("Описание (или «-» пропустить):", reply_markup=get_cancel_kb())


@router.message(EventSetup.description)
async def ev_desc(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    desc = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(description=desc)
    await state.set_state(EventSetup.location)
    await message.answer("Место (или «-»):", reply_markup=get_cancel_kb())


@router.message(EventSetup.location)
async def ev_location(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    loc = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(location=loc)
    await state.set_state(EventSetup.event_date)
    await message.answer(
        "Дата и время в формате <b>ДД.ММ.ГГГГ ЧЧ:ММ</b>\n"
        "Например: 22.06.2025 09:00",
        reply_markup=get_cancel_kb(),
    )


@router.message(EventSetup.event_date)
async def ev_date(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        return await message.answer("Неверный формат. Попробуй: 22.06.2025 09:00")
    await state.update_data(event_date=dt)
    await state.set_state(EventSetup.distance)
    await message.answer("Дистанция в км (или «-»):", reply_markup=get_cancel_kb())


@router.message(EventSetup.distance)
async def ev_distance(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    
    dist = None
    if message.text.strip() != "-":
        try:
            dist = float(message.text.replace(",", "."))
        except ValueError:
            return await message.answer("Введи число или «-».")
    
    data = await state.get_data()
    async with async_session() as session:
        async with session.begin():
            ev = Event(
                title=data["title"],
                description=data.get("description"),
                location=data.get("location"),
                event_date=data["event_date"],
                distance_km=dist,
                created_by=message.from_user.id,
            )
            session.add(ev)
            await session.flush()
            ev_id = ev.id

    await state.clear()
    date_str = data["event_date"].strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"✅ Мероприятие создано!\n\n"
        f"📅 <b>{data['title']}</b>\n⏰ {date_str}",
        reply_markup=get_main_kb(),
    )

    # Анонс в группу + репост во вторую группу
    if config.GROUP_ID:
        loc_str = f"\n📍 {data['location']}" if data.get("location") else ""
        dist_str = f"\n🏁 {dist} км" if dist else ""
        desc_str = f"\n\n{data['description']}" if data.get("description") else ""
        
        text = (
            f"📣 <b>АНОНС: {data['title']}</b>\n"
            f"⏰ {date_str}{loc_str}{dist_str}{desc_str}\n\n"
            f"Записаться: /events"
        )
        
        try:
            msg = await bot.send_message(
                config.GROUP_ID,
                text,
                message_thread_id=config.EVENTS_THREAD_ID,
            )
            
            # Репост во вторую группу
            if config.SECONDARY_GROUP_ID:
                try:
                    await bot.forward_message(
                        config.SECONDARY_GROUP_ID,
                        from_chat_id=msg.chat.id,
                        message_id=msg.message_id,
                        message_thread_id=config.SECONDARY_THREAD_ID,
                    )
                except Exception as e:
                    log.error(f"Ошибка репоста: {e}")
        except Exception as e:
            log.error(f"Ошибка отправки анонса: {e}")