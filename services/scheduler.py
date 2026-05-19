"""
services/scheduler.py — все крон-задачи бота.

Задачи:
  weekly_digest   — каждое воскресенье в 21:00 Asia/Omsk
  finalize_tours  — каждые 15 минут проверяем истёкшие турниры
"""

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from services.digest import send_weekly_digest

log = logging.getLogger(__name__)

# Часовой пояс для дайджеста (Омск UTC+6)
OMSK_TZ = "Asia/Omsk"


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Регистрирует все задачи в планировщике."""

    # ── Еженедельный дайджест: воскресенье 21:00 Asia/Omsk ──────────
    scheduler.add_job(
        send_weekly_digest,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=21,
            minute=0,
            timezone=OMSK_TZ,
        ),
        args=[bot],
        id="weekly_digest",
        replace_existing=True,
        misfire_grace_time=600,   # Допускаем опоздание до 10 минут
    )
    log.info("📅 Дайджест запланирован: вс 21:00 Asia/Omsk")

    # ── Автофинализация истёкших турниров: каждые 15 минут ───────────
    scheduler.add_job(
        _finalize_expired_tournaments,
        trigger=IntervalTrigger(minutes=15),
        args=[bot],
        id="finalize_tours",
        replace_existing=True,
    )
    log.info("🏆 Проверка турниров: каждые 15 минут")

    # ── Ежедневная таблица активного турнира: 21:00 Asia/Omsk ────────
    scheduler.add_job(
        _publish_daily_tournament_table,
        trigger=CronTrigger(hour=21, minute=0, timezone=OMSK_TZ),
        args=[bot],
        id="daily_tour_table",
        replace_existing=True,
        misfire_grace_time=600,
    )
    log.info("📊 Ежедневная таблица турнира: 21:00 Asia/Omsk")

    print(f"   📅 Планировщик: дайджест вс 21:00 ({OMSK_TZ})")


async def _finalize_expired_tournaments(bot: Bot) -> None:
    """
    Ищет истёкшие активные турниры, финализирует их и публикует итоги.
    """
    from services.tournaments import get_expired_tournaments, finalize_tournament, TOUR_TYPE_NAMES

    expired = await get_expired_tournaments()
    for tournament in expired:
        try:
            result = await finalize_tournament(tournament.id)
            if "error" in result:
                log.warning(f"Ошибка финализации турнира {tournament.id}: {result['error']}")
                continue

            log.info(f"Турнир {tournament.id} ({result['title']}) финализирован")
            await _publish_tournament_results(bot, result)

        except Exception as e:
            log.error(f"Исключение при финализации турнира {tournament.id}: {e}")


async def _publish_tournament_results(bot: Bot, result: dict) -> None:
    """Публикует итоги завершённого турнира в группу."""
    if not config.GROUP_ID:
        return

    title      = result["title"]
    placements = result["placements"]

    if not placements:
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>ИТОГИ ТУРНИРА: {title}</b>", ""]

    for row in placements[:3]:
        pos   = row["position"]
        user  = row["user"]
        score = row["score"]
        xp    = row["xp"]
        medal = medals[pos - 1] if pos <= 3 else f"{pos}."

        if user:
            name = f"@{user.username}" if user.username else user.school_nick
        else:
            name = f"user_{row.get('user_tg_id', '?')}"

        xp_str = f" (+{xp} XP)" if xp else ""
        lines.append(f"{medal} {name} — {score}{xp_str}")

    lines.append("")
    lines.append("Поздравляем победителей! 🎉")

    try:
        await bot.send_message(
            config.GROUP_ID,
            "\n".join(lines),
            message_thread_id=config.DIGEST_THREAD_ID,
        )
    except Exception as e:
        log.error(f"Ошибка публикации итогов турнира: {e}")


async def _publish_daily_tournament_table(bot: Bot) -> None:
    """
    Публикует текущую таблицу активного турнира каждый день в 21:00.
    По воскресеньям не публикует — в этот день выходит полный дайджест.
    """
    from datetime import datetime as dt
    if dt.now().weekday() == 6:  # воскресенье — дайджест сам покажет
        return

    from services.tournaments import get_active_tournament, get_leaderboard, TOUR_TYPE_NAMES
    tournament = await get_active_tournament()
    if not tournament or not config.GROUP_ID:
        return

    rows = await get_leaderboard(tournament.id, limit=5)
    if not rows:
        return

    type_label = TOUR_TYPE_NAMES.get(tournament.tournament_type, tournament.tournament_type)
    end_str    = tournament.end_date.strftime("%d.%m %H:%M")
    medals     = ["🥇", "🥈", "🥉", "4.", "5."]

    lines = [
        f"🏆 <b>{tournament.title}</b> — таблица дня",
        f"{type_label} · до {end_str}",
        "",
    ]
    for row in rows:
        pos   = row["position"]
        user  = row["user"]
        name  = (f"@{user.username}" if user.username else user.school_nick) if user else f"id{row['user_tg_id']}"
        score = row["score"]
        medal = medals[pos - 1] if pos <= 5 else f"{pos}."

        t_type = tournament.tournament_type
        if t_type in ("km", "team_km"):
            score_str = f"{score:.1f} км"
        elif t_type == "minutes":
            score_str = f"{int(score)} мин"
        else:
            score_str = f"{int(score)} дн"

        lines.append(f"{medal} {name} — {score_str}")

    try:
        await bot.send_message(config.GROUP_ID, "\n".join(lines))
    except Exception as e:
        log.error(f"Ошибка публикации ежедневной таблицы: {e}")