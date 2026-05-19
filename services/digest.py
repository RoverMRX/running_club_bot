"""
services/digest.py — еженедельный дайджест клуба.

Публичный API:
  send_weekly_digest(bot)   — публикует дайджест недели в группу
                               и отдельные отчёты по челленджам каждому участнику

Логика:
  1. Считаем статистику активности за неделю (км, тренировок, участников)
  2. Определяем героев и должников по active weekly_runs челленджам
  3. Для героев: streak+1, XP_PER_WEEK, проверяем milestone
  4. Для должников: streak = 0
  5. Сбрасываем current_runs / current_value для weekly_runs
  6. Топ-5 по XP
  7. Мероприятия недели
  8. Результаты завершённых турниров этой недели
  9. Публикуем в группу
  10. Отправляем каждому участнику личный отчёт по его челленджам
"""

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select, func

import config
from database import async_session
from models import (
    Challenge, Event, Report, TournamentParticipant,
    User, WeeklyTournament,
)

log = logging.getLogger(__name__)

_XP_WEEK   = config.XP_PER_WEEK
_MILESTONES: dict[int, int] = config.STREAK_MILESTONES


def _user_name(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or user.school_nick


def _week_range() -> tuple[datetime, datetime]:
    """Пн 00:00 — Вс 23:59 текущей недели."""
    now   = datetime.now()
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


# ─────────────────────────────────────────────────────────────
# Основная функция
# ─────────────────────────────────────────────────────────────

async def send_weekly_digest(bot: Bot) -> None:
    if not config.GROUP_ID:
        log.warning("GROUP_ID не задан — дайджест пропущен")
        return

    week_start, week_end = _week_range()

    async with async_session() as session:

        # ── 1. Активность за неделю ─────────────────────────────────
        stats_res = await session.execute(
            select(
                func.count(Report.id).label("cnt"),
                func.coalesce(func.sum(Report.km), 0).label("km"),
                func.count(Report.user_tg_id.distinct()).label("users"),
            ).where(
                Report.is_approved == True,
                Report.created_at >= week_start,
                Report.created_at < week_end,
            )
        )
        stats = stats_res.one()
        total_trainings = stats.cnt
        total_km        = float(stats.km)
        active_users    = stats.users

        # ── 2. weekly_runs челленджи ────────────────────────────────
        ch_res = await session.execute(
            select(Challenge).where(
                Challenge.is_active == True,
                Challenge.ch_type   == "weekly_runs",
            )
        )
        weekly_challenges = list(ch_res.scalars().all())

        # ── 3. Герои / должники ─────────────────────────────────────
        heroes:          list[str] = []
        debtors:         list[str] = []
        milestone_lines: list[str] = []

        for ch in weekly_challenges:
            u_res = await session.execute(
                select(User).where(User.tg_id == ch.user_id)
            )
            user = u_res.scalar_one_or_none()
            if not user:
                continue

            name = _user_name(user)

            if ch.current_runs >= ch.goal_runs:
                user.streak          += 1
                user.xp              += _XP_WEEK
                user.season_xp       += _XP_WEEK
                user.level            = user.xp // 100
                user.last_week_closed = datetime.now()

                heroes.append(
                    f"• {name} — {ch.current_runs} тренировок "
                    f"({ch.current_value:.1f} км) 🔥{user.streak}"
                )

                if user.streak in _MILESTONES:
                    bonus           = _MILESTONES[user.streak]
                    user.xp        += bonus
                    user.season_xp += bonus
                    user.level      = user.xp // 100
                    milestone_lines.append(
                        f"{name} — {user.streak} недель без пропусков! (+{bonus} XP)"
                    )
            else:
                user.streak = 0
                penalty_str = f"💰 {ch.penalty}" if ch.penalty else ""
                debtors.append(
                    f"• {name} ({ch.current_runs}/{ch.goal_runs}) {penalty_str}".strip()
                )

            ch.current_runs  = 0
            ch.current_value = 0.0

        # ── 4. Топ-5 по XP ─────────────────────────────────────────
        top_res = await session.execute(
            select(User).order_by(User.xp.desc()).limit(5)
        )
        top_users = list(top_res.scalars().all())

        # ── 5. Мероприятия этой недели ──────────────────────────────
        events_res = await session.execute(
            select(Event).where(
                Event.event_date >= week_start,
                Event.event_date <  week_end,
                Event.is_active  == True,
            )
        )
        week_events = list(events_res.scalars().all())

        # ── 6. Завершённые турниры этой недели ─────────────────────
        finished_tours_res = await session.execute(
            select(WeeklyTournament).where(
                WeeklyTournament.is_active == False,
                WeeklyTournament.end_date  >= week_start,
                WeeklyTournament.end_date  <  week_end,
            )
        )
        finished_tours = list(finished_tours_res.scalars().all())

        await session.commit()

    # ── Собираем текст ───────────────────────────────────────────────
    week_start_str = week_start.strftime("%d.%m")
    week_end_str   = (week_end - timedelta(seconds=1)).strftime("%d.%m.%Y")

    lines: list[str] = [
        "📊 <b>ДАЙДЖЕСТ НЕДЕЛИ — IT БЕГОТНЯ 21</b>",
        f"Период: {week_start_str} – {week_end_str}",
        "",
        "🏃 <b>АКТИВНОСТЬ КЛУБА</b>",
        f"Всего км: {total_km:.1f}  |  Тренировок: {total_trainings}  |  Участников: {active_users}",
        "",
    ]

    if heroes:
        lines.append("✅ <b>ГЕРОИ НЕДЕЛИ</b> (выполнили норму)")
        lines.extend(heroes)
        lines.append("")

    if debtors:
        lines.append("🍕 <b>ДОЛЖНИКИ</b> (не выполнили норму)")
        lines.extend(debtors)
        lines.append("")

    if top_users:
        lines.append("🏆 <b>ТОП-5 ПО XP</b>")
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        for i, u in enumerate(top_users):
            lines.append(f"{medals[i]} {_user_name(u)} — {u.xp} XP 🔥{u.streak}")
        lines.append("")

    if milestone_lines:
        lines.append("🔥 <b>MILESTONE СТРИКИ</b>")
        for ml in milestone_lines:
            lines.append(f"• {ml}")
        lines.append("")

    if week_events:
        lines.append("📅 <b>МЕРОПРИЯТИЯ НЕДЕЛИ</b>")
        for ev in week_events:
            going = sum(1 for p in ev.participants if p.status == "going")
            lines.append(f"✅ {ev.title} — {going} участников")
        lines.append("")

    if finished_tours:
        for tour in finished_tours:
            from services.tournaments import get_leaderboard as tour_lb
            placements = await tour_lb(tour.id, limit=3)
            if placements:
                lines.append(f"🏆 <b>ТУРНИР: {tour.title}</b>")
                medals3 = ["🥇", "🥈", "🥉"]
                for row in placements:
                    pos    = row["position"]
                    medal  = medals3[pos - 1] if pos <= 3 else f"{pos}."
                    name   = _user_name(row["user"]) if row["user"] else f"user_{row['user_tg_id']}"
                    xp     = {1: 250, 2: 150, 3: 100}.get(pos, 0)
                    xp_str = f" (+{xp} XP)" if xp else ""
                    lines.append(f"{medal} {name} — {row['score']}{xp_str}")
                lines.append("")

    lines.append("Новая неделя — новые километры! Вперёд 🏃💪")

    # ── Публикуем ────────────────────────────────────────────────────
    try:
        await bot.send_message(
            config.GROUP_ID,
            "\n".join(lines),
        )
        log.info("Дайджест опубликован")
    except Exception as e:
        log.error(f"Ошибка публикации дайджеста: {e}")

    await _send_personal_challenge_reports(bot)


# ─────────────────────────────────────────────────────────────
# Личные отчёты по челленджам
# ─────────────────────────────────────────────────────────────

async def _send_personal_challenge_reports(bot: Bot) -> None:
    async with async_session() as session:
        users_res = await session.execute(
            select(User.tg_id).distinct().join(
                Challenge, Challenge.user_id == User.tg_id
            ).where(Challenge.is_active == True)
        )
        user_ids = [row[0] for row in users_res.all()]

    for tg_id in user_ids:
        try:
            await _send_one_personal_report(bot, tg_id)
        except Exception as e:
            log.warning(f"Личный отчёт user {tg_id}: {e}")


async def _send_one_personal_report(bot: Bot, tg_id: int) -> None:
    from services.challenges import CH_TYPE_NAMES

    async with async_session() as session:
        u_res = await session.execute(select(User).where(User.tg_id == tg_id))
        user  = u_res.scalar_one_or_none()
        if not user:
            return

        ch_res = await session.execute(
            select(Challenge).where(
                Challenge.user_id  == tg_id,
                Challenge.is_active == True,
            )
        )
        challenges = list(ch_res.scalars().all())

    if not challenges:
        return

    lines: list[str] = ["📋 <b>Твой отчёт по челленджам за неделю</b>", ""]

    for ch in challenges:
        type_name = CH_TYPE_NAMES.get(ch.ch_type, ch.ch_type)
        lines.append(f"<b>{ch.title}</b> ({type_name})")

        if ch.ch_type == "weekly_runs":
            icon = "✅" if ch.current_runs >= ch.goal_runs else "❌"
            lines.append(
                f"  {icon} Пробежек: {ch.current_runs}/{ch.goal_runs} "
                f"({ch.current_value:.1f} км)"
            )
        elif ch.ch_type in ("daily_km", "weekly_km", "monthly_km"):
            pct  = min(100, int(ch.current_value / ch.goal_value * 100)) if ch.goal_value else 0
            icon = "✅" if ch.current_value >= ch.goal_value else "🔄"
            lines.append(f"  {icon} {ch.current_value:.1f} / {ch.goal_value:.1f} км ({pct}%)")
        elif ch.ch_type == "race":
            icon = "✅" if ch.current_value >= ch.goal_value else "🎯"
            lines.append(f"  {icon} {ch.current_value:.1f} / {ch.goal_value:.1f} км")
            if ch.deadline:
                lines.append(f"  📅 Дата забега: {ch.deadline.strftime('%d.%m.%Y')}")

        if ch.penalty:
            lines.append(f"  💰 Ставка: {ch.penalty}")

        lines.append("")

    async with async_session() as session:
        u_res = await session.execute(select(User).where(User.tg_id == tg_id))
        user  = u_res.scalar_one_or_none()

    if user and user.streak > 0:
        lines.append(f"🔥 Стрик: {user.streak} недель")

    try:
        await bot.send_message(tg_id, "\n".join(lines))
    except Exception as e:
        log.debug(f"Личное сообщение {tg_id} не доставлено: {e}")