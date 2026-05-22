"""
webapp/backend/notify.py — очередь уведомлений.

Api-контейнер не имеет доступа к прокси бота.
Вместо прямой отправки через aiogram — пишем задачу в таблицу pending_notifications.
Бот забирает их каждые 10 секунд и отправляет сам (у него есть прокси).
"""

import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from models import PendingNotification, Moderator


async def queue_message(
    db: AsyncSession,
    user_tg_id: int,
    text: str,
    kb=None,  # aiogram InlineKeyboardMarkup или None
) -> None:
    """Добавить уведомление в очередь для отправки ботом."""
    kb_json = None
    if kb is not None:
        try:
            kb_json = kb.model_dump_json()
        except Exception:
            kb_json = None

    db.add(PendingNotification(
        user_tg_id=user_tg_id,
        text=text,
        kb_json=kb_json,
    ))
    # Не делаем commit здесь — вызывающий код сам коммитит


async def queue_message_to_admins(
    db: AsyncSession,
    text: str,
    kb=None,
) -> None:
    """Добавить уведомление всем админам и модераторам."""
    from config import ADMIN_IDS

    for admin_id in ADMIN_IDS:
        await queue_message(db, admin_id, text, kb)

    mods_res = await db.execute(select(Moderator))
    for mod in mods_res.scalars().all():
        if mod.tg_id not in ADMIN_IDS:
            await queue_message(db, mod.tg_id, text, kb)