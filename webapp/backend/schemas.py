"""webapp/backend/schemas.py — схемы ответов API."""

from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


# ─── Пользователь ────────────────────────────────────────────

class UserProfile(BaseModel):
    tg_id:      int
    username:   str | None
    full_name:  str | None
    school_nick: str
    xp:         int
    level:      int
    season_xp:  int
    streak:     int
    best_km:    float | None  # личный рекорд

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

class EventOut(BaseModel):
    id:           int
    title:        str
    description:  str | None
    location:     str | None
    event_date:   datetime | None
    distance_km:  float | None
    xp_bonus:     int
    xp_multiplier: float
    is_active:    bool
    is_pending:   bool
    going_count:  int = 0
    not_going_count: int = 0
    user_status:  str | None = None  # "going" / "not_going" / None

    class Config:
        from_attributes = True


class CreateEventRequest(BaseModel):
    title:       str
    description: str | None = None
    location:    str | None = None
    event_date:  str        # "DD.MM.YYYY HH:MM"
    distance_km: float | None = None


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