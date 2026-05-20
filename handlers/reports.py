"""
handlers/reports.py — приём отчётов, P2P голосование, привязка к мероприятиям и челленджам.

Отчёт принимается ТОЛЬКО в топике REPORTS_THREAD_ID.
Формат: фото с подписью «#отчет N.N» (дистанция в км).

Флоу после подачи отчёта:
  1. Единое меню: мероприятия (radio — одно или ни одного) + челленджи (checkbox — любые)
  2. Нажимаешь «✔️ Готово» — всё сохраняется, переходим к голосованию

Разделение прав:
  Бегуны    — голосуют ✅/❌ (нужно VOTES_REQUIRED голосов каждого типа)
  Админ/мод — видят отдельное сообщение с кнопками мгновенного апрув/реджект
"""

import logging
from datetime import datetime

from aiogram import Router, types, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

import config
from database import async_session
from models import (
    User, Moderator, Challenge, ReportChallenge,
    Event, EventParticipant, Report,
)
from keyboards import (
    get_report_vote_kb,
    get_report_admin_kb,
    get_report_approved_kb,
    get_report_rejected_kb,
)
from services.reports import (
    create_report,
    detect_matching_challenges,
    link_challenges,
    add_vote,
    approve_report,
    reject_report,
)

router = Router()
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Клавиатура единого меню привязки
# ──────────────────────────────────────────────────────────────────────────────
#
# callback_data форматы:
#   rep_ev:{report_id}:{event_id}    — тоггл мероприятия (radio)
#   rep_ch:{report_id}:{ch_id}       — тоггл челленджа (checkbox)
#   rep_done:{report_id}             — сохранить и перейти к голосованию
#
# Состояние хранится в тексте кнопок: ✅ = выбрано, ➕ = не выбрано.
# Читается обратно при каждом нажатии из reply_markup.

def _build_link_kb(
    report_id: int,
    events: list,
    challenges: list,
    selected_event_id: int | None = None,   # только одно
    selected_ch_ids: set[int] | None = None,  # любые
) -> types.InlineKeyboardMarkup:
    if selected_ch_ids is None:
        selected_ch_ids = set()

    builder = InlineKeyboardBuilder()

    # ── Секция мероприятий ──
    if events:
        builder.button(text="─── 📅 Мероприятие ───", callback_data="rep_noop")
        for ev in events:
            date_str = ev.event_date.strftime("%d.%m")
            mark = "✅" if ev.id == selected_event_id else "➕"
            label = f"{mark} {ev.title} ({date_str})"
            if len(label) > 60:
                label = label[:57] + "…"
            builder.button(text=label, callback_data=f"rep_ev:{report_id}:{ev.id}")

    # ── Секция челленджей ──
    if challenges:
        builder.button(text="─── 🎯 Челленджи ───", callback_data="rep_noop")
        for ch in challenges:
            from services.challenges import get_type_name
            mark = "✅" if ch.id in selected_ch_ids else "➕"
            label = f"{mark} {get_type_name(ch.ch_type)}: {ch.title}"
            if len(label) > 60:
                label = label[:57] + "…"
            builder.button(text=label, callback_data=f"rep_ch:{report_id}:{ch.id}")

    # ── Кнопка завершения ──
    builder.button(text="✔️ Готово", callback_data=f"rep_done:{report_id}")
    builder.adjust(1)
    return builder.as_markup()


def _read_state(markup: types.InlineKeyboardMarkup) -> tuple[int | None, set[int]]:
    """Читает текущее состояние выбора из кнопок клавиатуры."""
    selected_event_id: int | None = None
    selected_ch_ids: set[int] = set()

    if not markup:
        return selected_event_id, selected_ch_ids

    for row in markup.inline_keyboard:
        for btn in row:
            if not btn.callback_data or not btn.text.startswith("✅"):
                continue
            if btn.callback_data.startswith("rep_ev:"):
                parts = btn.callback_data.split(":")
                selected_event_id = int(parts[2])
            elif btn.callback_data.startswith("rep_ch:"):
                parts = btn.callback_data.split(":")
                selected_ch_ids.add(int(parts[2]))

    return selected_event_id, selected_ch_ids


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные запросы
# ──────────────────────────────────────────────────────────────────────────────

async def _get_participant_events(user_tg_id: int) -> list:
    """Мероприятия, на которые пользователь записался (going), ещё не прошедшие."""
    now = datetime.now()
    async with async_session() as session:
        result = await session.execute(
            select(Event)
            .join(EventParticipant, EventParticipant.event_id == Event.id)
            .where(
                EventParticipant.user_tg_id == user_tg_id,
                EventParticipant.status == "going",
                Event.is_active == True,    # noqa: E712
                Event.is_pending == False,  # noqa: E712
                Event.event_date >= now,
            )
            .order_by(Event.event_date.asc())
        )
        return list(result.scalars().all())


# ──────────────────────────────────────────────────────────────────────────────
# Проверка прав
# ──────────────────────────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _is_moderator(user_id: int) -> bool:
    async with async_session() as session:
        res = await session.execute(
            select(Moderator).where(Moderator.tg_id == user_id)
        )
        return res.scalar_one_or_none() is not None


async def _has_rights(user_id: int) -> bool:
    return _is_admin(user_id) or await _is_moderator(user_id)


# ──────────────────────────────────────────────────────────────────────────────
# Приём отчёта
# ──────────────────────────────────────────────────────────────────────────────

@router.message(F.photo, F.caption.func(lambda c: c and "#отчет" in c.lower()))
async def handle_report(message: types.Message, bot: Bot):
    """Принимает фото с #отчет N.N только в топике REPORTS_THREAD_ID."""
    if not config.REPORTS_THREAD_ID:
        return
    if message.message_thread_id != config.REPORTS_THREAD_ID:
        return

    # Парсим дистанцию — берём только первую строку подписи
    first_line = message.caption.splitlines()[0].lower()
    try:
        raw = first_line.replace("#отчет", "").strip()
        km = float(raw.replace(",", ".")) if raw else 1.0
    except ValueError:
        km = 1.0
    km = max(0.1, round(km, 2))

    # Проверяем регистрацию
    async with async_session() as session:
        u_res = await session.execute(
            select(User).where(User.tg_id == message.from_user.id)
        )
        user = u_res.scalar_one_or_none()

    if not user:
        await message.reply(
            "⚠️ Ты ещё не зарегистрирован.\n"
            "Напиши /start в личку боту, чтобы создать профиль."
        )
        return

    # Привязываем к активному турниру если есть
    from services.tournaments import get_active_tournament, is_participant
    active_tour = await get_active_tournament()
    tour_id = None
    if active_tour and await is_participant(active_tour.id, message.from_user.id):
        tour_id = active_tour.id

    report = await create_report(
        user_tg_id=message.from_user.id,
        km=km,
        message_id=message.message_id,
        chat_id=message.chat.id,
        thread_id=message.message_thread_id,
        tournament_id=tour_id,
    )

    name = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    # Загружаем мероприятия и подходящие челленджи
    events = await _get_participant_events(message.from_user.id)
    challenges = await detect_matching_challenges(message.from_user.id, km)

    header = (
        f"🏃 <b>Новый отчёт!</b>\n"
        f"Атлет: {name}\n"
        f"Результат: <b>{km} км</b>"
    )

    if events or challenges:
        # Показываем единое меню выбора
        sections = []
        if events:
            sections.append("📅 Выбери мероприятие (если это отчёт о нём)")
        if challenges:
            sections.append("🎯 Выбери челленджи (можно несколько)")
        sections.append("Нажми <b>✔️ Готово</b> когда закончишь.")

        await message.reply(
            f"{header}\n\n" + "\n".join(sections),
            reply_markup=_build_link_kb(report.id, events, challenges),
            parse_mode="HTML",
        )
    else:
        # Нет ни мероприятий ни челленджей — сразу голосование
        vote_msg = await message.reply(
            f"{header}\n\n"
            f"Нужно <b>{config.VOTES_REQUIRED}</b> голоса для одобрения.",
            reply_markup=get_report_vote_kb(report.id, pos=0, neg=0),
            parse_mode="HTML",
        )
        await _save_vote_msg(report.id, vote_msg.message_id)

    await _notify_admins(bot, report.id, name, km)


# ──────────────────────────────────────────────────────────────────────────────
# Приём текстового отчёта (без фото)
# ──────────────────────────────────────────────────────────────────────────────
@router.message(F.text.func(lambda t: t and "#отчет" in t.lower()))
async def handle_report_text(message: types.Message, bot: Bot):
    """Принимает текстовый #отчет N.N в топике REPORTS_THREAD_ID."""
    if not config.REPORTS_THREAD_ID:
        return
    if message.message_thread_id != config.REPORTS_THREAD_ID:
        return

    # Парсим дистанцию: берём первую строку, убираем #отчет
    first_line = message.text.splitlines()[0].lower()
    try:
        raw = first_line.replace("#отчет", "").strip()
        km = float(raw.replace(",", ".")) if raw else 1.0
    except ValueError:
        km = 1.0
    km = max(0.1, round(km, 2))

    # Проверяем регистрацию
    async with async_session() as session:
        u_res = await session.execute(
            select(User).where(User.tg_id == message.from_user.id)
        )
        user = u_res.scalar_one_or_none()
    if not user:
        await message.reply(
            "⚠️ Ты ещё не зарегистрирован.\n"
            "Напиши /start в личку боту, чтобы создать профиль."
        )
        return

    # Привязываем к активному турниру если есть
    from services.tournaments import get_active_tournament, is_participant
    active_tour = await get_active_tournament()
    tour_id = None
    if active_tour and await is_participant(active_tour.id, message.from_user.id):
        tour_id = active_tour.id

    report = await create_report(
        user_tg_id=message.from_user.id,
        km=km,
        message_id=message.message_id,
        chat_id=message.chat.id,
        thread_id=message.message_thread_id,
        tournament_id=tour_id,
    )

    name = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    # Загружаем мероприятия и подходящие челленджи
    events     = await _get_participant_events(message.from_user.id)
    challenges = await detect_matching_challenges(message.from_user.id, km)

    header = (
        f"🏃 <b>Новый отчёт!</b>\n"
        f"Атлет: {name}\n"
        f"Результат: <b>{km} км</b>"
    )

    if events or challenges:
        sections = []
        if events:
            sections.append("📅 Выбери мероприятие (если это отчёт о нём)")
        if challenges:
            sections.append("🎯 Выбери челленджи (можно несколько)")
        sections.append("Нажми <b>✔️ Готово</b> когда закончишь.")

        await message.reply(
            f"{header}\n\n" + "\n".join(sections),
            reply_markup=_build_link_kb(report.id, events, challenges),
            parse_mode="HTML",
        )
    else:
        vote_msg = await message.reply(
            f"{header}\n\n"
            f"Нужно <b>{config.VOTES_REQUIRED}</b> голоса для одобрения.",
            reply_markup=get_report_vote_kb(report.id, pos=0, neg=0),
            parse_mode="HTML",
        )
        await _save_vote_msg(report.id, vote_msg.message_id)

    await _notify_admins(bot, report.id, name, km)


# ──────────────────────────────────────────────────────────────────────────────
# Тоггл мероприятия (radio — снять если уже выбрано, иначе выбрать)
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rep_ev:"))
async def cb_toggle_event(callback: types.CallbackQuery):
    _, report_id_str, event_id_str = callback.data.split(":")
    report_id = int(report_id_str)
    event_id  = int(event_id_str)

    async with async_session() as session:
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()

    if not report or report.user_tg_id != callback.from_user.id:
        return await callback.answer("Это не твой отчёт.")

    # Читаем текущее состояние
    cur_event_id, cur_ch_ids = _read_state(callback.message.reply_markup)

    # Radio: если уже выбрано — снимаем, иначе выбираем
    new_event_id = None if cur_event_id == event_id else event_id

    events = await _get_participant_events(callback.from_user.id)
    challenges = await detect_matching_challenges(callback.from_user.id, report.km)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=_build_link_kb(
                report_id, events, challenges,
                selected_event_id=new_event_id,
                selected_ch_ids=cur_ch_ids,
            )
        )
    except TelegramBadRequest:
        pass

    if new_event_id:
        ev = next((e for e in events if e.id == new_event_id), None)
        await callback.answer(f"📅 {ev.title}" if ev else "Мероприятие выбрано")
    else:
        await callback.answer("Мероприятие снято")


# ──────────────────────────────────────────────────────────────────────────────
# Тоггл челленджа (checkbox)
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rep_ch:"))
async def cb_toggle_challenge(callback: types.CallbackQuery):
    _, report_id_str, ch_id_str = callback.data.split(":")
    report_id  = int(report_id_str)
    ch_id      = int(ch_id_str)

    async with async_session() as session:
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()

    if not report or report.user_tg_id != callback.from_user.id:
        return await callback.answer("Это не твой отчёт.")

    cur_event_id, cur_ch_ids = _read_state(callback.message.reply_markup)

    # Checkbox тоггл
    if ch_id in cur_ch_ids:
        cur_ch_ids.discard(ch_id)
        action = "Снято"
    else:
        cur_ch_ids.add(ch_id)
        action = f"Выбрано: {len(cur_ch_ids)}"

    events = await _get_participant_events(callback.from_user.id)
    challenges = await detect_matching_challenges(callback.from_user.id, report.km)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=_build_link_kb(
                report_id, events, challenges,
                selected_event_id=cur_event_id,
                selected_ch_ids=cur_ch_ids,
            )
        )
    except TelegramBadRequest:
        pass

    await callback.answer(action)


# ──────────────────────────────────────────────────────────────────────────────
# Noop — заголовки секций (не реагируем)
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "rep_noop")
async def cb_rep_noop(callback: types.CallbackQuery):
    await callback.answer()


# ──────────────────────────────────────────────────────────────────────────────
# «Готово» — сохраняем выбор и переходим к голосованию
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rep_done:"))
async def cb_rep_done(callback: types.CallbackQuery):
    report_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()

    if not report or report.user_tg_id != callback.from_user.id:
        return await callback.answer("Это не твой отчёт.")

    selected_event_id, selected_ch_ids = _read_state(callback.message.reply_markup)

    # Сохраняем event_id в отчёт
    async with async_session() as session:
        r = await session.get(Report, report_id)
        if r:
            if selected_event_id:
                r.event_id = selected_event_id
                r.report_type = "event"
            else:
                r.event_id = None
                r.report_type = "training"
            await session.commit()

    # Сохраняем привязки к челленджам
    await link_challenges(report_id, list(selected_ch_ids))

    # Формируем итоговый текст
    summary_parts = []

    if selected_event_id:
        async with async_session() as session:
            ev = await session.get(Event, selected_event_id)
        if ev:
            summary_parts.append(f"📅 Мероприятие: <b>{ev.title}</b>")

    if selected_ch_ids:
        async with async_session() as session:
            chs_res = await session.execute(
                select(Challenge).where(Challenge.id.in_(selected_ch_ids))
            )
            ch_titles = [ch.title for ch in chs_res.scalars().all()]
        summary_parts.append("🎯 Челленджи: " + ", ".join(f"«{t}»" for t in ch_titles))

    if not summary_parts:
        summary_parts.append("📎 Без привязки")

    summary = "\n".join(summary_parts)

    try:
        await callback.message.edit_text(
            callback.message.text.split("\n\n📅")[0].split("\n\n🎯")[0] +
            f"\n\n{summary}\n\n"
            f"Нужно <b>{config.VOTES_REQUIRED}</b> голоса для одобрения.",
            reply_markup=get_report_vote_kb(report_id, pos=0, neg=0),
            parse_mode="HTML",
        )
        # Сохраняем ID этого сообщения — оно стало vote-сообщением
        await _save_vote_msg(report_id, callback.message.message_id)
    except TelegramBadRequest:
        pass

    await callback.answer("Сохранено! ✅")


# ──────────────────────────────────────────────────────────────────────────────
# P2P голосование
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("vote_yes:"))
async def cb_vote_yes(callback: types.CallbackQuery, bot: Bot):
    report_id = int(callback.data.split(":")[1])
    result = await add_vote(report_id, callback.from_user.id, negative=False)

    if not result['ok']:
        return await callback.answer(result['reason'])

    pos = result['pos_votes']
    neg = result['neg_votes']

    if result['approved']:
        ap = await approve_report(report_id)
        await _notify_athlete(bot, ap)
        await _notify_group_approved(bot, ap)
        # vote-сообщение — это и есть callback.message, кнопки уберёт edit_text ниже
        try:
            await callback.message.edit_text(
                callback.message.text.split("\n\nНужно")[0] +
                f"\n\n✅ <b>Одобрено голосованием!</b> ({pos}/{config.VOTES_REQUIRED})",
                reply_markup=get_report_approved_kb(),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer("Отчёт одобрен!")
    else:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=get_report_vote_kb(report_id, pos=pos, neg=neg)
            )
        except TelegramBadRequest:
            pass
        await callback.answer(f"✅ Голос принят! ({pos}/{config.VOTES_REQUIRED})")


@router.callback_query(F.data.startswith("vote_no:"))
async def cb_vote_no(callback: types.CallbackQuery, bot: Bot):
    report_id = int(callback.data.split(":")[1])
    result = await add_vote(report_id, callback.from_user.id, negative=True)

    if not result['ok']:
        return await callback.answer(result['reason'])

    pos = result['pos_votes']
    neg = result['neg_votes']

    if result['rejected']:
        try:
            await callback.message.edit_text(
                callback.message.text.split("\n\nНужно")[0] +
                f"\n\n❌ <b>Отклонено голосованием!</b> ({neg}/{config.VOTES_REQUIRED})",
                reply_markup=get_report_rejected_kb(),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
        await callback.answer("Отчёт отклонён!")
    else:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=get_report_vote_kb(report_id, pos=pos, neg=neg)
            )
        except TelegramBadRequest:
            pass
        await callback.answer(f"❌ Голос принят! ({neg}/{config.VOTES_REQUIRED})")


# ──────────────────────────────────────────────────────────────────────────────
# Мгновенный апрув/реджект (только админ/модер)
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_approve:"))
async def cb_admin_approve(callback: types.CallbackQuery, bot: Bot):
    report_id = int(callback.data.split(":")[1])

    if not await _has_rights(callback.from_user.id):
        return await callback.answer("Только админ/модер!")

    ap = await approve_report(report_id)

    if not ap['ok']:
        if ap['reason'] == 'already':
            return await callback.answer("Отчёт уже одобрен.")
        return await callback.answer(ap['reason'])

    await _notify_athlete(bot, ap)
    await _notify_group_approved(bot, ap)
    await _clear_vote_buttons(bot, report_id)

    try:
        await callback.message.edit_text(
            f"✅ <b>Одобрено администратором</b>\n"
            f"📝 {ap['km']} км · 💠 +{ap['xp']} XP",
            reply_markup=get_report_approved_kb(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass

    await callback.answer("Одобрено!")


@router.callback_query(F.data.startswith("adm_reject:"))
async def cb_admin_reject(callback: types.CallbackQuery, bot: Bot):
    report_id = int(callback.data.split(":")[1])

    if not await _has_rights(callback.from_user.id):
        return await callback.answer("Только админ/модер!")

    ok = await reject_report(report_id, rejected_by=callback.from_user.id)
    if not ok:
        return await callback.answer("Отчёт не найден или уже закрыт.")

    # Убираем кнопки с vote-сообщения в группе
    await _clear_vote_buttons_rejected(bot, report_id)

    try:
        await callback.message.edit_text(
            "❌ <b>Отклонено администратором</b>",
            reply_markup=get_report_rejected_kb(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass

    await callback.answer("Отклонено.")


# ──────────────────────────────────────────────────────────────────────────────
# Noop
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────


async def _notify_group_approved(bot: Bot, ap: dict) -> None:
    """Публикует уведомление об одобренном отчёте в general чат группы."""
    if not config.GROUP_ID or not ap.get('ok') or not ap.get('user_tg_id'):
        return
    from sqlalchemy import select as sa_select
    from models import User as UserModel
    async with async_session() as session:
        u_res = await session.execute(
            sa_select(UserModel).where(UserModel.tg_id == ap['user_tg_id'])
        )
        user = u_res.scalar_one_or_none()
    name = f"@{user.username}" if user and user.username else (
        user.school_nick if user else str(ap['user_tg_id'])
    )
    pr_str = " 🎯 <b>Личный рекорд!</b>" if ap.get('is_pr') else ""
    tour_str = ""
    if ap.get('tournament_id'):
        from services.tournaments import get_tournament, get_leaderboard
        tour = await get_tournament(ap['tournament_id'])
        if tour:
            lb = await get_leaderboard(tour.id, limit=3)
            lb_lines = []
            medals = ["🥇", "🥈", "🥉"]
            for row in lb:
                u = row["user"]
                n = f"@{u.username}" if u and u.username else (u.school_nick if u else "?")
                lb_lines.append(f"{medals[row['position']-1]} {n} — {row['score']:.1f} км")
            tour_str = (
                f"\n\n🏆 <b>{tour.title}</b> — текущий топ:\n" + "\n".join(lb_lines)
            )
    try:
        await bot.send_message(
            config.GROUP_ID,
            f"✅ <b>{name}</b> — отчёт принят: <b>{ap['km']} км</b> · +{ap['xp']} XP{pr_str}{tour_str}",
        )
    except Exception as e:
        log.debug("Уведомление в группу не отправлено: %s", e)


async def _save_vote_msg(report_id: int, vote_message_id: int) -> None:
    """Сохраняет message_id vote-сообщения в БД для последующего снятия кнопок."""
    async with async_session() as session:
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()
        if report:
            report.vote_message_id = vote_message_id
            await session.commit()


async def _clear_vote_buttons_rejected(bot: Bot, report_id: int) -> None:
    """Заменяет vote-кнопки на сообщение об отклонении."""
    async with async_session() as session:
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()
        if not report or not report.vote_message_id:
            return
        chat_id = report.chat_id
        vote_msg_id = report.vote_message_id
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=vote_msg_id,
            text="❌ <b>Отчёт отклонён администратором</b>",
            reply_markup=get_report_rejected_kb(),
            parse_mode="HTML",
        )
    except Exception as e:
        log.debug("Не удалось обновить vote-сообщение при реджекте: %s", e)


async def _clear_vote_buttons(bot: Bot, report_id: int) -> None:
    """Убирает кнопки голосования с vote-сообщения после апрува/реджекта."""
    async with async_session() as session:
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()
        if not report or not report.vote_message_id:
            return
        chat_id = report.chat_id
        vote_msg_id = report.vote_message_id
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=vote_msg_id,
            reply_markup=get_report_approved_kb(),
        )
    except Exception as e:
        log.debug("Не удалось обновить vote-сообщение: %s", e)


async def _notify_admins(bot: Bot, report_id: int, athlete_name: str, km: float) -> None:
    admin_ids = list(config.ADMIN_IDS)

    async with async_session() as session:
        mods_res = await session.execute(select(Moderator))
        for mod in mods_res.scalars().all():
            if mod.tg_id not in admin_ids:
                admin_ids.append(mod.tg_id)

    text = (
        f"🔔 <b>Новый отчёт на проверку</b>\n"
        f"Атлет: {athlete_name}\n"
        f"Дистанция: <b>{km} км</b>"
    )

    for uid in admin_ids:
        try:
            await bot.send_message(
                uid, text,
                reply_markup=get_report_admin_kb(report_id),
                parse_mode="HTML",
            )
        except Exception as e:
            log.debug("Не удалось уведомить админа %s: %s", uid, e)


async def _notify_athlete(bot: Bot, ap: dict) -> None:
    if not ap.get('ok') or not ap.get('user_tg_id'):
        return

    pr_line = (
        f"\n🎯 <b>Личный рекорд!</b> +{config.XP_PR_BONUS} XP"
        if ap.get('is_pr') else ""
    )
    completed_text = ""
    if ap.get('completed'):
        names = ", ".join(f"«{n}»" for n in ap['completed'])
        completed_text = f"\n🏆 Завершён челлендж: {names}"

    try:
        await bot.send_message(
            ap['user_tg_id'],
            f"✅ <b>Отчёт принят!</b>\n\n"
            f"📝 {ap['km']} км\n"
            f"💠 +{ap['xp']} XP"
            f"{pr_line}"
            f"{completed_text}",
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning("Не удалось уведомить атлета %s: %s", ap['user_tg_id'], e)