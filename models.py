from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    ForeignKey, DateTime, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    xp = Column(Integer, default=0)
    streak = Column(Integer, default=0)          # Кол-во успешных недель подряд
    last_week_closed = Column(DateTime, nullable=True)  # Когда последний раз закрыли неделю

    challenges = relationship("Challenge", back_populates="user", lazy="selectin")
    event_participations = relationship("EventParticipant", back_populates="user", lazy="selectin")


class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.tg_id"), nullable=False)
    title = Column(String, nullable=False)

    # "contract" — бессрочный еженедельный, "goal" — разовый с дедлайном
    ch_type = Column(String, nullable=False)

    min_per_run = Column(Float, default=0.0)   # Минимальная дистанция за 1 тренировку
    goal_runs = Column(Integer, default=0)      # Сколько раз в неделю (для contract)
    goal_value = Column(Float, default=0.0)    # Суммарно км (для goal)

    current_value = Column(Float, default=0.0)  # Накоплено км за текущую неделю (contract) / всего (goal)
    current_runs = Column(Integer, default=0)   # Тренировок за текущую неделю

    penalty = Column(Text, nullable=True)       # Цена слова
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    deadline = Column(DateTime, nullable=True)  # Для goal-типа

    user = relationship("User", back_populates="challenges")


class Report(Base):
    """Каждый отчёт (#отчет N) — отдельная запись. Связывает сообщение с атлетом."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, unique=True, nullable=False)  # ID сообщения в чате
    chat_id = Column(Integer, nullable=False)
    user_tg_id = Column(Integer, ForeignKey("users.tg_id"), nullable=False)
    km = Column(Float, nullable=False)
    is_approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    votes = relationship("Vote", back_populates="report", lazy="selectin")


class Vote(Base):
    """Голос за отчёт. UniqueConstraint гарантирует 1 голос с человека на уровне БД."""
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    voter_tg_id = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("report_id", "voter_tg_id", name="uq_vote_per_report"),
    )

    report = relationship("Report", back_populates="votes")


class Event(Base):
    """Мероприятие клуба: забег, Long Run и т.д."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    event_date = Column(DateTime, nullable=False)
    distance_km = Column(Float, nullable=True)
    created_by = Column(Integer, nullable=False)    # tg_id создателя (админа)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    participants = relationship("EventParticipant", back_populates="event", lazy="selectin")


class EventParticipant(Base):
    """M2M: пользователь ↔ мероприятие."""
    __tablename__ = "event_participants"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    user_tg_id = Column(Integer, ForeignKey("users.tg_id"), nullable=False)
    registered_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("event_id", "user_tg_id", name="uq_event_participant"),
    )

    event = relationship("Event", back_populates="participants")
    user = relationship("User", back_populates="event_participations")


class Tournament(Base):
    """Квартальный турнир. Победитель — по XP за период."""
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)