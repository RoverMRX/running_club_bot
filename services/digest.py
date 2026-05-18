"""
services/digest.py — еженедельный дайджест клуба с героями, турнирами и стриками.
"""

import logging
from datetime import datetime
from aiogram import Bot
from sqlalchemy import select, func

import config
from database import async_session
from models import User, Challenge, WeeklyTournament, TournamentParticipant

log = logging.getLogger(__name__)


async def send_weekly_digest(bot: Bot) -> None:
    """Публикует итоги недели в топик дайджеста."""
    if not config.GROUP_ID:
        return

    async with async_session() as session:
        # Топ-5 по XP
        top_res = await session.execute(
            select(User).order_by(User.xp.desc()).limit(5)
        )
        top = top_res.scalars().all()

        # Все активные контракты
        ch_res = await session.execute(
            select(Challenge).where(
                Challenge.is_active == True,
                Challenge.ch_type == "contract",
            )
        )
        contracts = ch_res.scalars().all()

        # Активный недельный турнир (если есть)
        tour_res = await session.execute(
            select(WeeklyTournament).where(WeeklyTournament.is_active == True)
        )
        current_tournament = tour_res.scalar_one_or_none()

        # Герои и должники
        heroes = []
        debtors = []
        total_km = 0.0
        total_runs = 0

        for ch in contracts:
            u_res = await session.execute(select(User).where(User.tg_id == ch.user_id))
            u = u_res.scalar_one_or_none()
            if not u:
                continue

            total_km += ch.current_value
            total_runs += ch.current_runs
            name = f"@{u.username}" if u.username else u.full_name

            if ch.current_runs >= ch.goal_runs:
                # Герой — выполнил норму
                u.streak += 1
                u.xp += config.XP_PER_WEEK
                u.season_xp += config.XP_PER_WEEK
                u.last_week_closed = datetime.now()
                heroes.append(
                    f"• {name} — {ch.current_runs} тренировок ({ch.current_value:.1f} км) 🔥{u.streak}"
                )
            else:
                # Должник
                u.streak = 0
                debtors.append(
                    f"• {name} ({ch.current_runs}/{ch.goal_runs}) — 💰 {ch.penalty or '...'}"
                )

            # Сброс счётчиков за неделю
            ch.current_runs = 0
            ch.current_value = 0.0

        await session.commit()

    # Собираем текст дайджеста
    lines = [
        "📊 <b>ДАЙДЖЕСТ НЕДЕЛИ — IT БЕГОТНЯ 21</b>",
        f"Период: {datetime.now().strftime('%d.%m.%Y')}",
        "",
        "🏃 <b>АКТИВНОСТЬ КЛУБА</b>",
        f"Всего км: {total_km:.1f}  |  Тренировок: {total_runs}  |  Участников: {len(contracts)}",
        "",
    ]

    if heroes:
        lines.append("✅ <b>ГЕРОИ НЕДЕЛИ</b>")
        lines.extend(heroes)
        lines.append("")

    if debtors:
        lines.append("🍕 <b>ДОЛЖНИКИ</b>")
        lines.extend(debtors)
        lines.append("")

    if top:
        lines.append("🏆 <b>ТОП-5 ПО XP (ВСЕГО)</b>")
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        for i, u in enumerate(top):
            name = f"@{u.username}" if u.username else u.full_name
            lines.append(f"{medals[i]} {name} — {u.xp} XP 🔥{u.streak}")
        lines.append("")

    if current_tournament:
        lines.append(f"🎯 <b>ТУРНИР: {current_tournament.title}</b>")
        part_res = await async_session().execute(
            select(TournamentParticipant).where(
                TournamentParticipant.tournament_id == current_tournament.id
            ).order_by(TournamentParticipant.score.desc()).limit(3)
        )
        for i, part in enumerate(part_res.scalars().all(), 1):
            u_res = await async_session().execute(
                select(User).where(User.tg_id == part.user_tg_id)
            )
            u = u_res.scalar_one_or_none()
            if u:
                name = f"@{u.username}" if u.username else u.full_name
                lines.append(f"{i}. {name} — {part.score}")
        lines.append("")

    lines.append("Новая неделя — новые километры! Вперёд 🏃💪")

    try:
        await bot.send_message(
            config.GROUP_ID,
            "\n".join(lines),
            message_thread_id=config.DIGEST_THREAD_ID,
        )
    except Exception as e:
        log.error(f"Ошибка отправки дайджеста: {e}")