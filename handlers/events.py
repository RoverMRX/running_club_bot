"""handlers/events.py — мероприятия: список, создание, публикация анонсов."""

from __future__ import annotations

from datetime import datetime

from aiogram.enums import ChatType
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

import config
from database import async_session
from keyboards import (
    get_cancel_kb,
    get_event_moderation_kb,
    get_event_participants_kb,
    get_event_secondary_kb,
    get_main_kb,
    get_main_kb_with_admin,
)
from models import Moderator, User, EventParticipant, Event
from services.events import (
    create_event,
    create_event_from_template,
    format_announce,
    get_event,
    get_participant_counts,
    get_pending_events,
    get_template,
    get_templates,
    get_upcoming_events,
    is_moderator,
    join_event,
    publish_to_main_group,
    publish_to_secondary_group,
)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


# ── FSM ──────────────────────────────────────────────────────

class CreateEventFSM(StatesGroup):
    choose_template = State()
    tpl_location    = State()
    tpl_distance    = State()
    manual_title       = State()
    manual_description = State()
    manual_location    = State()
    manual_distance    = State()
    event_date = State()


# ── Helpers ───────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _is_admin_or_mod(user_id: int) -> bool:
    if _is_admin(user_id):
        return True
    async with async_session() as session:
        return await is_moderator(session, user_id)


async def _main_kb_for(user_id: int):
    if await _is_admin_or_mod(user_id):
        return get_main_kb_with_admin()
    return get_main_kb()


def _parse_date(raw: str) -> datetime | None:
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _event_card(event, going: int, not_going: int) -> str:
    date_str = event.event_date.strftime("%d.%m.%Y в %H:%M")
    lines = [f"📅 <b>{event.title}</b>", f"🗓 {date_str}"]
    if event.location:
        lines.append(f"📍 {event.location}")
    if event.distance_km:
        lines.append(f"🏃 {event.distance_km} км")
    if event.description:
        lines.append(f"\n{event.description}")
    lines.append(f"\n👥 Идут: {going}  ·  ❌ Не идут: {not_going}")
    return "\n".join(lines)


def _templates_inline_kb(templates: list) -> object:
    builder = InlineKeyboardBuilder()
    for tpl in templates:
        ext = "🌍" if tpl.is_external else "🏃"
        parts = [f"{ext} {tpl.name}"]
        if tpl.distance_km:
            parts.append(f"{tpl.distance_km} км")
        if tpl.location:
            parts.append(tpl.location[:20])
        label = " · ".join(parts)
        if len(label) > 60:
            label = label[:57] + "…"
        builder.button(text=label, callback_data=f"evt_tpl:{tpl.id}")
    builder.button(text="✏️ Создать без шаблона", callback_data="evt_tpl:0")
    builder.button(text="❌ Отмена",               callback_data="evt_tpl:cancel")
    builder.adjust(1)
    return builder.as_markup()


# ── «📅 Мероприятия» — список ────────────────────────────────

@router.message(F.text == "📋 Ближайшие мероприятия")
async def cmd_events_list(message: Message) -> None:
    async with async_session() as session:
        events = await get_upcoming_events(session)
        if not events:
            await message.answer(
                "Ближайших мероприятий пока нет. Следите за обновлениями! 🙌"
            )
            return

        await message.answer(f"📅 <b>Ближайшие мероприятия</b> — {len(events)} шт.:")
        for event in events:
            going, not_going = await get_participant_counts(session, event.id)
            kb = _event_list_kb(event.id, going, not_going)
            await message.answer(_event_card(event, going, not_going), reply_markup=kb)


def _event_list_kb(event_id: int, going: int, not_going: int):
    """Кнопки под карточкой мероприятия в списке: участие + посмотреть участников."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🏃 Участвую ({going})",    callback_data=f"event_join:{event_id}")
    builder.button(text=f"❌ Не пойду ({not_going})", callback_data=f"event_skip:{event_id}")
    builder.button(text="👥 Участники",               callback_data=f"event_members:{event_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


# ── Список участников мероприятия ─────────────────────────────

@router.callback_query(F.data.startswith("event_members:"))
async def cb_event_members(callback: CallbackQuery) -> None:
    event_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        # Загружаем мероприятие
        event = await session.get(Event, event_id)
        if event is None:
            await callback.answer("Мероприятие не найдено.", show_alert=True)
            return

        # Участники со статусом going + их профили
        result = await session.execute(
            select(EventParticipant, User)
            .join(User, User.tg_id == EventParticipant.user_tg_id)
            .where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == "going",
            )
            .order_by(EventParticipant.registered_at.asc())
        )
        rows = result.all()

    if not rows:
        await callback.answer("Пока никто не записался.", show_alert=True)
        return

    lines = [f"👥 <b>Участники: {event.title}</b>\n"]
    for i, (ep, user) in enumerate(rows, 1):
        uname = f"@{user.username}" if user.username else user.full_name or "—"
        lines.append(f"{i}. <b>{user.school_nick}</b> ({uname})")

    await callback.message.answer("\n".join(lines))
    await callback.answer()


# ── Создание мероприятия ──────────────────────────────────────

@router.message(F.text == "➕ Создать мероприятие")
async def cmd_create_event_start(message: Message, state: FSMContext) -> None:
    async with async_session() as session:
        templates = await get_templates(session)

    if templates:
        await state.set_state(CreateEventFSM.choose_template)
        await message.answer(
            "Выбери шаблон мероприятия.\n\n"
            "Шаблон заполнит название, описание, место и км автоматически — "
            "ты сможешь их поправить или оставить как есть.\n"
            "Затем нужно будет ввести только <b>дату и время</b>.",
            reply_markup=_templates_inline_kb(templates),
        )
    else:
        await state.update_data(template_id=None)
        await state.set_state(CreateEventFSM.manual_title)
        await message.answer(
            "Шаблонов пока нет. Заполним всё вручную.\n\n"
            "Введи <b>название</b> мероприятия:",
            reply_markup=get_cancel_kb(),
        )


@router.callback_query(F.data.startswith("evt_tpl:"), CreateEventFSM.choose_template)
async def fsm_choose_template(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":")[1]

    if value == "cancel":
        await state.clear()
        await callback.message.edit_text("Создание мероприятия отменено.")
        await callback.answer()
        return

    template_id = int(value)

    if template_id == 0:
        await state.update_data(template_id=None)
        await state.set_state(CreateEventFSM.manual_title)
        await callback.message.edit_text("Создаём без шаблона.")
        await callback.message.answer(
            "Введи <b>название</b> мероприятия:", reply_markup=get_cancel_kb()
        )
        await callback.answer()
        return

    async with async_session() as session:
        tpl = await get_template(session, template_id)

    if tpl is None:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return

    await state.update_data(template_id=tpl.id)

    lines = [f"✅ Шаблон: <b>{tpl.name}</b>"]
    if tpl.description:
        lines.append(tpl.description)
    lines.append("")
    lines.append(
        f"📍 Место: {tpl.location or '—'}\n"
        f"🏃 Дистанция: {tpl.distance_km or '—'} км\n"
        f"⭐ XP: +{tpl.xp_bonus} · ×{tpl.xp_multiplier}"
    )

    await callback.message.edit_text("\n".join(lines))
    await callback.message.answer(
        "Введи <b>место проведения</b> или «-» чтобы оставить из шаблона"
        + (f" (<i>{tpl.location}</i>)" if tpl.location else " (в шаблоне не задано)") + ":",
        reply_markup=get_cancel_kb(),
    )
    await state.set_state(CreateEventFSM.tpl_location)
    await callback.answer()


@router.message(CreateEventFSM.tpl_location, F.text != "❌ Отмена")
async def fsm_tpl_location(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(override_location=... if raw == "-" else (raw or None))

    data = await state.get_data()
    async with async_session() as session:
        tpl = await get_template(session, data["template_id"])

    await state.set_state(CreateEventFSM.tpl_distance)
    await message.answer(
        "Введи <b>дистанцию</b> в км или «-» чтобы оставить из шаблона"
        + (f" (<i>{tpl.distance_km} км</i>)" if tpl and tpl.distance_km else " (в шаблоне не задана)") + ":",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateEventFSM.tpl_distance, F.text != "❌ Отмена")
async def fsm_tpl_distance(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if raw == "-":
        await state.update_data(override_distance=...)
    else:
        try:
            await state.update_data(override_distance=float(raw.replace(",", ".")) if raw else ...)
        except ValueError:
            await message.answer("Введи число (например 5.5) или «-» чтобы оставить из шаблона:")
            return

    await state.set_state(CreateEventFSM.event_date)
    await message.answer(
        "Введи <b>дату и время</b> в формате ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Например: <code>15.07.2025 09:30</code>",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateEventFSM.manual_title, F.text != "❌ Отмена")
async def fsm_manual_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip())
    await state.set_state(CreateEventFSM.manual_description)
    await message.answer(
        "Введи <b>описание</b> (или «-» чтобы пропустить):", reply_markup=get_cancel_kb()
    )


@router.message(CreateEventFSM.manual_description, F.text != "❌ Отмена")
async def fsm_manual_description(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(description=None if raw == "-" else raw)
    await state.set_state(CreateEventFSM.manual_location)
    await message.answer(
        "Введи <b>место проведения</b> (или «-» чтобы пропустить):", reply_markup=get_cancel_kb()
    )


@router.message(CreateEventFSM.manual_location, F.text != "❌ Отмена")
async def fsm_manual_location(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(manual_location=None if raw == "-" else raw)
    await state.set_state(CreateEventFSM.manual_distance)
    await message.answer(
        "Введи <b>дистанцию</b> в км (или «-» чтобы пропустить):", reply_markup=get_cancel_kb()
    )


@router.message(CreateEventFSM.manual_distance, F.text != "❌ Отмена")
async def fsm_manual_distance(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    distance_km: float | None = None
    if raw != "-":
        try:
            distance_km = float(raw.replace(",", "."))
        except ValueError:
            await message.answer("Введи число (например 5.5) или «-» чтобы пропустить:")
            return
    await state.update_data(manual_distance=distance_km)
    await state.set_state(CreateEventFSM.event_date)
    await message.answer(
        "Введи <b>дату и время</b> в формате ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Например: <code>15.07.2025 09:30</code>",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateEventFSM.event_date, F.text != "❌ Отмена")
async def fsm_event_date(message: Message, state: FSMContext) -> None:
    dt = _parse_date(message.text)
    if dt is None:
        await message.answer(
            "Не могу распознать дату. Формат: ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Например: <code>15.07.2025 09:30</code>"
        )
        return
    if dt < datetime.now():
        await message.answer("Дата не может быть в прошлом. Попробуй снова:")
        return

    data = await state.get_data()
    await state.clear()
    user_id = message.from_user.id

    async with async_session() as session:
        template_id = data.get("template_id")
        if template_id:
            loc  = data.get("override_location", ...)
            dist = data.get("override_distance", ...)
            event = await create_event_from_template(
                session,
                template_id=template_id,
                event_date=dt,
                created_by=user_id,
                location=loc,
                distance_km=dist,
            )
        else:
            event = await create_event(
                session,
                title=data.get("title", "Мероприятие"),
                description=data.get("description"),
                location=data.get("manual_location"),
                event_date=dt,
                distance_km=data.get("manual_distance"),
                created_by=user_id,
            )

    is_privileged = await _is_admin_or_mod(user_id)
    kb = await _main_kb_for(user_id)
    preview = format_announce(event)

    if is_privileged:
        await message.answer(
            f"✅ Мероприятие создано! Вот как будет выглядеть анонс:\n\n{preview}",
            reply_markup=get_event_moderation_kb(event.id),
        )
    else:
        await message.answer(
            f"✅ Мероприятие <b>{event.title}</b> отправлено на модерацию!\n\n"
            f"Как только модератор одобрит — анонс появится в группе.",
            reply_markup=kb,
        )
        await _notify_mods_about_pending(message.bot, event)


# ── Уведомление модераторов ───────────────────────────────────

async def _notify_mods_about_pending(bot: Bot, event) -> None:
    text = (
        f"🆕 <b>Новое мероприятие на модерации</b>\n\n"
        f"{format_announce(event)}\n\n"
        f"Создал: ID <code>{event.created_by}</code>"
    )
    kb = get_event_moderation_kb(event.id)

    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except Exception:
            pass

    async with async_session() as session:
        result = await session.execute(select(Moderator))
        mods = result.scalars().all()

    for mod in mods:
        if mod.tg_id not in config.ADMIN_IDS:
            try:
                await bot.send_message(mod.tg_id, text, reply_markup=kb)
            except Exception:
                pass


# ── Мероприятия на модерации ──────────────────────────────────

@router.message(F.text == "🗂 На модерации")
async def cmd_pending_events(message: Message) -> None:
    if not await _is_admin_or_mod(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    async with async_session() as session:
        events = await get_pending_events(session)

    if not events:
        await message.answer("Мероприятий на модерации нет. ✅")
        return

    await message.answer(f"🕐 На модерации: {len(events)} шт.")
    for event in events:
        await message.answer(
            f"Создал: ID <code>{event.created_by}</code>\n\n{format_announce(event)}",
            reply_markup=get_event_moderation_kb(event.id),
        )


# ── Публикация в основную группу ─────────────────────────────

@router.callback_query(F.data.startswith("evt_pub_main:"))
async def cb_publish_main(callback: CallbackQuery) -> None:
    if not await _is_admin_or_mod(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    event_id = int(callback.data.split(":")[1])

    if not config.GROUP_ID:
        await callback.answer("GROUP_ID не настроен в .env", show_alert=True)
        return

    async with async_session() as session:
        event = await get_event(session, event_id)
        if event is None:
            await callback.answer("Мероприятие не найдено.", show_alert=True)
            return
        if event.announce_msg_id:
            await callback.answer("Уже опубликовано в основной группе.", show_alert=True)
            return
        msg_id = await publish_to_main_group(session, event_id, callback.bot)

    await callback.message.edit_text(
        callback.message.text
        + f"\n\n✅ <b>Опубликовано в основной группе</b> (сообщение #{msg_id})"
    )

    if config.SECONDARY_GROUP_ID:
        async with async_session() as session:
            event = await get_event(session, event_id)
        secondary_preview = (
            f"{format_announce(event)}\n\n"
            "👟 Хочешь бегать вместе? Вступай в клуб: https://t.me/+your_invite_link"
        )
        await callback.message.answer(
            f"Вот как будет выглядеть анонс для второй группы:\n\n{secondary_preview}",
            reply_markup=get_event_secondary_kb(event_id),
        )
    else:
        await callback.message.answer("✅ Готово! Вторая группа не настроена в .env")

    await callback.answer("Опубликовано! 📢")


# ── Публикация во вторую группу ───────────────────────────────

@router.callback_query(F.data.startswith("evt_pub_sec:"))
async def cb_publish_secondary(callback: CallbackQuery) -> None:
    if not await _is_admin_or_mod(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    event_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        event = await get_event(session, event_id)
        if event is None:
            await callback.answer("Мероприятие не найдено.", show_alert=True)
            return
        if event.repost_msg_id:
            await callback.answer("Уже репостнуто.", show_alert=True)
            return
        msg_id = await publish_to_secondary_group(session, event_id, callback.bot)

    await callback.message.edit_text(
        callback.message.text
        + f"\n\n✅ <b>Репостнуто во вторую группу</b> (сообщение #{msg_id})"
    )
    await callback.answer("Репостнуто! 📣")


@router.callback_query(F.data.startswith("evt_skip_sec:"))
async def cb_skip_secondary(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        callback.message.text + "\n\n➡️ Репост во вторую группу пропущен."
    )
    await callback.answer()


# ── Отклонение мероприятия ────────────────────────────────────

@router.callback_query(F.data.startswith("evt_reject:"))
async def cb_reject_event(callback: CallbackQuery) -> None:
    if not await _is_admin_or_mod(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    event_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        event = await get_event(session, event_id)
        if event is None:
            await callback.answer("Мероприятие не найдено.", show_alert=True)
            return
        event.is_active = False
        event.is_pending = False
        await session.commit()

        try:
            await callback.bot.send_message(
                event.created_by,
                f"❌ Мероприятие <b>{event.title}</b> отклонено.",
            )
        except Exception:
            pass

    await callback.message.edit_text(
        callback.message.text + "\n\n❌ <b>Мероприятие отклонено.</b>"
    )
    await callback.answer("Отклонено.")


# ── Отмена FSM ────────────────────────────────────────────────

@router.message(F.text == "❌ Отмена", StateFilter(CreateEventFSM))
async def fsm_event_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    kb = await _main_kb_for(message.from_user.id)
    await message.answer("Создание мероприятия отменено.", reply_markup=kb)


# ── Колбэки участия ──────────────────────────────────────────

async def _handle_event_vote(callback: CallbackQuery, event_id: int, status: str) -> None:
    async with async_session() as session:
        event = await get_event(session, event_id)
        if event is None:
            await callback.answer("Мероприятие не найдено.", show_alert=True)
            return
        await join_event(
            session, event_id=event_id,
            user_tg_id=callback.from_user.id, status=status
        )
        going, not_going = await get_participant_counts(session, event_id)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=_event_list_kb(event_id, going, not_going)
        )
    except Exception:
        pass

    await callback.answer("Ты в деле! 🏃" if status == "going" else "Жаль, в другой раз! 👋")


@router.callback_query(F.data.startswith("event_join:"))
async def cb_event_join(callback: CallbackQuery) -> None:
    await _handle_event_vote(callback, int(callback.data.split(":")[1]), "going")


@router.callback_query(F.data.startswith("event_skip:"))
async def cb_event_skip(callback: CallbackQuery) -> None:
    await _handle_event_vote(callback, int(callback.data.split(":")[1]), "not_going")


@router.callback_query(F.data.startswith("event_leave:"))
async def cb_event_leave(callback: CallbackQuery) -> None:
    await _handle_event_vote(callback, int(callback.data.split(":")[1]), "not_going")