"""
handlers.py — вся бизнес-логика бота IT БЕГОТНЯ 21.

Структура:
  1. FSM-состояния
  2. Вспомогательные функции
  3. /start, главное меню
  4. Профиль и таблица лидеров
  5. Создание челленджа (FSM)
  6. Peer Review: приём и голосование за отчёты
  7. Мероприятия (Events)
  8. Еженедельный дайджест
  9. Сброс стриков (планировщик)
 10. Прочее (помощь, отмена)
"""

import logging
from datetime import datetime, timedelta

from aiogram import Router, types, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

import config
from database import async_session
from models import User, Challenge, Report, Vote, Event, EventParticipant
from keyboards import (
    get_main_kb, get_cancel_kb, get_challenge_type_kb,
    get_report_kb, get_report_approved_kb, get_event_kb,
)

router = Router()
log = logging.getLogger(__name__)


# ============================================================
# 1. FSM-состояния
# ============================================================

class ChallengeSetup(StatesGroup):
    title = State()
    ch_type = State()
    min_dist = State()
    target = State()
    penalty = State()


class EventCreate(StatesGroup):
    title = State()
    description = State()
    location = State()
    event_date = State()   # формат: "ДД.ММ.ГГГГ ЧЧ:ММ"
    distance = State()


# ============================================================
# 2. Вспомогательные функции
# ============================================================

async def get_or_create_user(session, tg_user: types.User) -> User:
    """Возвращает пользователя из БД или создаёт нового."""
    res = await session.execute(select(User).where(User.tg_id == tg_user.id))
    user = res.scalar_one_or_none()
    if not user:
        user = User(
            tg_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            xp=0,
            streak=0,
        )
        session.add(user)
        await session.flush()
    return user


def xp_to_level(xp: int) -> str:
    if xp < 500:
        return "🌱 Новичок (Seed)"
    if xp < 2000:
        return "🌿 Бегун (Sprout)"
    return "🌳 Атлет (Tree)"


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _approve_report(session, report: Report, bot: Bot) -> None:
    """Зачисляет XP и км в активные цели атлета после одобрения отчёта."""
    km = report.km
    xp_gain = int(km * config.XP_PER_KM)

    # Обновляем XP пользователя
    res = await session.execute(select(User).where(User.tg_id == report.user_tg_id))
    user = res.scalar_one_or_none()
    if user:
        user.xp += xp_gain

    # Обновляем прогресс по каждому активному челленджу
    ch_res = await session.execute(
        select(Challenge).where(
            Challenge.user_id == report.user_tg_id,
            Challenge.is_active == True,
        )
    )
    for ch in ch_res.scalars().all():
        if km >= ch.min_per_run:
            ch.current_runs += 1
            ch.current_value += km

            # Для разовой цели — проверяем завершение
            if ch.ch_type == "goal" and ch.current_value >= ch.goal_value:
                ch.is_active = False
                try:
                    await bot.send_message(
                        report.user_tg_id,
                        f"🎯 <b>Цель «{ch.title}» выполнена!</b>\n"
                        f"Суммарно: {ch.current_value:.1f} км — молодец! 💪",
                    )
                except Exception:
                    pass

    report.is_approved = True
    await session.flush()


# ============================================================
# 3. /start и базовая регистрация
# ============================================================

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        async with session.begin():
            await get_or_create_user(session, message.from_user)

    name = message.from_user.first_name or "атлет"
    await message.answer(
        f"👋 Привет, <b>{name}</b>!\n\n"
        "Добро пожаловать в <b>IT БЕГОТНЯ 21</b> — беговой клуб айтишников.\n\n"
        "Здесь ты можешь:\n"
        "• Поставить себе цель и отчитываться перед командой\n"
        "• Следить за стриком и таблицей лидеров\n"
        "• Участвовать в мероприятиях клуба\n\n"
        "Выбери действие в меню ниже 👇",
        reply_markup=get_main_kb(),
    )


# ============================================================
# 4. Профиль и таблица лидеров
# ============================================================

@router.message(F.text == "👤 Мой профиль")
async def cmd_profile(message: types.Message):
    async with async_session() as session:
        res = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = res.scalar_one_or_none()
        if not user:
            return await message.answer("Сначала напиши /start!")

        ch_res = await session.execute(
            select(Challenge).where(
                Challenge.user_id == message.from_user.id,
                Challenge.is_active == True,
            )
        )
        active = ch_res.scalars().all()

    lines = [
        f"👤 <b>{user.full_name}</b>",
        f"💠 XP: <b>{user.xp}</b>  |  {xp_to_level(user.xp)}",
        f"🔥 Стрик: <b>{user.streak} нед.</b>",
        "────────────────",
    ]

    if active:
        lines.append("<b>Активные цели:</b>")
        for ch in active:
            icon = "📜" if ch.ch_type == "contract" else "🎯"
            if ch.ch_type == "contract":
                progress = f"{ch.current_runs}/{ch.goal_runs} тренировок ({ch.current_value:.1f} км)"
            else:
                progress = f"{ch.current_value:.1f}/{ch.goal_value:.1f} км"
            lines.append(f"{icon} <b>{ch.title}</b>")
            lines.append(f"   └ {progress}")
            if ch.penalty:
                lines.append(f"   💰 Цена слова: {ch.penalty}")
    else:
        lines.append("Нет активных целей. Нажми «🏃 Создать челлендж»!")

    await message.answer("\n".join(lines), reply_markup=get_main_kb())


@router.message(F.text == "📊 Таблица лидеров")
async def cmd_leaderboard(message: types.Message):
    async with async_session() as session:
        res = await session.execute(select(User).order_by(User.xp.desc()).limit(10))
        users = res.scalars().all()

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>ТОП АТЛЕТОВ КЛУБА</b>\n"]
    for i, u in enumerate(users, 1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        streak_str = f" 🔥{u.streak}" if u.streak > 0 else ""
        name = f"@{u.username}" if u.username else u.full_name
        lines.append(f"{medal} {name} — <b>{u.xp} XP</b>{streak_str}")

    if not users:
        lines.append("Пока никого нет. Будь первым! 🏃")

    await message.answer("\n".join(lines))


# ============================================================
# 5. Создание челленджа (FSM)
# ============================================================

@router.message(F.text == "🏃 Создать челлендж")
async def start_challenge(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return await message.reply("Создание челленджа — только в личке! Напиши мне в ЛС.")
    await state.set_state(ChallengeSetup.title)
    await message.answer(
        "📝 <b>Создание новой цели</b>\n\n"
        "Введи название (например: «Базовый режим» или «Полумарафон 2025»):",
        reply_markup=get_cancel_kb(),
    )


@router.message(ChallengeSetup.title)
async def ch_title(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    await state.update_data(title=message.text.strip())
    await state.set_state(ChallengeSetup.ch_type)
    await message.answer("Выбери тип цели:", reply_markup=get_challenge_type_kb())


@router.message(ChallengeSetup.ch_type)
async def ch_type(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    if "Регулярность" in message.text or "📜" in message.text:
        ctype = "contract"
        next_prompt = (
            "Минимальная дистанция за <b>одну</b> тренировку (км)?\n"
            "<i>Например: 3</i>"
        )
    else:
        ctype = "goal"
        next_prompt = (
            "Общая дистанция для разовой цели (км)?\n"
            "<i>Например: 42.2 для марафона</i>"
        )
    await state.update_data(ch_type=ctype)
    await state.set_state(ChallengeSetup.min_dist)
    await message.answer(next_prompt, reply_markup=get_cancel_kb())


@router.message(ChallengeSetup.min_dist)
async def ch_min_dist(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    try:
        val = float(message.text.replace(",", "."))
    except ValueError:
        return await message.answer("Введи число, например: <b>5</b> или <b>3.5</b>")
    await state.update_data(min_dist=val)
    data = await state.get_data()
    await state.set_state(ChallengeSetup.target)
    if data["ch_type"] == "contract":
        prompt = "Сколько раз в неделю нужно бегать?\n<i>Например: 3</i>"
    else:
        prompt = "Эта цифра уже введена как суммарная дистанция. Сколько км суммарно?\n<i>Например: 100</i>"
    await message.answer(prompt, reply_markup=get_cancel_kb())


@router.message(ChallengeSetup.target)
async def ch_target(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    try:
        val = float(message.text.replace(",", "."))
    except ValueError:
        return await message.answer("Введи число.")
    await state.update_data(target=val)
    await state.set_state(ChallengeSetup.penalty)
    await message.answer(
        "💰 <b>Цена слова</b> — что будет, если сорвёшь неделю?\n"
        "<i>Например: «Куплю пиццу на всю команду» или «Молчу»</i>",
        reply_markup=get_cancel_kb(),
    )


@router.message(ChallengeSetup.penalty)
async def ch_penalty(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    data = await state.get_data()
    async with async_session() as session:
        async with session.begin():
            await get_or_create_user(session, message.from_user)
            ch = Challenge(
                user_id=message.from_user.id,
                title=data["title"],
                ch_type=data["ch_type"],
                min_per_run=data["min_dist"],
                goal_runs=int(data["target"]) if data["ch_type"] == "contract" else 0,
                goal_value=data["target"] if data["ch_type"] == "goal" else 0.0,
                penalty=message.text.strip(),
                is_active=True,
            )
            session.add(ch)

    await state.clear()
    icon = "📜" if data["ch_type"] == "contract" else "🎯"
    await message.answer(
        f"✅ <b>Цель добавлена!</b>\n\n"
        f"{icon} <b>{data['title']}</b>\n"
        f"Минималка за тренировку: {data['min_dist']} км\n"
        f"💰 Цена слова: {message.text.strip()}",
        reply_markup=get_main_kb(),
    )


# ============================================================
# 6. Peer Review — приём отчётов и голосование
# ============================================================

@router.message(F.photo, F.caption.func(lambda c: c and "#отчет" in c.lower()))
async def handle_report(message: types.Message):
    """Атлет присылает фото с подписью #отчет 7.5"""
    caption = message.caption.lower()
    try:
        raw = caption.replace("#отчет", "").strip()
        km = float(raw.replace(",", ".")) if raw else 1.0
    except ValueError:
        km = 1.0

    async with async_session() as session:
        async with session.begin():
            await get_or_create_user(session, message.from_user)
            report = Report(
                message_id=message.message_id,
                chat_id=message.chat.id,
                user_tg_id=message.from_user.id,
                km=km,
            )
            session.add(report)
            await session.flush()
            report_id = report.id

    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    await message.reply(
        f"🏃 <b>Новый отчёт!</b>\n"
        f"Атлет: {name}\n"
        f"Результат: <b>{km} км</b>\n\n"
        f"Нужно <b>{config.VOTES_REQUIRED}</b> голоса или 1 подтверждение админа.",
        reply_markup=get_report_kb(report_id),
    )


@router.callback_query(F.data.startswith("vote:"))
async def cb_vote(callback: types.CallbackQuery):
    report_id = int(callback.data.split(":")[1])
    voter_id = callback.from_user.id

    async with async_session() as session:
        async with session.begin():
            res = await session.execute(select(Report).where(Report.id == report_id))
            report = res.scalar_one_or_none()

            if not report or report.is_approved:
                return await callback.answer("Отчёт уже закрыт или не найден.")
            if report.user_tg_id == voter_id:
                return await callback.answer("Свой отчёт нельзя подтверждать!")

            # Пытаемся добавить голос — UniqueConstraint в БД страхует от дублей
            try:
                session.add(Vote(report_id=report_id, voter_tg_id=voter_id))
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return await callback.answer("Ты уже голосовал!")

            # Считаем голоса
            count_res = await session.execute(
                select(func.count(Vote.id)).where(Vote.report_id == report_id)
            )
            votes = count_res.scalar()

            if votes >= config.VOTES_REQUIRED:
                await _approve_report(session, report, callback.bot)
                await session.commit()
                name = f"@{callback.from_user.username}" if callback.from_user.username else "Атлет"
                try:
                    await callback.message.edit_text(
                        f"✅ <b>Отчёт принят!</b> ({report.km} км)\n"
                        f"Голосов: {votes}/{config.VOTES_REQUIRED}",
                        reply_markup=get_report_approved_kb(),
                    )
                except TelegramBadRequest:
                    pass
            else:
                await callback.answer(f"Голос принят! ({votes}/{config.VOTES_REQUIRED})")


@router.callback_query(F.data.startswith("adm_approve:"))
async def cb_admin_approve(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("Только для администраторов!")

    report_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        async with session.begin():
            res = await session.execute(select(Report).where(Report.id == report_id))
            report = res.scalar_one_or_none()

            if not report:
                return await callback.answer("Отчёт не найден.")
            if report.is_approved:
                return await callback.answer("Уже принят.")

            await _approve_report(session, report, callback.bot)

        try:
            await callback.message.edit_text(
                f"✅ <b>Отчёт принят администратором!</b> ({report.km} км)",
                reply_markup=get_report_approved_kb(),
            )
        except TelegramBadRequest:
            pass
    await callback.answer("Отчёт одобрен!")


@router.callback_query(F.data.startswith("vote_no:"))
async def cb_vote_no(callback: types.CallbackQuery):
    """Кнопка «Фейк» — пока просто считаем, в будущем можно добавить логику."""
    if not is_admin(callback.from_user.id):
        return await callback.answer("Сообщи об этом администратору.")
    await callback.answer("Пометка «Фейк» зафиксирована. Сообщи в чат.")


@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


# ============================================================
# 7. Мероприятия
# ============================================================

@router.message(F.text == "📅 Мероприятия")
async def cmd_events(message: types.Message):
    async with async_session() as session:
        res = await session.execute(
            select(Event)
            .where(Event.is_active == True, Event.event_date >= datetime.now())
            .order_by(Event.event_date)
            .limit(5)
        )
        events = res.scalars().all()

        if not events:
            return await message.answer(
                "📅 Ближайших мероприятий пока нет.\n"
                "Следи за анонсами в чате!"
            )

        for ev in events:
            # Проверяем, участвует ли пользователь
            part_res = await session.execute(
                select(EventParticipant).where(
                    EventParticipant.event_id == ev.id,
                    EventParticipant.user_tg_id == message.from_user.id,
                )
            )
            joined = part_res.scalar_one_or_none() is not None
            count_res = await session.execute(
                select(func.count(EventParticipant.id)).where(EventParticipant.event_id == ev.id)
            )
            count = count_res.scalar()

            date_str = ev.event_date.strftime("%d.%m.%Y %H:%M")
            dist_str = f"\n🏁 Дистанция: {ev.distance_km} км" if ev.distance_km else ""
            loc_str = f"\n📍 {ev.location}" if ev.location else ""
            desc_str = f"\n\n{ev.description}" if ev.description else ""

            text = (
                f"📅 <b>{ev.title}</b>\n"
                f"⏰ {date_str}{loc_str}{dist_str}{desc_str}\n\n"
                f"👥 Участников: {count}"
            )
            await message.answer(text, reply_markup=get_event_kb(ev.id, joined))


@router.callback_query(F.data.startswith("event_join:"))
async def cb_event_join(callback: types.CallbackQuery):
    event_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        async with session.begin():
            await get_or_create_user(session, callback.from_user)
            try:
                session.add(EventParticipant(
                    event_id=event_id,
                    user_tg_id=callback.from_user.id,
                ))
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return await callback.answer("Ты уже записан!")

            # Обновляем кнопку
            try:
                count_res = await session.execute(
                    select(func.count(EventParticipant.id)).where(EventParticipant.event_id == event_id)
                )
                count = count_res.scalar()
                await callback.message.edit_reply_markup(
                    reply_markup=get_event_kb(event_id, joined=True)
                )
            except TelegramBadRequest:
                pass

    await callback.answer(f"✅ Записал тебя! Участников: {count}")


# ============================================================
# 8. Создание мероприятий (только для админов)
# ============================================================

@router.message(Command("new_event"))
async def cmd_new_event(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(EventCreate.title)
    await message.answer("📅 <b>Новое мероприятие</b>\n\nНазвание:", reply_markup=get_cancel_kb())


@router.message(EventCreate.title)
async def ev_title(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    await state.update_data(title=message.text.strip())
    await state.set_state(EventCreate.description)
    await message.answer("Описание (или «-» пропустить):", reply_markup=get_cancel_kb())


@router.message(EventCreate.description)
async def ev_desc(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    desc = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(description=desc)
    await state.set_state(EventCreate.location)
    await message.answer("Место проведения (или «-»):", reply_markup=get_cancel_kb())


@router.message(EventCreate.location)
async def ev_location(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    loc = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(location=loc)
    await state.set_state(EventCreate.event_date)
    await message.answer(
        "Дата и время в формате <b>ДД.ММ.ГГГГ ЧЧ:ММ</b>\n"
        "<i>Например: 22.06.2025 09:00</i>",
        reply_markup=get_cancel_kb(),
    )


@router.message(EventCreate.event_date)
async def ev_date(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        return await message.answer("Неверный формат. Попробуй снова: <b>22.06.2025 09:00</b>")
    await state.update_data(event_date=dt)
    await state.set_state(EventCreate.distance)
    await message.answer("Дистанция в км (или «-»):", reply_markup=get_cancel_kb())


@router.message(EventCreate.distance)
async def ev_distance(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)
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

    # Анонс в группу
    if config.GROUP_ID:
        loc_str = f"\n📍 {data['location']}" if data.get("location") else ""
        dist_str = f"\n🏁 {dist} км" if dist else ""
        desc_str = f"\n\n{data['description']}" if data.get("description") else ""
        try:
            await message.bot.send_message(
                config.GROUP_ID,
                f"📣 <b>АНОНС: {data['title']}</b>\n"
                f"⏰ {date_str}{loc_str}{dist_str}{desc_str}\n\n"
                f"Записаться можно через меню «📅 Мероприятия».",
                reply_markup=get_event_kb(ev_id),
            )
        except Exception as e:
            log.error(f"Не удалось отправить анонс в группу: {e}")


# ============================================================
# 9. Еженедельный дайджест
# ============================================================

async def send_weekly_digest(bot: Bot) -> None:
    """Публикует итоги недели в группу. Вызывается планировщиком."""
    if not config.GROUP_ID:
        return

    async with async_session() as session:
        # Топ-5 по XP
        top_res = await session.execute(select(User).order_by(User.xp.desc()).limit(5))
        top = top_res.scalars().all()

        # Все активные контракты
        ch_res = await session.execute(
            select(Challenge).where(
                Challenge.is_active == True,
                Challenge.ch_type == "contract",
            )
        )
        contracts = ch_res.scalars().all()

        # Те, кто выполнил норму за неделю (current_runs >= goal_runs)
        heroes = []
        debtors = []
        for ch in contracts:
            u_res = await session.execute(select(User).where(User.tg_id == ch.user_id))
            u = u_res.scalar_one_or_none()
            if not u:
                continue
            name = f"@{u.username}" if u.username else u.full_name
            if ch.current_runs >= ch.goal_runs:
                heroes.append(f"• {name} — {ch.current_runs} тренировок 🔥{u.streak} нед.")
            else:
                debtors.append(f"• {name} ({ch.current_runs}/{ch.goal_runs}) — 💰 {ch.penalty or '...'}")

        # Сброс прогресса за неделю и обновление стриков
        for ch in contracts:
            if ch.current_runs >= ch.goal_runs:
                u_res = await session.execute(select(User).where(User.tg_id == ch.user_id))
                u = u_res.scalar_one_or_none()
                if u:
                    u.streak += 1
                    u.xp += config.XP_PER_WEEK
                    u.last_week_closed = datetime.now()
            else:
                u_res = await session.execute(select(User).where(User.tg_id == ch.user_id))
                u = u_res.scalar_one_or_none()
                if u:
                    u.streak = 0
            ch.current_runs = 0
            ch.current_value = 0.0

        await session.commit()

    # Собираем текст
    lines = ["🏆 <b>ИТОГИ НЕДЕЛИ — IT БЕГОТНЯ 21</b>\n"]

    if top:
        lines.append("📊 <b>Топ-5 по XP:</b>")
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        for i, u in enumerate(top):
            name = f"@{u.username}" if u.username else u.full_name
            lines.append(f"{medals[i]} {name} — {u.xp} XP 🔥{u.streak}")
        lines.append("")

    if heroes:
        lines.append("✅ <b>Выполнили норму:</b>")
        lines.extend(heroes)
        lines.append("")

    if debtors:
        lines.append("🍕 <b>Должники недели:</b>")
        lines.extend(debtors)
        lines.append("")

    lines.append("Новая неделя — новые километры! Вперёд 🏃")

    try:
        await bot.send_message(config.GROUP_ID, "\n".join(lines))
    except Exception as e:
        log.error(f"Ошибка отправки дайджеста: {e}")


# ============================================================
# 10. Помощь и отмена
# ============================================================

@router.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    await message.answer(
        "❓ <b>Как пользоваться ботом</b>\n\n"
        "<b>Отчёт о тренировке:</b>\n"
        "Пришли фото (скриншот трекера) с подписью:\n"
        "<code>#отчет 7.5</code>\n"
        "(где 7.5 — дистанция в км)\n\n"
        "<b>Нужно 3 голоса</b> других участников или подтверждение админа.\n"
        "После этого км и XP зачисляются автоматически.\n\n"
        "<b>Команды для админов:</b>\n"
        "/new_event — создать мероприятие\n\n"
        "<b>XP:</b>\n"
        f"• 1 км = {config.XP_PER_KM} XP\n"
        f"• Закрытая неделя = {config.XP_PER_WEEK} XP\n\n"
        "Уровни: 🌱 Новичок → 🌿 Бегун → 🌳 Атлет",
        reply_markup=get_main_kb(),
    )


async def _cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=get_main_kb())


@router.message(F.text == "❌ Отмена")
async def msg_cancel(message: types.Message, state: FSMContext):
    await _cancel(message, state)