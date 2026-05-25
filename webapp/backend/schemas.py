"""webapp/backend/schemas.py — схемы ответов API."""

from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


# ─── Пользователь ────────────────────────────────────────────

class UserProfile(BaseModel):
    tg_id:        int
    username:     str | None
    full_name:    str | None
    school_nick:  str
    xp:           int
    level:        int
    season_xp:    int
    streak:       int
    best_km:      float | None  # личный рекорд
    xp_in_level:  int           # XP накоплено в этом уровне
    xp_to_next:   int           # XP нужно для следующего уровня (порог)

    class Config:
        from_attributes = True


# ─── Челленджи ───────────────────────────────────────────────

class ChallengeParticipantOut(BaseModel):
    user_id:       int
    username:      str | None
    school_nick:   str
    penalty:       str | None
    current_runs:  int
    current_value: float
    result:          str | None = None
    close_requested: bool = False
    pause_requested: bool = False

    class Config:
        from_attributes = True


class ChallengeOut(BaseModel):
    id:                  int
    title:               str
    ch_type:             str
    min_per_run:         float
    min_minutes_per_run: int
    goal_runs:           int
    goal_value:          float
    goal_time:           int | None
    current_value:       float
    current_runs:        int
    penalty:             str | None
    is_active:           bool
    started_at:          datetime | None
    deadline:            datetime | None
    author_username:     str | None
    author_nick:         str
    is_owner:            bool = False
    is_participant:      bool = False
    days_left:           int | None = None
    is_paused:           bool = False        # заморожен прямо сейчас
    close_requested:     bool = False        # автор попросил закрыть
    pause_requested:     bool = False        # автор попросил паузу
    result:              str | None = None   # completed / failed / closed
    my_current_value:    float = 0.0         # прогресс текущего юзера (участника)
    my_current_runs:     int   = 0
    viewer_id:           int | None = None    # tg_id смотрящего
    participants:        list[ChallengeParticipantOut] = []

    class Config:
        from_attributes = True


class JoinChallengeRequest(BaseModel):
    penalty: str | None = None


# ─── Отчёты ──────────────────────────────────────────────────

class ReportOut(BaseModel):
    id:          int
    user_tg_id:  int
    username:    str | None
    school_nick: str
    km:          float
    is_approved: bool
    is_rejected: bool
    created_at:  datetime

    class Config:
        from_attributes = True


# ─── Мероприятия ─────────────────────────────────────────────

class EventParticipantOut(BaseModel):
    tg_id:       int
    username:    str | None
    school_nick: str
    status:      str  # "going" / "not_going"

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id:              int
    title:           str
    description:     str | None
    location:        str | None
    event_date:      datetime | None
    distance_km:     float | None
    xp_bonus:        int
    xp_multiplier:   float
    is_active:       bool
    is_pending:      bool
    going_count:     int = 0
    not_going_count: int = 0
    user_status:     str | None = None  # "going" / "not_going" / None
    created_by:      int | None = None
    created_by_nick: str | None = None
    participants:    list[EventParticipantOut] = []

    class Config:
        from_attributes = True


class EventTemplateOut(BaseModel):
    id:            int
    name:          str
    description:   str | None
    location:      str | None
    distance_km:   float | None
    xp_bonus:      int
    xp_multiplier: float
    is_external:   bool

    class Config:
        from_attributes = True


class CreateEventRequest(BaseModel):
    title:         str
    description:   str | None = None
    location:      str | None = None
    event_date:    str                # "DD.MM.YYYY HH:MM"
    distance_km:   float | None = None
    xp_bonus:      int = 100
    xp_multiplier: float = 1.5
    template_id:   int | None = None  # если создаём из шаблона


class RejectEventRequest(BaseModel):
    reason: str = ""


# ─── Турниры ─────────────────────────────────────────────────

class TournamentParticipantOut(BaseModel):
    position:    int
    user_tg_id:  int
    username:    str | None
    school_nick: str
    score:       float

    class Config:
        from_attributes = True


class TournamentOut(BaseModel):
    id:              int
    title:           str
    tournament_type: str
    start_date:      datetime
    end_date:        datetime
    is_active:       bool
    leaderboard:     list[TournamentParticipantOut] = []
    user_joined:     bool = False

    class Config:
        from_attributes = True


# ─── Общее ───────────────────────────────────────────────────

class OkResponse(BaseModel):
    ok:     bool
    reason: str = ""