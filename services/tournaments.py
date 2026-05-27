"""
services/tournaments.py — бизнес-логика турниров.

Публичный API:
  create_tournament(title, tournament_type, created_by, duration_days) → WeeklyTournament
  get_active_tournament()                     → WeeklyTournament | None
  get_tournament(tournament_id)               → WeeklyTournament | None
  is_participant(tournament_id, user_tg_id)   → bool
  join_tournament(tournament_id, user_tg_id)  → dict
  update_score(tournament_id, user_tg_id, km, duration_min) → None
  finalize_tournament(tournament_id)          → dict
  get_leaderboard(tournament_id, limit)       → list[dict]
  get_expired_tournaments()                   → list[WeeklyTournament]

Паттерн сессий:
  Каждая функция открывает ОДИН async with async_session() as session.
  Транзакции управляются через await session.commit() / await session.rollback().
  Вложенные session.begin() не используются — это вызывает InvalidRequestError
  в SQLAlchemy 2.x при autobegin.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import config
from database import async_session
from models import User, WeeklyTournament, TournamentParticipant

log = logging.getLogger(__name__)

# XP за призовые места
TOURNAMENT_XP: dict[int, int] = {1: 250, 2: 150, 3: 100}

# Человекочитаемые типы
TOUR_TYPE_NAMES = {
    "km":      "🏃 Больше километров",
    "minutes": "⏱ Больше минут",
    "days":    "📅 Больше дней",
    "team_km": "👥 Командные км",
}


# ─────────────────────────────────────────────────────────────
# Создание
# ─────────────────────────────────────────────────────────────

async def create_tournament(
    title: str,
    tournament_type: str,
    created_by: int,
    duration_days: int = 7,
) -> WeeklyTournament:
    """
    Создаёт новый турнир и возвращает его объект.

    Args:
        title:           название
        tournament_type: km / minutes / days / team_km
        created_by:      tg_id администратора
        duration_days:   длительность в днях (по умолчанию 7)
    """
    now = datetime.now()
    end = now + timedelta(days=duration_days)

    async with async_session() as session:
        tour = WeeklyTournament(
            title=title,
            tournament_type=tournament_type,
            start_date=now,
            end_date=end,
            is_active=True,
            created_by=created_by,
        )
        session.add(tour)
        await session.commit()
        await session.refresh(tour)
        tour_id = tour.id

    # Перечитываем в новой сессии чтобы relationship participants загрузился
    async with async_session() as session:
        res = await session.execute(
            select(WeeklyTournament).where(WeeklyTournament.id == tour_id)
        )
        return res.scalar_one()


# ─────────────────────────────────────────────────────────────
# Получение
# ─────────────────────────────────────────────────────────────

async def get_tournament(tournament_id: int) -> WeeklyTournament | None:
    """Получить турнир по ID."""
    async with async_session() as session:
        res = await session.execute(
            select(WeeklyTournament).where(WeeklyTournament.id == tournament_id)
        )
        return res.scalar_one_or_none()


async def get_active_tournament() -> WeeklyTournament | None:
    """Вернуть последний активный турнир."""
    async with async_session() as session:
        res = await session.execute(
            select(WeeklyTournament)
            .where(WeeklyTournament.is_active == True)
            .order_by(WeeklyTournament.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()


async def get_expired_tournaments() -> list[WeeklyTournament]:
    """Вернуть активные турниры, срок которых уже истёк."""
    now = datetime.now()
    async with async_session() as session:
        res = await session.execute(
            select(WeeklyTournament).where(
                WeeklyTournament.is_active == True,
                WeeklyTournament.end_date <= now,
            )
        )
        return list(res.scalars().all())


async def is_participant(tournament_id: int, user_tg_id: int) -> bool:
    """Проверить, зарегистрирован ли пользователь в турнире."""
    async with async_session() as session:
        res = await session.execute(
            select(TournamentParticipant).where(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.user_tg_id == user_tg_id,
            )
        )
        return res.scalar_one_or_none() is not None


# ─────────────────────────────────────────────────────────────
# Регистрация участника
# ─────────────────────────────────────────────────────────────

async def join_tournament(tournament_id: int, user_tg_id: int) -> dict:
    """
    Зарегистрировать пользователя в турнире.

    Returns:
        {"ok": True}
        {"error": "not_found"}
        {"error": "not_active"}
        {"error": "already_joined"}
    """
    async with async_session() as session:
        # Проверяем турнир
        t_res = await session.execute(
            select(WeeklyTournament).where(WeeklyTournament.id == tournament_id)
        )
        tournament = t_res.scalar_one_or_none()
        if not tournament:
            return {"error": "not_found"}
        if not tournament.is_active:
            return {"error": "not_active"}

        # Дубль?
        p_res = await session.execute(
            select(TournamentParticipant).where(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.user_tg_id == user_tg_id,
            )
        )
        if p_res.scalar_one_or_none():
            return {"error": "already_joined"}

        # Добавляем
        try:
            session.add(TournamentParticipant(
                tournament_id=tournament_id,
                user_tg_id=user_tg_id,
                score=0.0,
            ))
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"error": "already_joined"}

    # Ретроактивный зачёт пробежек за период турнира
    await _retroactive_score(tournament_id, user_tg_id)

    return {"ok": True}


async def _retroactive_score(tournament_id: int, user_tg_id: int) -> None:
    """Засчитать уже одобренные отчёты пользователя за период турнира."""
    async with async_session() as session:
        t_res = await session.execute(
            select(WeeklyTournament).where(WeeklyTournament.id == tournament_id)
        )
        tournament = t_res.scalar_one_or_none()
        if not tournament:
            return

        from models import Report
        reports_res = await session.execute(
            select(Report).where(
                Report.user_tg_id == user_tg_id,
                Report.is_approved == True,
                Report.created_at >= tournament.start_date,
            )
        )
        reports = reports_res.scalars().all()

        total_score = 0.0
        for r in reports:
            t_type = tournament.tournament_type
            if t_type in ("km", "team_km"):
                total_score += r.km or 0
            elif t_type == "minutes":
                total_score += r.duration_min or 0
            else:  # days
                total_score += 1

        if total_score <= 0:
            return

        p_res = await session.execute(
            select(TournamentParticipant).where(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.user_tg_id == user_tg_id,
            )
        )
        participant = p_res.scalar_one_or_none()
        if participant:
            participant.score = total_score
            await session.commit()


# ─────────────────────────────────────────────────────────────
# Обновление очков при одобрении отчёта
# ─────────────────────────────────────────────────────────────

async def update_score(
    tournament_id: int,
    user_tg_id: int,
    km: float,
    duration_min: int | None = None,
) -> None:
    """
    Прибавить очки участнику после одобрения отчёта.

    Логика:
      km / team_km → score += km
      minutes      → score += duration_min
      days         → score += 1 (каждый одобренный отчёт = 1 день)
    """
    async with async_session() as session:
        t_res = await session.execute(
            select(WeeklyTournament).where(WeeklyTournament.id == tournament_id)
        )
        tournament = t_res.scalar_one_or_none()
        if not tournament or not tournament.is_active:
            return

        p_res = await session.execute(
            select(TournamentParticipant).where(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.user_tg_id == user_tg_id,
            )
        )
        participant = p_res.scalar_one_or_none()
        if not participant:
            return

        t_type = tournament.tournament_type
        if t_type in ("km", "team_km"):
            participant.score += km
        elif t_type == "minutes":
            if duration_min:
                participant.score += duration_min
        elif t_type == "days":
            participant.score += 1

        await session.commit()


# ─────────────────────────────────────────────────────────────
# Таблица лидеров
# ─────────────────────────────────────────────────────────────

async def get_leaderboard(tournament_id: int, limit: int = 10) -> list[dict]:
    """
    Таблица участников турнира, отсортированная по score.

    Returns:
        [{"position": 1, "user": User|None, "score": 42.5, "user_tg_id": int}, ...]
    """
    async with async_session() as session:
        res = await session.execute(
            select(TournamentParticipant)
            .where(TournamentParticipant.tournament_id == tournament_id)
            .order_by(TournamentParticipant.score.desc())
            .limit(limit)
        )
        participants = list(res.scalars().all())

        rows = []
        for pos, p in enumerate(participants, 1):
            u_res = await session.execute(
                select(User).where(User.tg_id == p.user_tg_id)
            )
            rows.append({
                "position":   pos,
                "user":       u_res.scalar_one_or_none(),
                "score":      p.score,
                "user_tg_id": p.user_tg_id,
            })
        return rows


# ─────────────────────────────────────────────────────────────
# Финализация
# ─────────────────────────────────────────────────────────────

async def finalize_tournament(tournament_id: int, bot=None) -> dict:
    """
    Завершить турнир: определить призёров, начислить XP, деактивировать.
    Если передан bot — отправить личные уведомления всем участникам.
    """
    async with async_session() as session:
        t_res = await session.execute(
            select(WeeklyTournament).where(WeeklyTournament.id == tournament_id)
        )
        tournament = t_res.scalar_one_or_none()
        if not tournament:
            return {"error": "not_found"}
        if not tournament.is_active:
            return {"error": "already_finalized"}

        tour_title = tournament.title
        tour_type  = tournament.tournament_type

        # Топ участников
        p_res = await session.execute(
            select(TournamentParticipant)
            .where(TournamentParticipant.tournament_id == tournament_id)
            .order_by(TournamentParticipant.score.desc())
        )
        participants = list(p_res.scalars().all())

        placements = []
        for pos, p in enumerate(participants, 1):
            u_res = await session.execute(
                select(User).where(User.tg_id == p.user_tg_id)
            )
            user = u_res.scalar_one_or_none()
            xp_bonus = TOURNAMENT_XP.get(pos, 0)

            # Начисляем XP призёрам
            if user and xp_bonus:
                user.xp += xp_bonus
                user.season_xp += xp_bonus
                from services.xp import calc_level
                user.level = calc_level(user.xp)

            placements.append({
                "position":   pos,
                "user":       user,
                "score":      p.score,
                "xp":         xp_bonus,
                "user_tg_id": p.user_tg_id,
            })

        # Запоминаем победителя и закрываем
        if participants:
            tournament.winner_tg_id = participants[0].user_tg_id
        tournament.is_active = False

        await session.commit()

    result = {
        "title":      tour_title,
        "type":       tour_type,
        "placements": placements,
    }

    # Уведомляем участников в личку
    if bot and placements:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for row in placements:
            pos   = row["position"]
            score = row["score"]
            xp    = row["xp"]
            uid   = row["user_tg_id"]

            if tour_type in ("km", "team_km"):
                score_str = f"{score:.1f} км"
            elif tour_type == "minutes":
                score_str = f"{int(score)} мин"
            else:
                score_str = f"{int(score)} дн"

            medal = medals.get(pos, f"{pos}-е место")
            xp_str = f"\n💠 +{xp} XP за призовое место!" if xp else ""
            place_str = f"{medal} {pos}-е место" if pos <= 3 else f"{pos}-е место"

            try:
                await bot.send_message(
                    uid,
                    f"🏆 <b>Турнир завершён!</b>\n\n"
                    f"<b>{tour_title}</b>\n"
                    f"Твой результат: <b>{score_str}</b>\n"
                    f"Итог: {place_str}"
                    f"{xp_str}",
                    parse_mode="HTML",
                )
            except Exception as e:
                log.warning("Не удалось уведомить участника %s о завершении турнира: %s", uid, e)

    # Публикуем итоги в болталку
    if bot and placements:
        from services.scheduler import _post_to_digest
        medals_map = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [f"🏆 <b>Турнир «{tour_title}» завершён!</b>\n"]
        for row in placements[:3]:
            pos = row["position"]
            score = row["score"]
            user = row["user"]
            name = (f"@{user.username}" if user and user.username
                    else (user.school_nick if user else str(row["user_tg_id"])))
            if tour_type in ("km", "team_km"):
                s = f"{score:.1f} км"
            elif tour_type == "minutes":
                s = f"{int(score)} мин"
            else:
                s = f"{int(score)} дн"
            medal = medals_map.get(pos, f"{pos}.")
            lines.append(f"{medal} {name} — {s}")
        try:
            await _post_to_digest(bot, "\n".join(lines))
        except Exception as e:
            log.warning("Не удалось опубликовать итоги турнира: %s", e)

    return result