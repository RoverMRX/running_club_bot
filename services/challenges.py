"""
services/challenges.py — бизнес-логика челленджей.

Типы челленджей (ch_type):
  weekly_runs  — регулярный: N пробежек/неделю, условие зачёта км и/или минуты
  daily_km     — дневной спринт: N км за один день  (deadline = старт + 1 день)
  weekly_km    — недельный спринт: N км за неделю   (deadline = старт + 7 дней)
  monthly_km   — месячный спринт: N км за месяц     (deadline = старт + 30 дней)
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
    """Человекочитаемое название типа челленджа."""
    return CH_TYPE_NAMES.get(ch_type, ch_type)


def _calc_deadline(ch_type: str, started_at: datetime) -> datetime | None:
    """
    Автоматически рассчитывает deadline для спринтов.
    Для остальных типов возвращает None (deadline задаётся вручную или отсутствует).
    """
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
) -> Challenge:
    """
    Создаёт челлендж.

    Для спринтов (daily_km, weekly_km, monthly_km) deadline вычисляется
    автоматически от started_at и переданное значение deadline игнорируется.

    Returns:
        Созданный Challenge (отсоединённый от сессии).
    """
    started_at = started_at or datetime.now()

    # Для спринтов всегда считаем deadline сами, игнорируем переданный
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
            )
            session.add(ch)
            await session.flush()
            ch_id = ch.id

    # Возвращаем свежезагруженный объект
    return await get_challenge(ch_id)


async def get_challenge(challenge_id: int) -> Challenge | None:
    """Получить челлендж по ID."""
    async with async_session() as session:
        res = await session.execute(
            select(Challenge).where(Challenge.id == challenge_id)
        )
        return res.scalar_one_or_none()


async def get_user_challenges(user_id: int, active_only: bool = True) -> dict:
    """
    Челленджи пользователя — свои и те, к которым присоединился.

    Returns:
        {'own': [Challenge, ...], 'joined': [Challenge, ...]}
    """
    async with async_session() as session:
        # Свои
        q = select(Challenge).where(Challenge.user_id == user_id)
        if active_only:
            q = q.where(Challenge.is_active == True)
        own_res = await session.execute(q)
        own = own_res.scalars().all()

        # Присоединённые
        joined_res = await session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.user_id == user_id
            )
        )
        joined = []
        for part in joined_res.scalars().all():
            ch = part.challenge
            if ch and (not active_only or ch.is_active):
                joined.append(ch)

        return {'own': list(own), 'joined': joined}


async def get_public_challenges(exclude_user: int | None = None, limit: int = 20) -> list[Challenge]:
    """Список публичных активных челленджей (для присоединения)."""
    async with async_session() as session:
        q = select(Challenge).where(
            Challenge.is_active == True,
            Challenge.is_public == True,
        )
        if exclude_user is not None:
            q = q.where(Challenge.user_id != exclude_user)
        q = q.order_by(Challenge.created_at.desc()).limit(limit)

        res = await session.execute(q)
        return list(res.scalars().all())


async def join_challenge(challenge_id: int, user_id: int, penalty: str | None = None) -> dict:
    """
    Присоединить пользователя к чужому челленджу.

    Args:
        penalty: личная ставка участника (опционально)
    Returns:
        {'ok': bool, 'reason': str}
    """
    async with async_session() as session:
        async with session.begin():
            # Проверяем челлендж
            ch_res = await session.execute(
                select(Challenge).where(Challenge.id == challenge_id)
            )
            ch = ch_res.scalar_one_or_none()

            if not ch or not ch.is_active:
                return {'ok': False, 'reason': 'Челлендж не найден или завершён.'}
            if not ch.is_public:
                return {'ok': False, 'reason': 'Челлендж закрыт для присоединения.'}
            if ch.user_id == user_id:
                return {'ok': False, 'reason': 'Это твой собственный челлендж.'}

            # Уже участвует?
            exist_res = await session.execute(
                select(ChallengeParticipant).where(
                    ChallengeParticipant.challenge_id == challenge_id,
                    ChallengeParticipant.user_id == user_id,
                )
            )
            if exist_res.scalar_one_or_none():
                return {'ok': False, 'reason': 'Ты уже участвуешь в этом челлендже.'}

            # Добавляем
            try:
                session.add(ChallengeParticipant(
                    challenge_id=challenge_id,
                    user_id=user_id,
                    penalty=penalty,
                ))
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return {'ok': False, 'reason': 'Не удалось присоединиться.'}

            return {'ok': True, 'reason': f'Ты присоединился к «{ch.title}»!'}


async def leave_challenge(challenge_id: int, user_id: int) -> bool:
    """Выйти из чужого челленджа."""
    async with async_session() as session:
        async with session.begin():
            res = await session.execute(
                select(ChallengeParticipant).where(
                    ChallengeParticipant.challenge_id == challenge_id,
                    ChallengeParticipant.user_id == user_id,
                )
            )
            part = res.scalar_one_or_none()
            if not part:
                return False
            await session.delete(part)
            return True


def is_run_counts(challenge: Challenge, km: float, minutes: int | None) -> bool:
    """
    Проверяет, засчитывается ли пробежка по условиям челленджа.

    ИЛИ-логика: если заданы оба условия (км и минуты), пробежка
    засчитывается при выполнении ЛЮБОГО из них. Условия дополняют
    друг друга (быстрый интервал засчитается по минутам, медленный
    длинный кросс — по км), а не дублируют.

    Если не задано ни одного условия — засчитывается любая пробежка.
    """
    has_km_req      = challenge.min_per_run > 0
    has_minutes_req = challenge.min_minutes_per_run > 0

    # Нет условий вообще — засчитываем любую пробежку
    if not has_km_req and not has_minutes_req:
        return True

    # Выполнено условие по километрам
    if has_km_req and km >= challenge.min_per_run:
        return True

    # Выполнено условие по минутам
    if has_minutes_req and minutes is not None and minutes >= challenge.min_minutes_per_run:
        return True

    return False


async def update_on_report(user_id: int, km: float, minutes: int | None = None) -> dict:
    """
    Обновляет прогресс всех активных челленджей пользователя по новому отчёту.
    Вызывается после одобрения отчёта.

    Returns:
        {'updated': [названия челленджей], 'completed': [названия завершённых]}
    """
    updated = []
    completed = []

    async with async_session() as session:
        async with session.begin():
            now = datetime.now()

            # Собственные челленджи
            own_res = await session.execute(
                select(Challenge).where(
                    Challenge.user_id == user_id,
                    Challenge.is_active == True,
                )
            )
            for ch in own_res.scalars().all():
                # Пропускаем если на паузе
                if ch.pause_until and ch.pause_until > now:
                    continue
                if not is_run_counts(ch, km, minutes):
                    continue

                ch.current_runs += 1
                ch.current_value += km
                if minutes:
                    ch.current_time += minutes
                updated.append(ch.title)

                # Проверка завершения для целевых типов
                if _is_goal_reached(ch):
                    ch.is_active = False
                    ch.result = "completed"
                    xp_bonus = _challenge_xp(ch)
                    if xp_bonus:
                        await _grant_participant_xp(user_id, xp_bonus)
                    completed.append(ch.title)

            # Присоединённые челленджи — явный JOIN чтобы избежать lazy load
            joined_res = await session.execute(
                select(ChallengeParticipant, Challenge)
                .join(Challenge, Challenge.id == ChallengeParticipant.challenge_id)
                .where(
                    ChallengeParticipant.user_id == user_id,
                    Challenge.is_active == True,
                )
            )
            for part, ch in joined_res.all():
                if ch.pause_until and ch.pause_until > now:
                    continue
                if not is_run_counts(ch, km, minutes):
                    continue

                part.current_runs += 1
                part.current_value += km
                if minutes:
                    part.current_time += minutes
                updated.append(f"{ch.title} (совместный)")

                # Проверяем выполнение для участника
                if _is_goal_reached_for_participant(ch, part):
                    part.result = "completed"
                    xp_bonus = _challenge_xp(ch)
                    if xp_bonus:
                        await _grant_participant_xp(part.user_id, xp_bonus)
                    completed.append(f"{ch.title} (совместный)")

    return {'updated': updated, 'completed': completed}


def _is_goal_reached(ch: Challenge) -> bool:
    """Проверяет, достигнута ли цель челленджа (для спринтов и забегов)."""
    if ch.ch_type in ("daily_km", "weekly_km", "monthly_km", "race"):
        return ch.current_value >= ch.goal_value > 0
    return False


def _challenge_xp(ch) -> int:
    """XP за выполнение челленджа в зависимости от длительности."""
    import config as _cfg
    if ch.ch_type == "weekly_runs":
        # Бессрочный — XP за стрик выдаётся в дайджесте, здесь 0
        return 0
    if not ch.started_at or not ch.deadline:
        return _cfg.XP_CHALLENGE_WEEK
    duration = (ch.deadline - ch.started_at).days
    if duration <= 1:
        return _cfg.XP_CHALLENGE_DAY
    if duration <= 7:
        return _cfg.XP_CHALLENGE_WEEK
    if duration <= 62:  # ~2 месяца
        return _cfg.XP_CHALLENGE_MONTH
    return _cfg.XP_CHALLENGE_LONG


async def _grant_participant_xp(user_id: int, xp: int) -> None:
    """Начислить XP участнику за выполнение челленджа."""
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


def _is_goal_reached_for_participant(ch, part) -> bool:
    """Достигнута ли цель участника (его личный прогресс)."""
    if part.result:  # уже есть результат
        return False
    if ch.ch_type in ("daily_km", "weekly_km", "monthly_km", "race"):
        return (part.current_value or 0) >= (ch.goal_value or 0) > 0
    return False


async def pause_challenge(challenge_id: int, until: datetime) -> bool:
    """Поставить челлендж на паузу до даты (форс-мажор, админ)."""
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
    """Снять паузу, сдвинуть дедлайн на время заморозки."""
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
    """Завершить челлендж вручную (досрочно)."""
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
    """Сколько человек присоединилось к челленджу."""
    async with async_session() as session:
        res = await session.execute(
            select(func.count(ChallengeParticipant.id)).where(
                ChallengeParticipant.challenge_id == challenge_id
            )
        )
        return res.scalar() or 0