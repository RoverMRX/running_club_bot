"""handlers/reports.py — отчёты о тренировках и мероприятиях, P2P голосование."""

import logging
from aiogram import Router, types, F, Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

import config
from database import async_session
from models import User, Report, Vote, Moderator
from keyboards import get_report_kb, get_report_approved_kb, get_report_rejected_kb
from services.xp import give_xp_for_training, check_and_update_pr

router = Router()
log = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def is_moderator(session, user_id: int) -> bool:
    """Проверка модератор."""
    res = await session.execute(select(Moderator).where(Moderator.tg_id == user_id))
    return res.scalar_one_or_none() is not None


# ──────────────────────────────────────────
# Приём отчёта (фото + #отчет)
# ──────────────────────────────────────────

@router.message(F.photo, F.caption.func(lambda c: c and "#отчет" in c.lower()))
async def handle_report(message: types.Message, bot: Bot):
    """Атлет присылает фото с подписью #отчет N."""
    if not config.REPORTS_THREAD_ID:
        # Если топик не задан, игнорируем (отчёты только в топик)
        return

    # Парсим дистанцию из подписи
    caption = message.caption.lower()
    try:
        raw = caption.replace("#отчет", "").strip()
        km = float(raw.replace(",", ".")) if raw else 1.0
    except ValueError:
        km = 1.0

    async with async_session() as session:
        async with session.begin():
            # Создаём или обновляем пользователя
            u_res = await session.execute(select(User).where(User.tg_id == message.from_user.id))
            user = u_res.scalar_one_or_none()
            if not user:
                user = User(
                    tg_id=message.from_user.id,
                    username=message.from_user.username,
                    full_name=message.from_user.full_name,
                    xp=0,
                )
                session.add(user)
                await session.flush()

            # Сохраняем отчёт в БД
            report = Report(
                message_id=message.message_id,
                chat_id=message.chat.id,
                thread_id=message.message_thread_id,
                user_tg_id=message.from_user.id,
                km=km,
                report_type="training",
            )
            session.add(report)
            await session.flush()
            report_id = report.id

    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    await message.reply(
        f"🏃 <b>Новый отчёт!</b>\n"
        f"Атлет: {name}\n"
        f"Результат: <b>{km} км</b>\n\n"
        f"Нужно <b>{config.VOTES_REQUIRED}</b> голоса или апрув админа/модера.",
        reply_markup=get_report_kb(report_id),
    )


# ──────────────────────────────────────────
# Голосование за отчёт (участники)
# ──────────────────────────────────────────

@router.callback_query(F.data.startswith("vote:"))
async def cb_vote(callback: types.CallbackQuery, bot: Bot):
    """Участник голосует за отчёт."""
    report_id = int(callback.data.split(":")[1])
    voter_id = callback.from_user.id

    async with async_session() as session:
        async with session.begin():
            # Загружаем отчёт
            r_res = await session.execute(select(Report).where(Report.id == report_id))
            report = r_res.scalar_one_or_none()

            if not report or report.is_approved or report.is_rejected:
                return await callback.answer("Отчёт уже закрыт.")
            if report.user_tg_id == voter_id:
                return await callback.answer("Свой отчёт нельзя подтверждать!")

            # Добавляем голос
            try:
                session.add(Vote(report_id=report_id, voter_tg_id=voter_id))
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return await callback.answer("Ты уже голосовал!")

            # Считаем голоса
            v_res = await session.execute(
                select(func.count(Vote.id)).where(Vote.report_id == report_id)
            )
            votes = v_res.scalar()

            # Если собралось достаточно — одобряем
            if votes >= config.VOTES_REQUIRED:
                await _approve_report(session, report, bot)
                await session.commit()

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


# ──────────────────────────────────────────
# Отклонение отчёта (админ/модер)
# ──────────────────────────────────────────

@router.callback_query(F.data.startswith("vote_no:"))
async def cb_vote_no(callback: types.CallbackQuery):
    """Кнопка «Фейк» — отклоняет отчёт."""
    report_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    async with async_session() as session:
        async with session.begin():
            # Проверяем права (админ или модератор)
            if not is_admin(user_id):
                is_mod = await is_moderator(session, user_id)
                if not is_mod:
                    return await callback.answer("Только админ/модер может отклонять!")

            r_res = await session.execute(select(Report).where(Report.id == report_id))
            report = r_res.scalar_one_or_none()

            if not report:
                return await callback.answer("Отчёт не найден.")
            if report.is_approved or report.is_rejected:
                return await callback.answer("Уже решено.")

            report.is_rejected = True
            report.rejected_by = user_id
            await session.flush()

    try:
        await callback.message.edit_text(
            f"❌ <b>Отчёт отклонён</b> ({report.km} км)",
            reply_markup=get_report_rejected_kb(),
        )
    except TelegramBadRequest:
        pass

    await callback.answer("Отчёт отклонён.")


# ──────────────────────────────────────────
# Одобрение администратором
# ──────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_approve:"))
async def cb_admin_approve(callback: types.CallbackQuery, bot: Bot):
    """Админ/модер мгновенно одобряет отчёт."""
    report_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    async with async_session() as session:
        async with session.begin():
            # Проверяем права
            if not is_admin(user_id):
                is_mod = await is_moderator(session, user_id)
                if not is_mod:
                    return await callback.answer("Только админ/модер!")

            r_res = await session.execute(select(Report).where(Report.id == report_id))
            report = r_res.scalar_one_or_none()

            if not report:
                return await callback.answer("Отчёт не найден.")
            if report.is_approved or report.is_rejected:
                return await callback.answer("Уже решено.")

            await _approve_report(session, report, bot)
            await session.commit()

    try:
        await callback.message.edit_text(
            f"✅ <b>Отчёт одобрен администратором</b> ({report.km} км)",
            reply_markup=get_report_approved_kb(),
        )
    except TelegramBadRequest:
        pass

    await callback.answer("Отчёт одобрен!")


# ──────────────────────────────────────────
# Вспомогательная функция одобрения
# ──────────────────────────────────────────

async def _approve_report(session, report: Report, bot: Bot) -> None:
    """Одобряет отчёт и начисляет XP."""
    # Начисляем XP
    total_xp = await give_xp_for_training(
        session,
        report.user_tg_id,
        report.km,
    )

    # Проверяем личный рекорд
    is_pr, pr_bonus = await check_and_update_pr(session, report.user_tg_id, report.km)
    if is_pr:
        total_xp += pr_bonus
        u_res = await session.execute(select(User).where(User.tg_id == report.user_tg_id))
        user = u_res.scalar_one_or_none()
        if user:
            user.xp += pr_bonus
            user.season_xp += pr_bonus

    # Обновляем активные челленджи атлета
    from models import Challenge, ChallengeParticipant
    
    ch_res = await session.execute(
        select(Challenge).where(
            Challenge.user_id == report.user_tg_id,
            Challenge.is_active == True,
            Challenge.ch_type == "contract",
        )
    )
    for ch in ch_res.scalars().all():
        if report.km >= ch.min_per_run:
            ch.current_runs += 1
            ch.current_value += report.km

    # Обновляем челленджи, к которым присоединился
    part_res = await session.execute(
        select(ChallengeParticipant).where(
            ChallengeParticipant.user_id == report.user_tg_id
        )
    )
    for part in part_res.scalars().all():
        ch = part.challenge
        if ch.is_active and ch.ch_type == "contract" and report.km >= ch.min_per_run:
            part.current_runs += 1
            part.current_value += report.km

    report.is_approved = True
    await session.flush()

    # Отправляем уведомление в личку
    try:
        await bot.send_message(
            report.user_tg_id,
            f"✅ Отчёт принят!\n\n"
            f"📝 {report.km} км\n"
            f"💠 +{total_xp} XP" +
            (f"\n🎯 Личный рекорд!" if is_pr else ""),
        )
    except Exception:
        pass