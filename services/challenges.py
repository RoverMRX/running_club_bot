"""
services/challenges.py — бизнес-логика челленджей.

Архитектура (после рефакторинга):
  - Автор создаёт челлендж (parent_id=None, is_public=True)
  - Участник присоединяется → создаётся дочерний Challenge
    (parent_id=родительский_id, is_public=False, user_id=участник)
  - В клубе показываются только parent_id IS NULL AND is_public=True
  - В "Мои" — собственные (parent_id IS NULL, user_id=я)
                + дочерние (parent_id NOT NULL, user_id=я)
  - Прогресс каждого участника — в его дочернем челлендже
  - Завершение независимо

Типы:
  weekly_runs  — регулярный: N пробежек/неделю
  daily_km     — дневной спринт: N км за день
  weekly_km    — недельный спринт: N км за неделю
  monthly_km   — месячный спринт: N км за месяц
  race         — разовый забег: N км за время T
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from database import async_session
from models import Challenge, ChallengeParticipant, User

log = logging.getLogger(__name__)

# Человекочитаемые названия типов
CH_TYPE_NAMES = {
    "weekly_runs": "📜 Регулярный",
    "daily_km":    "🎯 Дневной спринт",
    "weekly_km":   "📅 Недельный спринт",
    "monthly_km":  "📆 Месячный спринт",
    "race":        "🏃 Разовый забег",
}

# Автоматический срок для спринтов (в днях)
_SPRINT_DAYS = {
    "daily_km":   1,
    "weekly_km":  7,
    "monthly_km": 30,
}


def get_type_name(ch_type: str) -> str:
    return CH_TYPE_NAMES.get(ch_type, ch_type)


def _calc_deadline(ch_type: str, started_at: datetime) -> datetime | None:
    days = _SPRINT_DAYS.get(ch_type)
    if days is not None:
        return started_at + timedelta(days=days)
    return None


async def create_challenge(
    user_id: int,
    title: str,
    ch_type: str,
    *,
    min_per_run: float = 0.0,
    min_minutes_per_run: int = 0,
    goal_runs: int = 0,
    goal_value: float = 0.0,
    goal_time: int | None = None,
    penalty: str | None = None,
    is_public: bool = True,
    started_at: datetime | None = None,
    deadline: datetime | None = None,
    parent_id: int | None = None,
) -> Challenge:
    started_at = started_at or datetime.now()
    auto_deadline = _calc_deadline(ch_type, started_at)
    if auto_deadline is not None:
        deadline = auto_deadline

    async with async_session() as session:
        async with session.begin():
            ch = Challenge(
                user_id=user_id,
                title=title,
                ch_type=ch_type,
                min_per_run=min_per_run,
                min_minutes_per_run=min_minutes_per_run,
                goal_runs=goal_runs,
                goal_value=goal_value,
                goal_time=goal_time,
                penalty=penalty,
                is_public=is_public,
                is_active=True,
                started_at=started_at,
                deadline=deadline,
                parent_id=parent_id,
            )
            session.add(ch)
            await session.flush()
            ch_id = ch.id

    return await get_challenge(ch_id)


async def get_challenge(challenge_id: int) -> Challenge | None:
    async with async_session() as session:
        res = await session.execute(
            select(Challenge).where(Challenge.id == challenge_id)
        )
        return res.scalar_one_or_none()


async def get_user_challenges(user_id: int, active_only: bool = True) -> dict:
    """
    Возвращает {'own': [...], 'joined': [...]}
    own   — родительские челленджи пользователя (parent_id IS NULL)
    joined — дочерние (parent_id NOT NULL, т.е. копии чужих)
    """
    async with async_session() as session:
        # Свои (корневые)
        q = select(Challenge).where(
            Challenge.user_id == user_id,
            Challenge.parent_id.is_(None),
        )
        if active_only:
            q = q.where(Challenge.is_active == True)
        own_res = await session.execute(q)
        own = list(own_res.scalars().all())

        # Дочерние (участие в чужих)
        q2 = select(Challenge).where(
            Challenge.user_id == user_id,
            Challenge.parent_id.isnot(None),
        )
        if active_only:
            q2 = q2.where(Challenge.is_active == True)
        joined_res = await session.execute(q2)
        joined = list(joined_res.scalars().all())

    return {'own': own, 'joined': joined}


async def get_public_challenges(exclude_user: int | None = None, limit: int = 20) -> list[Challenge]:
    """Список публичных активных корневых челленджей (для присоединения)."""
    async with async_session() as session:
        q = select(Challenge).where(
            Challenge.is_active == True,
            Challenge.is_public == True,
            Challenge.parent_id.is_(None),   # только родительские
        )
        if exclude_user is not None:
            q = q.where(Challenge.user_id != exclude_user)
        q = q.order_by(Challenge.created_at.desc()).limit(limit)
        res = await session.execute(q)
        return list(res.scalars().all())


async def join_challenge(challenge_id: int, user_id: int, penalty: str | None = None) -> dict:
    """
    Присоединить пользователя к чужому челленджу:
    создаёт дочерний Challenge (parent_id=challenge_id, is_public=False).
    """
    async with async_session() as session:
        async with session.begin():
            # Проверяем родительский челлендж
            ch_res = await session.execute(
                select(Challenge).where(Challenge.id == challenge_id)
            )
            ch = ch_res.scalar_one_or_none()

            if not ch or not ch.is_active:
                return {'ok': False, 'reason': 'Челлендж не найден или завершён.'}
            if not ch.is_public or ch.parent_id is not None:
                return {'ok': False, 'reason': 'Челлендж закрыт для присоединения.'}
            if ch.user_id == user_id:
                return {'ok': False, 'reason': 'Это твой собственный челлендж.'}

            # Уже участвует? (дочерний с таким parent_id уже есть)
            exist_res = await session.execute(
                select(Challenge).where(
                    Challenge.parent_id == challenge_id,
                    Challenge.user_id == user_id,
                )
            )
            if exist_res.scalar_one_or_none():
                return {'ok': False, 'reason': 'Ты уже участвуешь в этом челлендже.'}

            # Рассчитываем дедлайн дочернего — длительность от сегодня
            now = datetime.now()
            child_deadline = None
            if ch.deadline and ch.started_at:
                duration = ch.deadline - ch.started_at
                child_deadline = now + duration

            child = Challenge(
                user_id=user_id,
                title=ch.title,
                ch_type=ch.ch_type,
                min_per_run=ch.min_per_run or 0.0,
                min_minutes_per_run=ch.min_minutes_per_run or 0,
                goal_runs=ch.goal_runs or 0,
                goal_value=ch.goal_value or 0.0,
                goal_time=ch.goal_time,
                penalty=penalty,
                is_public=False,
                is_active=True,
                started_at=now,
                deadline=child_deadline,
                parent_id=challenge_id,
            )
            session.add(child)
            await session.flush()

    return {'ok': True, 'reason': f'Ты присоединился к «{ch.title}»!'}


async def leave_challenge(challenge_id: int, user_id: int) -> bool:
    """
    Покинуть чужой челлендж — деактивируем дочерний.
    Поддерживает как parent_id=challenge_id (новая архитектура),
    так и ChallengeParticipant (старая, для совместимости).
    """
    async with async_session() as session:
        async with session.begin():
            # Новая архитектура: дочерний челлендж
            res = await session.execute(
                select(Challenge).where(
                    Challenge.parent_id == challenge_id,
                    Challenge.user_id == user_id,
                    Challenge.is_active == True,
                )
            )
            child = res.scalar_one_or_none()
            if child:
                child.is_active = False
                child.result = "closed"
                return True

            # Старая архитектура: ChallengeParticipant
            res2 = await session.execute(
                select(ChallengeParticipant).where(
                    ChallengeParticipant.challenge_id == challenge_id,
                    ChallengeParticipant.user_id == user_id,
                )
            )
            part = res2.scalar_one_or_none()
            if part:
                await session.delete(part)
                return True

    return False


def is_run_counts(challenge: Challenge, km: float, minutes: int | None) -> bool:
    """
    Проверяет засчитываемость пробежки. ИЛИ-логика между км и минутами.
    """
    has_km_req      = challenge.min_per_run > 0
    has_minutes_req = challenge.min_minutes_per_run > 0

    if not has_km_req and not has_minutes_req:
        return True
    if has_km_req and km >= challenge.min_per_run:
        return True
    if has_minutes_req and minutes is not None and minutes >= challenge.min_minutes_per_run:
        return True
    return False


async def update_on_report(
    user_id: int,
    km: float,
    minutes: int | None = None,
    duration_sec: int | None = None,
) -> dict:
    """
    Обновляет прогресс всех активных челленджей пользователя.
    Для race-челленджей дополнительно проверяет duration_sec vs goal_time.
    """
    updated = []
    completed = []

    async with async_session() as session:
        async with session.begin():
            now = datetime.now()

            all_res = await session.execute(
                select(Challenge).where(
                    Challenge.user_id == user_id,
                    Challenge.is_active == True,
                )
            )
            for ch in all_res.scalars().all():
                if ch.pause_until and ch.pause_until > now:
                    continue
                if not is_run_counts(ch, km, minutes):
                    continue

                ch.current_runs += 1
                ch.current_value += km
                if minutes:
                    ch.current_time += minutes

                label = ch.title if ch.parent_id is None else f"{ch.title} (участие)"
                updated.append(label)

                goal_reached = _is_goal_reached(ch)

                # Для race-челленджа: учитываем время если задан goal_time
                if ch.ch_type == "race" and ch.goal_time and duration_sec is not None:
                    goal_sec = ch.goal_time * 60
                    goal_reached = goal_reached and duration_sec <= goal_sec

                if goal_reached:
                    ch.is_active = False
                    ch.result = "completed"
                    xp_bonus = _challenge_xp(ch)
                    if xp_bonus:
                        await _grant_participant_xp(user_id, xp_bonus)
                    completed.append(label)

    return {'updated': updated, 'completed': completed}


def _is_goal_reached(ch: Challenge) -> bool:
    if ch.ch_type in ("daily_km", "weekly_km", "monthly_km", "race"):
        return ch.current_value >= ch.goal_value > 0
    return False


def _challenge_xp(ch) -> int:
    import config as _cfg
    if ch.ch_type == "weekly_runs":
        return 0
    if not ch.started_at or not ch.deadline:
        return _cfg.XP_CHALLENGE_WEEK
    duration = (ch.deadline - ch.started_at).days
    if duration <= 1:
        return _cfg.XP_CHALLENGE_DAY
    if duration <= 7:
        return _cfg.XP_CHALLENGE_WEEK
    if duration <= 62:
        return _cfg.XP_CHALLENGE_MONTH
    return _cfg.XP_CHALLENGE_LONG


async def _grant_participant_xp(user_id: int, xp: int) -> None:
    if xp <= 0:
        return
    async with async_session() as session:
        async with session.begin():
            from models import User as _User
            from sqlalchemy import select as _sel
            u = await session.execute(_sel(_User).where(_User.tg_id == user_id))
            user = u.scalar_one_or_none()
            if user:
                user.xp += xp
                user.season_xp += xp
                user.level = user.xp // 100


async def pause_challenge(challenge_id: int, until: datetime) -> bool:
    async with async_session() as session:
        async with session.begin():
            res = await session.execute(
                select(Challenge).where(Challenge.id == challenge_id)
            )
            ch = res.scalar_one_or_none()
            if not ch:
                return False
            ch.pause_until = until
            ch.frozen_at = datetime.now()
            return True


async def unfreeze_challenge(challenge_id: int) -> bool:
    async with async_session() as session:
        async with session.begin():
            res = await session.execute(
                select(Challenge).where(Challenge.id == challenge_id)
            )
            ch = res.scalar_one_or_none()
            if not ch:
                return False
            if ch.frozen_at and ch.deadline:
                frozen_duration = datetime.now() - ch.frozen_at
                ch.deadline += frozen_duration
            ch.pause_until = None
            ch.frozen_at = None
            return True


async def close_challenge(challenge_id: int, result: str = "closed") -> bool:
    async with async_session() as session:
        async with session.begin():
            res = await session.execute(
                select(Challenge).where(Challenge.id == challenge_id)
            )
            ch = res.scalar_one_or_none()
            if not ch:
                return False
            ch.is_active = False
            ch.result = result
            return True


async def get_participants_count(challenge_id: int) -> int:
    """Сколько дочерних (активных) у родительского челленджа."""
    async with async_session() as session:
        res = await session.execute(
            select(func.count(Challenge.id)).where(
                Challenge.parent_id == challenge_id,
                Challenge.is_active == True,
            )
        )
        return res.scalar() or 0


async def get_child_challenge(parent_id: int, user_id: int) -> Challenge | None:
    """Получить дочерний челлендж пользователя по parent_id."""
    async with async_session() as session:
        res = await session.execute(
            select(Challenge).where(
                Challenge.parent_id == parent_id,
                Challenge.user_id == user_id,
            )
        )
        return res.scalar_one_or_none()