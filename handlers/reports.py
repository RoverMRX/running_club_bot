"""
handlers/reports.py — приём отчётов, P2P голосование, привязка к челленджам.

Отчёт принимается ТОЛЬКО в топике REPORTS_THREAD_ID.
Формат: фото с подписью «#отчет N.N» (дистанция в км).

Разделение прав:
  Бегуны    — голосуют ✅/❌ (нужно VOTES_REQUIRED голосов каждого типа)
  Админ/мод — видят отдельное сообщение с кнопками мгновенного апрув/реджект
"""

import logging
from aiogram import Router, types, F, Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select

import config
from database import async_session
from models import User, Moderator, Challenge, ReportChallenge
from keyboards import (
    get_report_vote_kb,
    get_report_admin_kb,
    get_report_approved_kb,
    get_report_rejected_kb,
    get_challenge_link_kb,
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
    """
    Принимает фото с #отчет N.N только в топике REPORTS_THREAD_ID.
    Парсит дистанцию, создаёт отчёт, предлагает привязать к челленджам
    и отправляет отдельное сообщение с кнопками для голосования.
    Админам/модерам дополнительно шлёт личное сообщение с кнопками апрув/реджект.
    """
    if not config.REPORTS_THREAD_ID:
        return
    if message.message_thread_id != config.REPORTS_THREAD_ID:
        return

    # Парсим дистанцию
    caption = message.caption.lower()
    try:
        raw = caption.replace("#отчет", "").strip()
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

    # Создаём отчёт
    report = await create_report(
        user_tg_id=message.from_user.id,
        km=km,
        message_id=message.message_id,
        chat_id=message.chat.id,
        thread_id=message.message_thread_id,
    )

    name = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    header = (
        f"🏃 <b>Новый отчёт!</b>\n"
        f"Атлет: {name}\n"
        f"Результат: <b>{km} км</b>"
    )

    # Ищем подходящие челленджи для привязки
    matching = await detect_matching_challenges(message.from_user.id, km)

    if matching:
        # Сначала предлагаем выбрать челленджи
        await message.reply(
            f"{header}\n\n"
            f"К каким челленджам засчитать? Можно выбрать несколько.\n"
            f"Когда выберешь — нажми <b>Готово</b>.",
            reply_markup=get_challenge_link_kb(report.id, matching),
            parse_mode="HTML",
        )
    else:
        # Нет подходящих челленджей — сразу показываем голосование
        await message.reply(
            f"{header}\n\n"
            f"Нужно <b>{config.VOTES_REQUIRED}</b> голоса для одобрения.",
            reply_markup=get_report_vote_kb(report.id, pos=0, neg=0),
            parse_mode="HTML",
        )

    # Уведомляем админов/модеров в личку
    await _notify_admins(bot, report.id, name, km)


# ──────────────────────────────────────────────────────────────────────────────
# Мульти-выбор челленджей
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("toggle_ch:"))
async def cb_toggle_challenge(callback: types.CallbackQuery):
    """
    Пользователь тогглит челлендж в мульти-выборе.
    callback_data: toggle_ch:{report_id}:{challenge_id}

    Выбранные челленджи хранятся прямо в тексте кнопок (✅/➕),
    фактическая запись в БД происходит при нажатии «Готово».
    """
    _, report_id_str, challenge_id_str = callback.data.split(":")
    report_id = int(report_id_str)
    challenge_id = int(challenge_id_str)

    # Проверяем что это сообщение для этого пользователя
    async with async_session() as session:
        from models import Report
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()

    if not report or report.user_tg_id != callback.from_user.id:
        return await callback.answer("Это не твой отчёт.")

    # Читаем текущее состояние выбора из callback_data кнопок
    markup = callback.message.reply_markup
    selected: set[int] = set()
    if markup:
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("toggle_ch:"):
                    parts = btn.callback_data.split(":")
                    if btn.text.startswith("✅"):
                        selected.add(int(parts[2]))

    # Тоггл
    if challenge_id in selected:
        selected.discard(challenge_id)
    else:
        selected.add(challenge_id)

    # Получаем список всех челленджей для обновления клавиатуры
    matching = await detect_matching_challenges(
        callback.from_user.id,
        report.km,
    )

    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_challenge_link_kb(report_id, matching, selected=selected)
        )
    except TelegramBadRequest:
        pass

    count = len(selected)
    await callback.answer(
        f"Выбрано: {count}" if count else "Снято"
    )


@router.callback_query(F.data.startswith("link_done:"))
async def cb_link_done(callback: types.CallbackQuery):
    """
    Пользователь нажал «Готово» — сохраняем выбранные челленджи
    и меняем сообщение на голосовалку.
    callback_data: link_done:{report_id}
    """
    report_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        from models import Report
        r_res = await session.execute(select(Report).where(Report.id == report_id))
        report = r_res.scalar_one_or_none()

    if not report or report.user_tg_id != callback.from_user.id:
        return await callback.answer("Это не твой отчёт.")

    # Собираем выбранные ID из кнопок с ✅
    markup = callback.message.reply_markup
    selected: list[int] = []
    if markup:
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("toggle_ch:") and btn.text.startswith("✅"):
                    selected.append(int(btn.callback_data.split(":")[2]))

    # Сохраняем привязки
    await link_challenges(report_id, selected)

    # Формируем текст подтверждения
    if selected:
        async with async_session() as session:
            chs_res = await session.execute(
                select(Challenge).where(Challenge.id.in_(selected))
            )
            titles = [ch.title for ch in chs_res.scalars().all()]
        linked_text = "📎 " + ", ".join(f"«{t}»" for t in titles)
    else:
        linked_text = "📎 Без привязки к челленджам"

    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n{linked_text}\n\n"
            f"Нужно <b>{config.VOTES_REQUIRED}</b> голоса для одобрения.",
            reply_markup=get_report_vote_kb(report_id, pos=0, neg=0),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass

    await callback.answer("Сохранено!")


# ──────────────────────────────────────────────────────────────────────────────
# P2P голосование (бегуны)
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("vote_yes:"))
async def cb_vote_yes(callback: types.CallbackQuery, bot: Bot):
    """Голос «Засчитать» от любого бегуна."""
    report_id = int(callback.data.split(":")[1])
    result = await add_vote(report_id, callback.from_user.id, negative=False)

    if not result['ok']:
        return await callback.answer(result['reason'])

    pos = result['pos_votes']
    neg = result['neg_votes']

    if result['approved']:
        ap = await approve_report(report_id)
        await _notify_athlete(bot, ap)
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
    """Голос «Фейк» от любого бегуна."""
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
# Мгновенный апрув/реджект (только админ/модер, через личку)
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_approve:"))
async def cb_admin_approve(callback: types.CallbackQuery, bot: Bot):
    """Админ/модер одобряет отчёт мгновенно."""
    report_id = int(callback.data.split(":")[1])

    if not await _has_rights(callback.from_user.id):
        return await callback.answer("Только админ/модер!")

    ap = await approve_report(report_id)

    if not ap['ok']:
        if ap['reason'] == 'already':
            return await callback.answer("Отчёт уже одобрен.")
        return await callback.answer(ap['reason'])

    await _notify_athlete(bot, ap)

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
async def cb_admin_reject(callback: types.CallbackQuery):
    """Админ/модер отклоняет отчёт мгновенно."""
    report_id = int(callback.data.split(":")[1])

    if not await _has_rights(callback.from_user.id):
        return await callback.answer("Только админ/модер!")

    ok = await reject_report(report_id, rejected_by=callback.from_user.id)
    if not ok:
        return await callback.answer("Отчёт не найден или уже закрыт.")

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
# noop
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────

async def _notify_admins(bot: Bot, report_id: int, athlete_name: str, km: float) -> None:
    """Отправляет личное сообщение всем админам и модераторам с кнопками апрув/реджект."""
    admin_ids = list(config.ADMIN_IDS)

    # Добавляем модераторов
    async with async_session() as session:
        from models import Moderator
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
                uid,
                text,
                reply_markup=get_report_admin_kb(report_id),
                parse_mode="HTML",
            )
        except Exception as e:
            log.debug("Не удалось уведомить админа %s: %s", uid, e)


async def _notify_athlete(bot: Bot, ap: dict) -> None:
    """Отправляет уведомление об одобрении в личку атлету."""
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