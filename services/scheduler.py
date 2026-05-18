"""
services/scheduler.py — все крон-задачи: дайджест, напоминания, сброс стриков.
"""

from datetime import datetime
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, func

import config
from database import async_session
from models import User, Challenge, WeeklyTournament, TournamentParticipant
from services.digest import send_weekly_digest


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Регистрирует все задачи в планировщике."""
    
    # Каждое воскресенье в 21:00 МСК
    scheduler.add_job(
        send_weekly_digest,
        trigger="cron",
        day_of_week="sun",
        hour=21,
        minute=0,
        args=[bot],
        id="weekly_digest",
        replace_existing=True,
    )
    
    print("   📅 Планировщик: дайджест каждое вс в 21:00 МСК")