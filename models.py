"""
models.py — схема базы данных IT БЕГОТНЯ 21.

Хранение данных:
  - tg_id: НЕ шифруем (primary key, нужен для Telegram API)
  - school_nick: НЕ шифруем (отображаем в таблице лидеров: @school_nick)
  - username: НЕ шифруем (для упоминания @username)
  - full_name: НЕ шифруем (для отображения в профиле)
  - xp, level, streak: НЕ шифруем (игровые данные)
"""

from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime,
    Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ────────────────────────────────────────────
# Пользователи
# ────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id               = Column(Integer,    primary_key=True)
    tg_id            = Column(BigInteger, unique=True, nullable=False)  # Telegram chat ID
    username         = Column(String,     nullable=True)                 # @username из Telegram
    full_name        = Column(String,     nullable=True)                 # Имя и фамилия
    school_nick      = Column(String,     unique=True, nullable=False)   # @school_nick из школы 21

    xp               = Column(Integer, default=0)         # Общий XP (не сбрасывается)
    level            = Column(Integer, default=0)         # Level = xp // 100
    season_xp        = Column(Integer, default=0)         # Квартальный XP (сбрасывается каждый квартал)
    streak           = Column(Integer, default=0)         # Недели подряд без пропусков
    last_week_closed = Column(DateTime, nullable=True)    # Когда последний раз закрыли неделю

    created_at       = Column(DateTime, default=datetime.now)
    updated_at       = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Связи
    challenges               = relationship("Challenge",              back_populates="owner",        lazy="selectin")
    challenge_participations = relationship("ChallengeParticipant",  back_populates="user",         lazy="selectin")
    reports                  = relationship("Report",                 back_populates="user",         lazy="selectin")
    personal_record          = relationship("PersonalRecord",         back_populates="user",         uselist=False, lazy="selectin")
    event_participations     = relationship("EventParticipant",       back_populates="user",         lazy="selectin")
    tournament_participations = relationship("TournamentParticipant", back_populates="user",         lazy="selectin")
    team_memberships         = relationship("TeamMember",             back_populates="user",         lazy="selectin")


class Moderator(Base):
    """Модераторы могут апрувить/отклонять отчёты."""
    __tablename__ = "moderators"

    id        = Column(Integer,    primary_key=True)
    tg_id     = Column(BigInteger, unique=True, nullable=False)
    username  = Column(String,     nullable=True)
    added_by  = Column(BigInteger, nullable=False)   # tg_id админа, который добавил
    added_at  = Column(DateTime,   default=datetime.now)


# ────────────────────────────────────────────
# Челленджи
# ────────────────────────────────────────────

class Challenge(Base):
    """
    Челлендж пользователя.
    ch_type: "weekly_runs" | "daily_km" | "weekly_km" | "monthly_km" | "race" | "open"
    """
    __tablename__ = "challenges"

    id            = Column(Integer,    primary_key=True)
    user_id       = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False)
    title         = Column(String,     nullable=False)
    ch_type       = Column(String,     nullable=False)   # Тип челленджа

    # Параметры в зависимости от типа
    min_per_run        = Column(Float,   default=0.0)    # Мин. км за 1 тренировку (0 = не требуется)
    min_minutes_per_run = Column(Integer, default=0)     # Мин. минут за 1 тренировку (0 = не требуется)
    goal_runs          = Column(Integer, default=0)      # Раз в неделю (weekly_runs)
    goal_value         = Column(Float,   default=0.0)    # Суммарно км (weekly_km, monthly_km, race)
    goal_time          = Column(Integer, nullable=True)  # Время в минутах — лимит (race)

    # Текущий прогресс
    current_value = Column(Float,   default=0.0)
    current_runs  = Column(Integer, default=0)
    current_time  = Column(Integer, default=0)           # Минуты

    # Параметры
    penalty       = Column(Text,    nullable=True)       # "Цена слова"
    is_public     = Column(Boolean, default=True)        # Можно ли присоединиться
    is_active     = Column(Boolean, default=True)

    # Сроки
    started_at    = Column(DateTime, nullable=True)
    deadline      = Column(DateTime, nullable=True)      # Null = открытый челлендж
    pause_until   = Column(DateTime, nullable=True)      # На паузе до даты (админ)

    created_at    = Column(DateTime, default=datetime.now)

    owner        = relationship("User",                  back_populates="challenges")
    participants = relationship("ChallengeParticipant",  back_populates="challenge", lazy="selectin")


class ChallengeParticipant(Base):
    """Участник чужого челленджа."""
    __tablename__ = "challenge_participants"

    id            = Column(Integer,    primary_key=True)
    challenge_id  = Column(Integer,    ForeignKey("challenges.id"),  nullable=False)
    user_id       = Column(BigInteger, ForeignKey("users.tg_id"),    nullable=False)
    joined_at     = Column(DateTime,   default=datetime.now)

    current_value = Column(Float,   default=0.0)
    current_runs  = Column(Integer, default=0)
    current_time  = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("challenge_id", "user_id", name="uq_challenge_participant"),
    )

    challenge = relationship("Challenge", back_populates="participants")
    user      = relationship("User",      back_populates="challenge_participations")


# ────────────────────────────────────────────
# Отчёты и голосование
# ────────────────────────────────────────────

class Report(Base):
    """Отчёт о тренировке."""
    __tablename__ = "reports"

    id           = Column(Integer,    primary_key=True)
    message_id   = Column(Integer,    unique=True, nullable=False)
    chat_id      = Column(BigInteger, nullable=False)
    thread_id    = Column(Integer,    nullable=True)     # ID топика

    user_tg_id   = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False)
    km           = Column(Float,   nullable=False)
    duration_min = Column(Integer, nullable=True)

    report_type  = Column(String, default="training")    # "training" | "event"
    event_id     = Column(Integer, ForeignKey("events.id"), nullable=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=True)
    tournament_id = Column(Integer, ForeignKey("weekly_tournaments.id"), nullable=True)

    is_approved  = Column(Boolean, default=False)
    is_rejected  = Column(Boolean, default=False)
    rejected_by  = Column(BigInteger, nullable=True)

    created_at   = Column(DateTime, default=datetime.now)

    user      = relationship("User",  back_populates="reports")
    votes     = relationship("Vote",  back_populates="report",  lazy="selectin")
    event     = relationship("Event", back_populates="reports", foreign_keys=[event_id])
    challenge = relationship("Challenge")
    tournament = relationship("WeeklyTournament")


class Vote(Base):
    """Голос за отчёт."""
    __tablename__ = "votes"

    id          = Column(Integer,    primary_key=True)
    report_id   = Column(Integer,    ForeignKey("reports.id"), nullable=False)
    voter_tg_id = Column(BigInteger, nullable=False)
    voted_at    = Column(DateTime,   default=datetime.now)

    __table_args__ = (
        UniqueConstraint("report_id", "voter_tg_id", name="uq_vote_per_report"),
    )

    report = relationship("Report", back_populates="votes")


# ────────────────────────────────────────────
# Личные рекорды
# ────────────────────────────────────────────

class PersonalRecord(Base):
    """Лучшая дистанция за одну тренировку."""
    __tablename__ = "personal_records"

    id         = Column(Integer,    primary_key=True)
    user_tg_id = Column(BigInteger, ForeignKey("users.tg_id"), unique=True, nullable=False)
    best_km    = Column(Float, default=0.0)
    set_at     = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="personal_record")


# ────────────────────────────────────────────
# Мероприятия
# ────────────────────────────────────────────

class EventTemplate(Base):
    """Шаблон мероприятия."""
    __tablename__ = "event_templates"

    id                = Column(Integer,    primary_key=True)
    name              = Column(String,     nullable=False)
    description       = Column(Text,       nullable=True)
    rules             = Column(Text,       nullable=True)
    registration_info = Column(Text,       nullable=True)
    is_external       = Column(Boolean,    default=False)   # True = мы гости
    xp_bonus          = Column(Integer,    default=100)
    xp_multiplier     = Column(Float,      default=1.5)
    is_active         = Column(Boolean,    default=True)
    created_by        = Column(BigInteger, nullable=False)
    created_at        = Column(DateTime,   default=datetime.now)

    events = relationship("Event", back_populates="template", lazy="selectin")


class Event(Base):
    """Конкретное мероприятие."""
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

    xp_bonus      = Column(Integer, default=100)
    xp_multiplier = Column(Float,   default=1.5)

    announce_msg_id = Column(Integer, nullable=True)   # В основной группе
    repost_msg_id   = Column(Integer, nullable=True)   # В школьной группе

    template     = relationship("EventTemplate",    back_populates="events")
    participants = relationship("EventParticipant", back_populates="event",   lazy="selectin")
    reports      = relationship("Report",           back_populates="event",
                                foreign_keys="Report.event_id",              lazy="selectin")


class EventParticipant(Base):
    """Участие в мероприятии."""
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


# ────────────────────────────────────────────
# Турниры
# ────────────────────────────────────────────

class WeeklyTournament(Base):
    """Недельный турнир."""
    __tablename__ = "weekly_tournaments"

    id               = Column(Integer,    primary_key=True)
    title            = Column(String,     nullable=False)
    tournament_type  = Column(String,     nullable=False)  # "km" | "minutes" | "days" | "team_km"
    start_date       = Column(DateTime,   nullable=False)
    end_date         = Column(DateTime,   nullable=False)
    is_active        = Column(Boolean,    default=True)
    winner_tg_id     = Column(BigInteger, nullable=True)
    created_by       = Column(BigInteger, nullable=False)
    created_at       = Column(DateTime,   default=datetime.now)

    participants = relationship("TournamentParticipant", back_populates="tournament", lazy="selectin")


class TournamentParticipant(Base):
    """Участник турнира."""
    __tablename__ = "tournament_participants"

    id            = Column(Integer,    primary_key=True)
    tournament_id = Column(Integer,    ForeignKey("weekly_tournaments.id"), nullable=False)
    user_tg_id    = Column(BigInteger, ForeignKey("users.tg_id"),           nullable=False)
    score         = Column(Float,  default=0.0)
    joined_at     = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("tournament_id", "user_tg_id", name="uq_tournament_participant"),
    )

    tournament = relationship("WeeklyTournament",     back_populates="participants")
    user       = relationship("User",                 back_populates="tournament_participations")


# ────────────────────────────────────────────
# Команды
# ────────────────────────────────────────────

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


# ────────────────────────────────────────────
# Квартальный турнир
# ────────────────────────────────────────────

class Tournament(Base):
    __tablename__ = "tournaments"

    id         = Column(Integer,  primary_key=True)
    name       = Column(String,   nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date   = Column(DateTime, nullable=False)
    is_active  = Column(Boolean,  default=True)