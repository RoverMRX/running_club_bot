"""
models.py — схема базы данных IT БЕГОТНЯ 21.

Таблицы:
  User                  — атлет
  Moderator             — модераторы (могут апрувить отчёты)
  Challenge             — личный челлендж
  ChallengeParticipant  — присоединение к чужому челленджу
  Report                — отчёт о тренировке
  Vote                  — голос за отчёт (P2P)
  PersonalRecord        — личный рекорд дистанции
  EventTemplate         — шаблон мероприятия
  Event                 — конкретное мероприятие
  EventParticipant      — участие в мероприятии
  WeeklyTournament      — недельный турнир
  TournamentParticipant — участник турнира
  Team                  — команда
  TeamMember            — участник команды
  Tournament            — квартальный турнир
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime,
    Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ────────────────────────────────────────────────
# Пользователи и права
# ────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id               = Column(Integer,    primary_key=True)
    tg_id            = Column(BigInteger, unique=True, nullable=False)
    username         = Column(String,     nullable=True)
    full_name        = Column(String,     nullable=True)

    xp               = Column(Integer, default=0)
    season_xp        = Column(Integer, default=0)     # Сбрасывается каждый квартал
    streak           = Column(Integer, default=0)     # Недели подряд без пропусков
    last_week_closed = Column(DateTime, nullable=True)

    challenges               = relationship("Challenge",              back_populates="owner",        lazy="selectin")
    challenge_participations = relationship("ChallengeParticipant",  back_populates="user",         lazy="selectin")
    reports                  = relationship("Report",                 back_populates="user",         lazy="selectin")
    personal_record          = relationship("PersonalRecord",         back_populates="user",         uselist=False, lazy="selectin")
    event_participations     = relationship("EventParticipant",       back_populates="user",         lazy="selectin")
    tournament_participations = relationship("TournamentParticipant", back_populates="user",         lazy="selectin")
    team_memberships         = relationship("TeamMember",             back_populates="user",         lazy="selectin")


class Moderator(Base):
    """
    Модераторы могут апрувить/отклонять отчёты.
    Администраторы хранятся в ADMIN_IDS в .env — в эту таблицу не вносятся.
    """
    __tablename__ = "moderators"

    id        = Column(Integer,    primary_key=True)
    tg_id     = Column(BigInteger, unique=True, nullable=False)
    username  = Column(String,     nullable=True)
    full_name = Column(String,     nullable=True)
    added_by  = Column(BigInteger, nullable=False)   # tg_id того, кто добавил
    added_at  = Column(DateTime,   default=datetime.now)


# ────────────────────────────────────────────────
# Челленджи
# ────────────────────────────────────────────────

class Challenge(Base):
    """
    Личный челлендж атлета.
    ch_type:
      "contract" — бессрочный еженедельный (X пробежек по Y км)
      "goal"     — разовая цель (суммарно N км до дедлайна)
    """
    __tablename__ = "challenges"

    id            = Column(Integer,    primary_key=True)
    user_id       = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False)
    title         = Column(String,     nullable=False)
    ch_type       = Column(String,     nullable=False)   # "contract" | "goal"
    is_public     = Column(Boolean,    default=True)     # Можно ли присоединиться

    min_per_run   = Column(Float,   default=0.0)         # Мин. км за 1 тренировку
    goal_runs     = Column(Integer, default=0)           # Раз в неделю (contract)
    goal_value    = Column(Float,   default=0.0)         # Суммарно км (goal)

    current_value = Column(Float,   default=0.0)         # Накоплено км за неделю / всего
    current_runs  = Column(Integer, default=0)           # Тренировок за текущую неделю

    penalty       = Column(Text,    nullable=True)       # Цена слова
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.now)
    deadline      = Column(DateTime, nullable=True)      # Для goal-типа

    owner        = relationship("User",                  back_populates="challenges")
    participants = relationship("ChallengeParticipant",  back_populates="challenge", lazy="selectin")


class ChallengeParticipant(Base):
    """Участник чужого публичного челленджа. Прогресс считается отдельно."""
    __tablename__ = "challenge_participants"

    id            = Column(Integer,    primary_key=True)
    challenge_id  = Column(Integer,    ForeignKey("challenges.id"),  nullable=False)
    user_id       = Column(BigInteger, ForeignKey("users.tg_id"),    nullable=False)
    joined_at     = Column(DateTime,   default=datetime.now)

    current_value = Column(Float,   default=0.0)
    current_runs  = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("challenge_id", "user_id", name="uq_challenge_participant"),
    )

    challenge = relationship("Challenge", back_populates="participants")
    user      = relationship("User",      back_populates="challenge_participations")


# ────────────────────────────────────────────────
# Отчёты и голосование
# ────────────────────────────────────────────────

class Report(Base):
    """
    Отчёт о тренировке или участии в мероприятии.
    report_type:
      "training" — обычная тренировка
      "event"    — участие в мероприятии (event_id обязателен)
    """
    __tablename__ = "reports"

    id           = Column(Integer,    primary_key=True)
    message_id   = Column(Integer,    unique=True, nullable=False)  # ID сообщения в чате
    chat_id      = Column(BigInteger, nullable=False)
    thread_id    = Column(Integer,    nullable=True)                # ID топика (если есть)
    user_tg_id   = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False)

    report_type  = Column(String,  default="training")             # "training" | "event"
    event_id     = Column(Integer, ForeignKey("events.id"), nullable=True)

    km           = Column(Float,   nullable=False)
    duration_min = Column(Integer, nullable=True)                   # Минуты тренировки
    is_approved  = Column(Boolean, default=False)
    is_rejected  = Column(Boolean, default=False)
    rejected_by  = Column(BigInteger, nullable=True)               # tg_id кто отклонил
    created_at   = Column(DateTime,   default=datetime.now)

    user  = relationship("User",  back_populates="reports")
    votes = relationship("Vote",  back_populates="report",  lazy="selectin")
    event = relationship("Event", back_populates="reports", foreign_keys=[event_id])


class Vote(Base):
    """Голос за отчёт. UniqueConstraint — 1 голос с человека на уровне БД."""
    __tablename__ = "votes"

    id          = Column(Integer,    primary_key=True)
    report_id   = Column(Integer,    ForeignKey("reports.id"), nullable=False)
    voter_tg_id = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("report_id", "voter_tg_id", name="uq_vote_per_report"),
    )

    report = relationship("Report", back_populates="votes")


# ────────────────────────────────────────────────
# Личные рекорды
# ────────────────────────────────────────────────

class PersonalRecord(Base):
    """Лучшая дистанция за одну тренировку. Одна запись на пользователя."""
    __tablename__ = "personal_records"

    id         = Column(Integer,    primary_key=True)
    user_tg_id = Column(BigInteger, ForeignKey("users.tg_id"), unique=True, nullable=False)
    best_km    = Column(Float,   default=0.0)
    set_at     = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="personal_record")


# ────────────────────────────────────────────────
# Мероприятия
# ────────────────────────────────────────────────

class EventTemplate(Base):
    """
    Шаблон мероприятия. Управляется через админ-меню.
    is_external = True  → идём как гости (5 вёрст, городской забег)
    is_external = False → мероприятие клуба (Long Run, совместная тренировка)
    """
    __tablename__ = "event_templates"

    id                = Column(Integer,    primary_key=True)
    name              = Column(String,     nullable=False)
    description       = Column(Text,       nullable=True)
    rules             = Column(Text,       nullable=True)  # Правила участия
    registration_info = Column(Text,       nullable=True)  # Инфо о регистрации
    is_external       = Column(Boolean,    default=False)
    xp_bonus          = Column(Integer,    default=100)    # Фиксированный бонус XP
    xp_multiplier     = Column(Float,      default=1.5)    # Множитель XP за км
    is_active         = Column(Boolean,    default=True)
    created_by        = Column(BigInteger, nullable=False)
    created_at        = Column(DateTime,   default=datetime.now)

    events = relationship("Event", back_populates="template", lazy="selectin")


class Event(Base):
    """Конкретное мероприятие (создаётся из шаблона или с нуля)."""
    __tablename__ = "events"

    id            = Column(Integer,    primary_key=True)
    template_id   = Column(Integer,    ForeignKey("event_templates.id"), nullable=True)
    title         = Column(String,     nullable=False)
    description   = Column(Text,       nullable=True)
    location      = Column(String,     nullable=True)
    event_date    = Column(DateTime,   nullable=False)
    distance_km   = Column(Float,      nullable=True)
    created_by    = Column(BigInteger, nullable=False)
    is_active     = Column(Boolean,    default=True)
    created_at    = Column(DateTime,   default=datetime.now)

    # XP настройки (наследуются из шаблона, можно переопределить)
    xp_bonus      = Column(Integer, default=100)
    xp_multiplier = Column(Float,   default=1.5)

    template     = relationship("EventTemplate",    back_populates="events")
    participants = relationship("EventParticipant", back_populates="event",  lazy="selectin")
    reports      = relationship("Report",           back_populates="event",
                                foreign_keys="Report.event_id",              lazy="selectin")


class EventParticipant(Base):
    """
    Участие пользователя в мероприятии.
    status: "going" | "not_going"
    """
    __tablename__ = "event_participants"

    id            = Column(Integer,    primary_key=True)
    event_id      = Column(Integer,    ForeignKey("events.id"),    nullable=False)
    user_tg_id    = Column(BigInteger, ForeignKey("users.tg_id"),  nullable=False)
    status        = Column(String,     default="going")            # "going" | "not_going"
    registered_at = Column(DateTime,   default=datetime.now)

    __table_args__ = (
        UniqueConstraint("event_id", "user_tg_id", name="uq_event_participant"),
    )

    event = relationship("Event", back_populates="participants")
    user  = relationship("User",  back_populates="event_participations")


# ────────────────────────────────────────────────
# Турниры
# ────────────────────────────────────────────────

class WeeklyTournament(Base):
    """
    Недельный турнир между участниками.
    tournament_type:
      "km"      — кто больше км пробежит
      "minutes" — кто больше минут потратит
      "days"    — кто больше дней подряд бегал
      "team_km" — командный: суммарные км команды
    """
    __tablename__ = "weekly_tournaments"

    id               = Column(Integer,    primary_key=True)
    title            = Column(String,     nullable=False)
    tournament_type  = Column(String,     nullable=False)
    start_date       = Column(DateTime,   nullable=False)
    end_date         = Column(DateTime,   nullable=False)
    is_active        = Column(Boolean,    default=True)
    winner_tg_id     = Column(BigInteger, nullable=True)  # Заполняется после финиша
    created_by       = Column(BigInteger, nullable=False)
    created_at       = Column(DateTime,   default=datetime.now)

    participants = relationship("TournamentParticipant", back_populates="tournament", lazy="selectin")


class TournamentParticipant(Base):
    """Участник недельного турнира и его результат."""
    __tablename__ = "tournament_participants"

    id            = Column(Integer,    primary_key=True)
    tournament_id = Column(Integer,    ForeignKey("weekly_tournaments.id"), nullable=False)
    user_tg_id    = Column(BigInteger, ForeignKey("users.tg_id"),           nullable=False)
    score         = Column(Float,  default=0.0)   # км / минуты / дни
    joined_at     = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("tournament_id", "user_tg_id", name="uq_tournament_participant"),
    )

    tournament = relationship("WeeklyTournament",     back_populates="participants")
    user       = relationship("User",                 back_populates="tournament_participations")


# ────────────────────────────────────────────────
# Команды
# ────────────────────────────────────────────────

class Team(Base):
    """Команда для командных турниров."""
    __tablename__ = "teams"

    id         = Column(Integer,    primary_key=True)
    name       = Column(String,     nullable=False)
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime,   default=datetime.now)
    is_active  = Column(Boolean,    default=True)

    members = relationship("TeamMember", back_populates="team", lazy="selectin")


class TeamMember(Base):
    """Участник команды."""
    __tablename__ = "team_members"

    id         = Column(Integer,    primary_key=True)
    team_id    = Column(Integer,    ForeignKey("teams.id"),     nullable=False)
    user_tg_id = Column(BigInteger, ForeignKey("users.tg_id"),  nullable=False)
    joined_at  = Column(DateTime,   default=datetime.now)

    __table_args__ = (
        UniqueConstraint("team_id", "user_tg_id", name="uq_team_member"),
    )

    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_memberships")


# ────────────────────────────────────────────────
# Квартальный турнир
# ────────────────────────────────────────────────

class Tournament(Base):
    __tablename__ = "tournaments"

    id         = Column(Integer,  primary_key=True)
    name       = Column(String,   nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date   = Column(DateTime, nullable=False)
    is_active  = Column(Boolean,  default=True)