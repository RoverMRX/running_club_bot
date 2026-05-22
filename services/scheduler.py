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

    # ── Отправка очереди уведомлений от webapp: каждые 10 секунд ────
    scheduler.add_job(
        _send_pending_notifications,
        trigger=IntervalTrigger(seconds=10),
        args=[bot],
        id="send_pending_notifications",
        replace_existing=True,
    )
    log.info("📬 Очередь уведомлений: каждые 10 секунд")

    # ── Проверка истёкших челленджей: каждые 15 минут ──────────────
    scheduler.add_job(
        _expire_challenges,
        trigger=IntervalTrigger(minutes=15),
        args=[bot],
        id="expire_challenges",
        replace_existing=True,
    )
    log.info("⏰ Проверка истёкших челленджей: каждые 15 минут")

    print(f"   📅 Планировщик: дайджест вс 21:00 ({OMSK_TZ})")


async def _finalize_expired_tournaments(bot: Bot) -> None:
    """
    Ищет истёкшие активные турниры, финализирует их и публикует итоги.
    """
    from services.tournaments import get_expired_tournaments, finalize_tournament, TOUR_TYPE_NAMES

    expired = await get_expired_tournaments()
    for tournament in expired:
        try:
            result = await finalize_tournament(tournament.id, bot=bot)
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

async def _notify_pending_events(bot: Bot) -> None:
    """
    Каждые 2 минуты проверяет новые мероприятия на модерации
    и уведомляет администраторов/модераторов.
    Чтобы не дублировать — после отправки ставит notified_at.
    """
    from database import async_session
    from models import Event, Moderator
    from sqlalchemy import select
    from keyboards import get_event_moderation_kb
    from services.events import format_announce

    async with async_session() as session:
        # Берём только не уведомлённые pending события
        res = await session.execute(
            select(Event).where(
                Event.is_pending == True,
                Event.is_active == True,
                Event.notified_at == None,
            )
        )
        events = res.scalars().all()

        if not events:
            return

        # Собираем список получателей
        mods_res = await session.execute(select(Moderator))
        mods = mods_res.scalars().all()
        recipients = list(config.ADMIN_IDS) + [
            m.tg_id for m in mods if m.tg_id not in config.ADMIN_IDS
        ]

        for event in events:
            try:
                text = (
                    f"🆕 <b>Новое мероприятие на модерации</b>\n\n"
                    f"{format_announce(event)}\n\n"
                    f"Создал: ID <code>{event.created_by}</code>"
                )
                kb = get_event_moderation_kb(event.id)

                for tg_id in recipients:
                    try:
                        await bot.send_message(tg_id, text, reply_markup=kb)
                    except Exception:
                        pass

                # Помечаем как уведомлённое
                from datetime import datetime
                event.notified_at = datetime.now()

            except Exception as e:
                log.error(f"Ошибка уведомления о событии {event.id}: {e}")

        await session.commit()


async def _expire_challenges(bot) -> None:
    """
    Проверяет челленджи с истёкшим дедлайном, деактивирует их
    и уведомляет автора и участников.
    """
    from datetime import datetime
    from sqlalchemy import select
    from database import async_session
    from models import Challenge, ChallengeParticipant, User

    now = datetime.now()

    async with async_session() as session:
        res = await session.execute(
            select(Challenge).where(
                Challenge.is_active == True,
                Challenge.deadline != None,
                Challenge.deadline <= now,
            )
        )
        expired = res.scalars().all()

        for ch in expired:
            ch.is_active = False

            # Собираем ID для уведомления: автор + участники
            notify_ids: list[int] = [ch.user_id]

            parts_res = await session.execute(
                select(ChallengeParticipant).where(
                    ChallengeParticipant.challenge_id == ch.id
                )
            )
            for p in parts_res.scalars().all():
                if p.user_id not in notify_ids:
                    notify_ids.append(p.user_id)

            ch_title    = ch.title
            ch_progress = ch.current_value
            ch_goal     = ch.goal_value

            for uid in notify_ids:
                is_author = (uid == ch.user_id)
                role_str  = "твой" if is_author else "совместный"
                try:
                    await bot.send_message(
                        uid,
                        f"⏰ <b>Дедлайн истёк!</b>\n\n"
                        f"Челлендж «{ch_title}» завершён.\n"
                        f"Прогресс: {ch_progress:.1f} из {ch_goal:.1f}\n\n"
                        f"Это был {role_str} челлендж.",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    log.warning("Не удалось уведомить %s об истечении челленджа: %s", uid, e)

        await session.commit()


async def _send_pending_notifications(bot) -> None:
    """Забирает уведомления из таблицы pending_notifications и отправляет их."""
    from sqlalchemy import select, update
    from database import async_session
    from models import PendingNotification
    import json
    from aiogram.types import InlineKeyboardMarkup

    async with async_session() as session:
        res = await session.execute(
            select(PendingNotification)
            .where(PendingNotification.sent == False)
            .order_by(PendingNotification.created_at)
            .limit(20)
        )
        pending = res.scalars().all()

        for notif in pending:
            try:
                kb = None
                if notif.kb_json:
                    try:
                        kb = InlineKeyboardMarkup.model_validate_json(notif.kb_json)
                    except Exception:
                        kb = None

                await bot.send_message(
                    notif.user_tg_id,
                    notif.text,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
                notif.sent = True
            except Exception as e:
                import logging
                logging.getLogger("scheduler").warning(
                    f"Не удалось отправить уведомление {notif.id}: {e}"
                )

        await session.commit()