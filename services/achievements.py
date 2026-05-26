"""
services/achievements.py — проверка и выдача ачивментов.

Вызывается после каждого апрува отчёта из services/reports.py:
    await check_and_grant(user_tg_id, km, bot, report_created_at)

Также вызывается при:
    - финализации турнира (tournament_gold, tournament_hat)
    - первом мероприятии (first_event)
    - создании/вступлении в челлендж (first_challenge)
"""

import logging
from datetime import datetime
from sqlalchemy import select, func, text

from database import async_session
from models import User, Report, UserAchievement, Achievement

log = logging.getLogger(__name__)


async def _already_has(session, user_tg_id: int, slug: str) -> bool:
    res = await session.execute(
        select(UserAchievement).where(
            UserAchievement.user_tg_id == user_tg_id,
            UserAchievement.slug == slug,
        )
    )
    return res.scalar_one_or_none() is not None


async def _grant(session, user_tg_id: int, slug: str) -> bool:
    """Выдаёт ачивку если ещё нет. Возвращает True если выдана впервые."""
    if await _already_has(session, user_tg_id, slug):
        return False
    session.add(UserAchievement(user_tg_id=user_tg_id, slug=slug))
    return True


async def check_and_grant(
    user_tg_id: int,
    km: float,
    bot=None,
    report_created_at: datetime | None = None,
) -> list[str]:
    """
    Проверяет все условия и выдаёт новые ачивки.
    Возвращает список slug'ов выданных ачивок.
    Если передан bot — отправляет уведомление в личку.
    """
    granted: list[str] = []
    now = report_created_at or datetime.now()

    async with async_session() as session:
        async with session.begin():

            # ── Суммарный пробег пользователя ──────────────────
            total_res = await session.execute(
                select(func.sum(Report.km)).where(
                    Report.user_tg_id == user_tg_id,
                    Report.is_approved == True,
                )
            )
            total_km = float(total_res.scalar() or 0)

            for threshold, slug in [
                (1,    "km_1"),
                (10,   "km_10"),
                (100,  "km_100"),
                (500,  "km_500"),
                (1000, "km_1000"),
                (5000, "km_5000"),
            ]:
                if total_km >= threshold and await _grant(session, user_tg_id, slug):
                    granted.append(slug)

            # ── Стрик ───────────────────────────────────────────
            user_res = await session.execute(select(User).where(User.tg_id == user_tg_id))
            user = user_res.scalar_one_or_none()
            if user:
                streak = user.streak or 0
                for weeks, slug in [
                    (1,  "streak_1"),
                    (4,  "streak_4"),
                    (12, "streak_12"),
                    (24, "streak_24"),
                    (52, "streak_52"),
                ]:
                    if streak >= weeks and await _grant(session, user_tg_id, slug):
                        granted.append(slug)

            # ── PR по одной пробежке ────────────────────────────
            for threshold, slug in [
                (5.0,  "pr_5"),
                (10.0, "pr_10"),
                (21.1, "pr_half"),
                (42.2, "pr_marathon"),
            ]:
                if km >= threshold and await _grant(session, user_tg_id, slug):
                    granted.append(slug)

            # ── Первый отчёт ────────────────────────────────────
            count_res = await session.execute(
                select(func.count(Report.id)).where(
                    Report.user_tg_id == user_tg_id,
                    Report.is_approved == True,
                )
            )
            report_count = count_res.scalar() or 0
            if report_count >= 1 and await _grant(session, user_tg_id, "first_report"):
                granted.append("first_report")

            # ── Особые: время пробежки ──────────────────────────
            hour = now.hour
            if hour < 7 and await _grant(session, user_tg_id, "early_bird"):
                granted.append("early_bird")
            if hour >= 22 and await _grant(session, user_tg_id, "night_owl"):
                granted.append("night_owl")

            # ── Зимняя пробежка ─────────────────────────────────
            if now.month in (12, 1, 2) and await _grant(session, user_tg_id, "winter_run"):
                granted.append("winter_run")

    if granted and bot:
        await _notify_user(bot, user_tg_id, granted)

    return granted


async def check_first_event(user_tg_id: int, bot=None) -> list[str]:
    """Вызвать когда пользователь посетил мероприятие."""
    async with async_session() as session:
        async with session.begin():
            if await _grant(session, user_tg_id, "first_event"):
                if bot:
                    await _notify_user(bot, user_tg_id, ["first_event"])
                return ["first_event"]
    return []


async def check_first_challenge(user_tg_id: int, bot=None) -> list[str]:
    """Вызвать когда пользователь создал или вступил в первый челлендж."""
    async with async_session() as session:
        async with session.begin():
            if await _grant(session, user_tg_id, "first_challenge"):
                if bot:
                    await _notify_user(bot, user_tg_id, ["first_challenge"])
                return ["first_challenge"]
    return []


async def check_tournament_finish(user_tg_id: int, place: int, bot=None) -> list[str]:
    """Вызвать при финализации турнира с местом участника."""
    granted = []
    async with async_session() as session:
        async with session.begin():
            if place == 1:
                if await _grant(session, user_tg_id, "tournament_gold"):
                    granted.append("tournament_gold")

                # Считаем победы
                wins_res = await session.execute(
                    select(func.count(UserAchievement.id)).where(
                        UserAchievement.user_tg_id == user_tg_id,
                        UserAchievement.slug == "tournament_gold",
                    )
                )
                wins = wins_res.scalar() or 0
                if wins >= 3 and await _grant(session, user_tg_id, "tournament_hat"):
                    granted.append("tournament_hat")

    if granted and bot:
        await _notify_user(bot, user_tg_id, granted)
    return granted


async def _notify_user(bot, user_tg_id: int, slugs: list[str]) -> None:
    """Отправляет уведомление о новых ачивках."""
    async with async_session() as session:
        names = []
        for slug in slugs:
            res = await session.execute(
                select(Achievement).where(Achievement.slug == slug)
            )
            ach = res.scalar_one_or_none()
            if ach:
                names.append(f"🏅 <b>{ach.name}</b> — {ach.description}")

    if not names:
        return

    text = "🎉 <b>Новые ачивки!</b>\n\n" + "\n".join(names)
    try:
        await bot.send_message(user_tg_id, text, parse_mode="HTML")
    except Exception as e:
        log.warning("Не удалось отправить ачивки %s: %s", user_tg_id, e)


async def get_user_achievements(user_tg_id: int) -> list[dict]:
    """Возвращает список всех ачивок с флагом earned."""
    async with async_session() as session:
        # Все ачивки из справочника
        all_res = await session.execute(
            select(Achievement).order_by(Achievement.category, Achievement.slug)
        )
        all_ach = all_res.scalars().all()

        # Полученные пользователем
        earned_res = await session.execute(
            select(UserAchievement).where(UserAchievement.user_tg_id == user_tg_id)
        )
        earned_map = {
            ua.slug: ua.earned_at
            for ua in earned_res.scalars().all()
        }

    return [
        {
            "slug":        a.slug,
            "name":        a.name,
            "description": a.description,
            "category":    a.category,
            "image_url":   a.image_url,
            "earned":      a.slug in earned_map,
            "earned_at":   earned_map[a.slug].isoformat() if a.slug in earned_map else None,
        }
        for a in all_ach
    ]
