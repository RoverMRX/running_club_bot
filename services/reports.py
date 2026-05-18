"""
services/reports.py — бизнес-логика отчётов и P2P голосования.

Публичный API:
  create_report(...)                               → Report
  detect_matching_challenges(user_id, km, minutes) → list[Challenge]
  link_challenges(report_id, challenge_ids)        → None
  add_vote(report_id, voter_id, negative)          → dict
  approve_report(report_id)                        → dict
  reject_report(report_id, rejected_by)            → bool

Голосование:
  - VOTES_REQUIRED положительных голосов → автоодобрение
  - VOTES_REQUIRED отрицательных голосов → автоотклонение
  - Один человек — один голос (UniqueConstraint в Vote)
  - Автор не может голосовать за свой отчёт
"""

import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

import config
from database import async_session
from models import (
    Report, ReportChallenge, Vote,
    User, Challenge, ChallengeParticipant,
    PersonalRecord, Event,
)
from services.challenges import update_on_report, is_run_counts

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Создание отчёта
# ──────────────────────────────────────────────────────────────────────────────

async def create_report(
    user_tg_id: int,
    km: float,
    message_id: int,
    chat_id: int,
    thread_id: int | None = None,
    duration_min: int | None = None,
    event_id: int | None = None,
    tournament_id: int | None = None,
) -> Report:
    """
    Создаёт запись отчёта в БД.

    Привязка к челленджам делается отдельно через link_challenges()
    после того, как пользователь выберет их через кнопки.

    report_type = "event" если передан event_id, иначе "training".
    """
    report_type = "event" if event_id else "training"

    async with async_session() as session:
        async with session.begin():
            report = Report(
                message_id=message_id,
                chat_id=chat_id,
                thread_id=thread_id,
                user_tg_id=user_tg_id,
                km=km,
                duration_min=duration_min,
                report_type=report_type,
                event_id=event_id,
                tournament_id=tournament_id,
                is_approved=False,
                is_rejected=False,
            )
            session.add(report)
            await session.flush()
            report_id = report.id

    async with async_session() as session:
        res = await session.execute(select(Report).where(Report.id == report_id))
        return res.scalar_one()


# ──────────────────────────────────────────────────────────────────────────────
# Определение подходящих челленджей
# ──────────────────────────────────────────────────────────────────────────────

async def detect_matching_challenges(
    user_id: int,
    km: float,
    minutes: int | None = None,
) -> list[Challenge]:
    """
    Возвращает активные челленджи пользователя (свои + присоединённые),
    которым подходит данная пробежка по условиям is_run_counts.
    """
    now = datetime.now()
    matching: list[Challenge] = []

    async with async_session() as session:
        own_res = await session.execute(
            select(Challenge).where(
                Challenge.user_id == user_id,
                Challenge.is_active == True,
            )
        )
        own_challenges = list(own_res.scalars().all())

        joined_res = await session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.user_id == user_id,
            )
        )
        joined_challenges = [
            p.challenge for p in joined_res.scalars().all()
            if p.challenge and p.challenge.is_active
        ]

        for ch in own_challenges + joined_challenges:
            if ch.pause_until and ch.pause_until > now:
                continue
            if is_run_counts(ch, km, minutes):
                matching.append(ch)

    return matching


# ──────────────────────────────────────────────────────────────────────────────
# Привязка отчёта к нескольким челленджам
# ──────────────────────────────────────────────────────────────────────────────

async def link_challenges(report_id: int, challenge_ids: list[int]) -> None:
    """
    Создаёт записи в report_challenges для каждого выбранного челленджа.
    Дубликаты игнорируются (UniqueConstraint).
    """
    if not challenge_ids:
        return

    async with async_session() as session:
        async with session.begin():
            for ch_id in challenge_ids:
                try:
                    session.add(ReportChallenge(
                        report_id=report_id,
                        challenge_id=ch_id,
                    ))
                    await session.flush()
                except IntegrityError:
                    await session.rollback()
                    log.debug("link_challenges: дубликат report=%s ch=%s", report_id, ch_id)


# ──────────────────────────────────────────────────────────────────────────────
# Голосование
# ──────────────────────────────────────────────────────────────────────────────

async def add_vote(
    report_id: int,
    voter_id: int,
    negative: bool = False,
) -> dict:
    """
    Добавляет голос за или против отчёта.

    negative=False → «Засчитать»
    negative=True  → «Фейк»

    Returns:
        {
          'ok': bool,
          'reason': str,
          'pos_votes': int,
          'neg_votes': int,
          'approved': bool,
          'rejected': bool,
        }
    """
    async with async_session() as session:
        async with session.begin():
            r_res = await session.execute(select(Report).where(Report.id == report_id))
            report = r_res.scalar_one_or_none()

            if not report:
                return _vote_err('Отчёт не найден.')
            if report.is_approved or report.is_rejected:
                return _vote_err('Отчёт уже закрыт.')
            if report.user_tg_id == voter_id:
                return _vote_err('Свой отчёт нельзя оценивать!')

            try:
                session.add(Vote(
                    report_id=report_id,
                    voter_tg_id=voter_id,
                    is_negative=negative,
                ))
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return _vote_err('Ты уже голосовал!')

            pos_res = await session.execute(
                select(func.count(Vote.id)).where(
                    Vote.report_id == report_id,
                    Vote.is_negative == False,
                )
            )
            neg_res = await session.execute(
                select(func.count(Vote.id)).where(
                    Vote.report_id == report_id,
                    Vote.is_negative == True,
                )
            )
            pos_votes = pos_res.scalar() or 0
            neg_votes = neg_res.scalar() or 0

            approved = pos_votes >= config.VOTES_REQUIRED
            rejected = neg_votes >= config.VOTES_REQUIRED

            if approved:
                report.is_approved = True
                await session.flush()
            elif rejected:
                report.is_rejected = True
                report.rejected_by = voter_id
                await session.flush()

    return {
        'ok': True,
        'reason': '',
        'pos_votes': pos_votes,
        'neg_votes': neg_votes,
        'approved': approved,
        'rejected': rejected,
    }


def _vote_err(reason: str) -> dict:
    return {
        'ok': False, 'reason': reason,
        'pos_votes': 0, 'neg_votes': 0,
        'approved': False, 'rejected': False,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Одобрение отчёта
# ──────────────────────────────────────────────────────────────────────────────

async def approve_report(report_id: int) -> dict:
    """
    Одобряет отчёт: начисляет XP, обновляет все привязанные челленджи,
    проверяет PR.

    Идемпотентен: повторный вызов вернёт {'ok': True, 'reason': 'already'}.

    Returns:
        {
          'ok': bool,
          'reason': str,
          'user_tg_id': int,
          'km': float,
          'xp': int,
          'is_pr': bool,
          'updated': list[str],
          'completed': list[str],
        }
    """
    async with async_session() as session:
        async with session.begin():
            r_res = await session.execute(select(Report).where(Report.id == report_id))
            report = r_res.scalar_one_or_none()

            if not report:
                return _ap_err('Отчёт не найден.')
            if report.is_rejected:
                return _ap_err('Отчёт отклонён.')
            if report.is_approved:
                return {
                    'ok': True, 'reason': 'already',
                    'user_tg_id': report.user_tg_id, 'km': report.km,
                    'xp': 0, 'is_pr': False, 'updated': [], 'completed': [],
                }

            # Бонусы мероприятия
            event_bonus = 0
            event_multiplier = 1.0
            if report.event_id:
                ev_res = await session.execute(
                    select(Event).where(Event.id == report.event_id)
                )
                event = ev_res.scalar_one_or_none()
                if event:
                    event_bonus = event.xp_bonus or 0
                    event_multiplier = event.xp_multiplier or 1.0

            km_xp = int(report.km * config.XP_PER_KM * event_multiplier)
            total_xp = km_xp + event_bonus

            u_res = await session.execute(
                select(User).where(User.tg_id == report.user_tg_id)
            )
            user = u_res.scalar_one_or_none()
            if user:
                user.xp += total_xp
                user.season_xp += total_xp
                user.level = user.xp // 100

            # PR
            pr_res = await session.execute(
                select(PersonalRecord).where(PersonalRecord.user_tg_id == report.user_tg_id)
            )
            pr = pr_res.scalar_one_or_none()
            is_pr = False

            if not pr:
                session.add(PersonalRecord(
                    user_tg_id=report.user_tg_id,
                    best_km=report.km,
                    set_at=datetime.now(),
                ))
                is_pr = True
            elif report.km > pr.best_km:
                pr.best_km = report.km
                pr.set_at = datetime.now()
                is_pr = True

            if is_pr and user:
                user.xp += config.XP_PR_BONUS
                user.season_xp += config.XP_PR_BONUS
                total_xp += config.XP_PR_BONUS

            report.is_approved = True
            user_tg_id = report.user_tg_id
            km = report.km
            duration_min = report.duration_min
            await session.flush()

    challenge_result = await update_on_report(
        user_id=user_tg_id,
        km=km,
        minutes=duration_min,
    )

    return {
        'ok': True,
        'reason': '',
        'user_tg_id': user_tg_id,
        'km': km,
        'xp': total_xp,
        'is_pr': is_pr,
        'updated': challenge_result['updated'],
        'completed': challenge_result['completed'],
    }


def _ap_err(reason: str) -> dict:
    return {
        'ok': False, 'reason': reason,
        'user_tg_id': 0, 'km': 0,
        'xp': 0, 'is_pr': False, 'updated': [], 'completed': [],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Отклонение отчёта
# ──────────────────────────────────────────────────────────────────────────────

async def reject_report(report_id: int, rejected_by: int) -> bool:
    """
    Отклоняет отчёт вручную (только админ/модер — проверка в хендлере).

    Returns True если успешно, False если отчёт не найден или уже закрыт.
    """
    async with async_session() as session:
        async with session.begin():
            r_res = await session.execute(select(Report).where(Report.id == report_id))
            report = r_res.scalar_one_or_none()

            if not report or report.is_approved or report.is_rejected:
                return False

            report.is_rejected = True
            report.rejected_by = rejected_by
            return True