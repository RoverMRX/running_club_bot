"""routers/challenges.py — челленджи."""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from database import get_db
from auth import get_current_user
from schemas import ChallengeOut, ChallengeParticipantOut, JoinChallengeRequest, OkResponse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from models import Challenge, ChallengeParticipant, User

class PauseRequest(BaseModel):
    reason: str = ""


router = APIRouter(prefix="/challenges", tags=["challenges"])

_SPRINT_DAYS = {"daily_km": 1, "weekly_km": 7, "monthly_km": 30}


# ─── helpers ─────────────────────────────────────────────────

def _make_bot():
    """Создать Bot с прокси если задан (api-контейнер не имеет host network)."""
    from config import BOT_TOKEN
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    import os
    proxy_url = os.getenv("PROXY_URL")
    if proxy_url:
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiohttp_socks import ProxyConnector
        session = AiohttpSession(connector=ProxyConnector.from_url(proxy_url))
        return Bot(token=BOT_TOKEN, session=session,
                   default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def _notify_admins(text: str, kb=None, db: AsyncSession = None) -> None:
    """Уведомить всех администраторов через pending_notifications."""
    import json
    from notify import queue_message
    try:
        from config import ADMIN_IDS
        kb_json = kb.model_dump_json() if kb else None
        if db:
            for admin_id in ADMIN_IDS:
                await queue_message(db, admin_id, text, kb_json)
        else:
            from database import async_session as _async_session
            async with _async_session() as _db:
                for admin_id in ADMIN_IDS:
                    await queue_message(_db, admin_id, text, kb_json)
    except Exception as e:
        import logging
        logging.getLogger("challenges").warning(f"Ошибка уведомления админов: {e}")


async def _enrich_challenge(ch: Challenge, db: AsyncSession, viewer_id: int | None = None) -> ChallengeOut:
    author_res = await db.execute(select(User).where(User.tg_id == ch.user_id))
    author = author_res.scalar_one_or_none()

    # Для родительского — список дочерних (участников)
    # Для дочернего — пусто (у него нет своих участников)
    participants = []
    is_participant = False
    my_current_value = 0.0
    my_current_runs  = 0

    if ch.parent_id is None:
        # Это родительский: ищем дочерние
        children_res = await db.execute(
            select(Challenge, User)
            .join(User, User.tg_id == Challenge.user_id)
            .where(Challenge.parent_id == ch.id)
            .order_by(Challenge.created_at)
        )
        for child, u in children_res.all():
            if viewer_id and u.tg_id == viewer_id:
                is_participant = True
                my_current_value = child.current_value or 0.0
                my_current_runs  = child.current_runs  or 0
            participants.append(ChallengeParticipantOut(
                user_id=u.tg_id, username=u.username, school_nick=u.school_nick,
                penalty=child.penalty,
                current_runs=child.current_runs or 0,
                current_value=child.current_value or 0.0,
                result=child.result,
                close_requested=bool(child.close_requested),
                pause_requested=bool(child.pause_requested),
            ))

    is_owner = viewer_id is not None and ch.user_id == viewer_id and ch.parent_id is None

    days_left: int | None = None
    if ch.deadline:
        days_left = max(0, (ch.deadline - datetime.now()).days)

    # Заморожен ли сейчас
    is_paused = bool(ch.pause_until and ch.pause_until > datetime.now())

    is_child = ch.parent_id is not None

    return ChallengeOut(
        id=ch.id, title=ch.title, ch_type=ch.ch_type,
        min_per_run=ch.min_per_run or 0, min_minutes_per_run=ch.min_minutes_per_run or 0,
        goal_runs=ch.goal_runs or 0, goal_value=ch.goal_value or 0, goal_time=ch.goal_time,
        current_value=ch.current_value or 0, current_runs=ch.current_runs or 0,
        penalty=ch.penalty, is_active=ch.is_active,
        started_at=ch.started_at, deadline=ch.deadline,
        author_username=author.username if author else None,
        author_nick=author.school_nick if author else "?",
        is_owner=is_owner, is_participant=is_participant,
        days_left=days_left,
        is_paused=is_paused,
        close_requested=bool(ch.close_requested),
        pause_requested=bool(ch.pause_requested),
        result=ch.result,
        my_current_value=my_current_value if not is_child else (ch.current_value or 0.0),
        my_current_runs=my_current_runs if not is_child else (ch.current_runs or 0),
        viewer_id=viewer_id,
        parent_id=ch.parent_id,
        is_child=is_child,
        participants=participants,
    )


# ─── Мои активные ────────────────────────────────────────────

@router.get("/my", response_model=list[ChallengeOut])
async def get_my_challenges(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    user_id = tg_user["id"]
    # Все челленджи пользователя: свои (parent_id=None) + дочерние (участие в чужих)
    res = await db.execute(
        select(Challenge).where(Challenge.user_id == user_id, Challenge.is_active == True)
        .order_by(Challenge.created_at.desc())
    )
    all_ch = list(res.scalars().all())
    return [await _enrich_challenge(ch, db, user_id) for ch in all_ch]


# ─── История ─────────────────────────────────────────────────

@router.get("/my/history", response_model=list[ChallengeOut])
async def get_my_history(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    user_id = tg_user["id"]
    res = await db.execute(
        select(Challenge).where(Challenge.user_id == user_id, Challenge.is_active == False)
        .order_by(Challenge.created_at.desc()).limit(50)
    )
    all_ch = list(res.scalars().all())
    return [await _enrich_challenge(ch, db, user_id) for ch in all_ch]


# ─── Публичные ───────────────────────────────────────────────

@router.get("/club", response_model=list[ChallengeOut])
async def get_club_challenges(
    db: AsyncSession = Depends(get_db),
    tg_user: dict = Depends(get_current_user),
    page: int = 0, page_size: int = 10,
) -> list[ChallengeOut]:
    res = await db.execute(
        select(Challenge).where(
            Challenge.is_public == True,
            Challenge.is_active == True,
            Challenge.parent_id.is_(None),  # только корневые
        )
        .order_by(Challenge.created_at.desc()).offset(page * page_size).limit(page_size)
    )
    return [await _enrich_challenge(ch, db, tg_user["id"]) for ch in res.scalars().all()]


@router.get("/club/count")
async def get_club_challenges_count(db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(
        select(func.count()).select_from(Challenge).where(
            Challenge.is_public == True,
            Challenge.is_active == True,
            Challenge.parent_id.is_(None),
        )
    )
    return {"total": res.scalar()}


# ─── Карточка ────────────────────────────────────────────────

@router.get("/{challenge_id}", response_model=ChallengeOut)
async def get_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChallengeOut:
    res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = res.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Челлендж не найден")
    return await _enrich_challenge(ch, db, tg_user["id"])


# ─── Создание ────────────────────────────────────────────────

@router.post("", response_model=OkResponse)
async def create_challenge(
    body: dict,
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]
    ch_type = body.get("ch_type", "")
    title   = (body.get("title") or "").strip()

    if not title:
        return OkResponse(ok=False, reason="Введи название челленджа")
    if ch_type not in ("weekly_runs", "daily_km", "weekly_km", "monthly_km", "race"):
        return OkResponse(ok=False, reason="Неизвестный тип челленджа")

    goal_runs           = int(body.get("goal_runs") or 0)
    goal_value          = float(body.get("goal_value") or 0)
    min_per_run         = float(body.get("min_per_run") or 0)
    min_minutes_per_run = int(body.get("min_minutes_per_run") or 0)
    penalty             = (body.get("penalty") or "").strip() or None
    is_public           = bool(body.get("is_public", True))
    started_at          = datetime.now()

    deadline: datetime | None = None
    if ch_type in _SPRINT_DAYS:
        deadline = started_at + timedelta(days=_SPRINT_DAYS[ch_type])
    elif ch_type in ("weekly_runs", "race") and body.get("deadline"):
        try:
            deadline = datetime.strptime(body["deadline"], "%d.%m.%Y")
        except ValueError:
            return OkResponse(ok=False, reason="Неверный формат даты. Используй ДД.ММ.ГГГГ")
        if deadline < started_at:
            return OkResponse(ok=False, reason="Дата не может быть в прошлом")

    if ch_type == "weekly_runs" and goal_runs <= 0:
        return OkResponse(ok=False, reason="Укажи количество пробежек в неделю")
    if ch_type in ("daily_km", "weekly_km", "monthly_km", "race") and goal_value <= 0:
        return OkResponse(ok=False, reason="Укажи целевую дистанцию")

    ch = Challenge(
        user_id=user_id, title=title, ch_type=ch_type,
        min_per_run=min_per_run, min_minutes_per_run=min_minutes_per_run,
        goal_runs=goal_runs, goal_value=goal_value,
        penalty=penalty, is_public=is_public, is_active=True,
        started_at=started_at, deadline=deadline,
    )
    db.add(ch)
    await db.commit()
    return OkResponse(ok=True, reason="Челлендж создан!")


# ─── Присоединиться ──────────────────────────────────────────

@router.post("/{challenge_id}/join", response_model=OkResponse)
async def join_challenge(
    challenge_id: int, body: JoinChallengeRequest,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]
    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch or not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж не найден или завершён.")
    if not ch.is_public or ch.parent_id is not None:
        return OkResponse(ok=False, reason="Челлендж закрыт для присоединения.")
    if ch.user_id == user_id:
        return OkResponse(ok=False, reason="Это твой собственный челлендж.")
    # Проверяем: дочерний уже есть?
    exist = await db.execute(
        select(Challenge).where(
            Challenge.parent_id == challenge_id,
            Challenge.user_id == user_id,
        )
    )
    if exist.scalar_one_or_none():
        return OkResponse(ok=False, reason="Ты уже участвуешь в этом челлендже.")

    # Создаём дочерний Challenge
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
        penalty=body.penalty,
        is_public=False,
        is_active=True,
        started_at=now,
        deadline=child_deadline,
        parent_id=challenge_id,
    )
    db.add(child)
    await db.commit()
    return OkResponse(ok=True, reason=f"Ты присоединился к «{ch.title}»!")


# ─── Покинуть ────────────────────────────────────────────────

@router.post("/{challenge_id}/leave", response_model=OkResponse)
async def leave_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]
    child_res = await db.execute(
        select(Challenge).where(
            Challenge.parent_id == challenge_id,
            Challenge.user_id == user_id,
            Challenge.is_active == True,
        )
    )
    child = child_res.scalar_one_or_none()
    if not child:
        return OkResponse(ok=False, reason="Ты не участвуешь в этом челлендже.")
    child.is_active = False
    child.result = "closed"
    await db.commit()
    return OkResponse(ok=True, reason="Ты вышел из челленджа.")


# ─── Запрос на закрытие (автор → уведомление admin) ─────────

@router.post("/{challenge_id}/request-close", response_model=OkResponse)
async def request_close_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Автор просит закрыть челлендж. Отправляет запрос администратору."""
    user_id = tg_user["id"]
    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return OkResponse(ok=False, reason="Челлендж не найден.")
    if ch.user_id != user_id:
        return OkResponse(ok=False, reason="Только автор может запросить завершение.")
    if not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж уже завершён.")
    if ch.close_requested:
        return OkResponse(ok=False, reason="Запрос уже отправлен, ожидай решения администратора.")

    ch.close_requested = True
    await db.commit()

    # Получаем ник автора
    nick_res = await db.execute(select(User.school_nick).where(User.tg_id == user_id))
    author_nick = nick_res.scalar_one_or_none() or f"ID {user_id}"

    # Уведомляем админов через бота с кнопками
    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Разрешить завершение", callback_data=f"ch_close_ok:{challenge_id}")
        kb.button(text="❌ Отказать",             callback_data=f"ch_close_no:{challenge_id}")
        kb.adjust(2)

        progress = (
            f"{ch.current_runs} пробежек" if ch.ch_type == "weekly_runs"
            else f"{ch.current_value:.1f} / {ch.goal_value:.1f} км"
        )
        text = (
            f"🏁 <b>Запрос на завершение челленджа</b>\n\n"
            f"<b>{ch.title}</b>\n"
            f"Автор: {author_nick}\n"
            f"Прогресс: {progress}\n\n"
            f"Разрешить досрочное завершение?"
        )
        await _notify_admins(text, kb.as_markup(), db)
    except Exception as e:
        import logging
        logging.getLogger("challenges").warning(f"Ошибка уведомления: {e}")

    return OkResponse(ok=True, reason="Запрос отправлен администратору. Ожидай решения.")


# ─── Сдаться (участник → result=failed + публикация) ───────

@router.post("/{challenge_id}/surrender", response_model=OkResponse)
async def surrender_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Участник сдаётся — result=failed, публикация в группу со ставкой."""
    user_id = tg_user["id"]
    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return OkResponse(ok=False, reason="Челлендж не найден.")
    if not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж уже завершён.")

    # Поддержка обеих архитектур:
    # - если challenge_id — это дочерний (parent_id NOT NULL, user_id=я)
    # - или ищем дочерний через parent_id
    if ch.user_id == user_id and ch.parent_id is not None:
        # Передан сразу child_id
        child = ch
    else:
        child_res = await db.execute(
            select(Challenge).where(
                Challenge.parent_id == challenge_id,
                Challenge.user_id == user_id,
            )
        )
        child = child_res.scalar_one_or_none()

    if not child:
        return OkResponse(ok=False, reason="Ты не участник этого челленджа.")
    if child.result:
        return OkResponse(ok=False, reason="Твоё участие уже завершено.")

    child.result = "failed"
    child.is_active = False
    await db.commit()

    # Публикуем в группу
    nick_res = await db.execute(select(User.school_nick, User.username).where(User.tg_id == user_id))
    u_row = nick_res.one_or_none()
    name = f"@{u_row[1]}" if u_row and u_row[1] else (u_row[0] if u_row else str(user_id))
    penalty_str = f" 💰 Ставка: {part.penalty}" if part.penalty else ""
    try:
        from notify import queue_message as _qm
        import config as _cfg
        if _cfg.DIGEST_THREAD_ID and _cfg.GROUP_ID:
            # Сообщение в болталку через pending_notifications
            # GROUP_ID используем как user_id — бот сам опубликует в нужный топик
            import json as _json
            from models import PendingNotification
            db.add(PendingNotification(
                user_tg_id=_cfg.GROUP_ID,
                text=f"🏳️ <b>{name}</b> сдался в челлендже «{ch.title}».{penalty_str}",
                kb_json=_json.dumps({"thread_id": _cfg.DIGEST_THREAD_ID}),
            ))
            await db.commit()
    except Exception:
        pass

    return OkResponse(ok=True, reason="Ты вышел из челленджа. Результат зафиксирован как не выполнен.")


# ─── Запросы участника (не автора) ─────────────────────────

@router.post("/{challenge_id}/request-close-participation", response_model=OkResponse)
async def request_close_participation(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Участник просит закрыть его участие без штрафа."""
    user_id = tg_user["id"]
    from models import ChallengeParticipant as CP
    p_res = await db.execute(
        select(CP).where(CP.challenge_id == challenge_id, CP.user_id == user_id)
    )
    part = p_res.scalar_one_or_none()
    if not part:
        return OkResponse(ok=False, reason="Ты не участник.")
    if part.result:
        return OkResponse(ok=False, reason="Участие уже завершено.")
    if part.close_requested:
        return OkResponse(ok=False, reason="Запрос уже отправлен.")

    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch or not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж не найден.")

    part.close_requested = True
    await db.commit()

    nick_res = await db.execute(select(User.school_nick, User.username).where(User.tg_id == user_id))
    u_row = nick_res.one_or_none()
    name = f"@{u_row[1]}" if u_row and u_row[1] else (u_row[0] if u_row else str(user_id))

    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Закрыть без штрафа", callback_data=f"part_close_ok:{challenge_id}:{user_id}")
        kb.button(text="❌ Отказать",           callback_data=f"part_close_no:{challenge_id}:{user_id}")
        kb.adjust(2)
        await _notify_admins(
            f"🏁 <b>Запрос на закрытие участия</b>\n\n"
            f"Челлендж: <b>{ch.title}</b>\n"
            f"Участник: {name}\n\n"
            f"Закрыть без штрафа?",
            kb.as_markup(), db
        )
    except Exception:
        pass

    return OkResponse(ok=True, reason="Запрос отправлен администратору.")


@router.post("/{challenge_id}/request-pause-participation", response_model=OkResponse)
async def request_pause_participation(
    challenge_id: int, body: PauseRequest,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Участник просит паузу своего участия."""
    user_id = tg_user["id"]
    from models import ChallengeParticipant as CP
    p_res = await db.execute(
        select(CP).where(CP.challenge_id == challenge_id, CP.user_id == user_id)
    )
    part = p_res.scalar_one_or_none()
    if not part:
        return OkResponse(ok=False, reason="Ты не участник.")
    if part.result:
        return OkResponse(ok=False, reason="Участие уже завершено.")
    if part.pause_requested:
        return OkResponse(ok=False, reason="Запрос уже отправлен.")

    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch or not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж не найден.")

    part.pause_requested = True
    part.pause_reason = body.reason.strip() if body.reason else None
    await db.commit()

    nick_res = await db.execute(select(User.school_nick, User.username).where(User.tg_id == user_id))
    u_row = nick_res.one_or_none()
    name = f"@{u_row[1]}" if u_row and u_row[1] else (u_row[0] if u_row else str(user_id))

    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="⏸ Одобрить паузу", callback_data=f"part_pause_ok:{challenge_id}:{user_id}")
        kb.button(text="❌ Отказать",      callback_data=f"part_pause_no:{challenge_id}:{user_id}")
        kb.adjust(2)
        reason_str = f"\nПричина: {part.pause_reason}" if part.pause_reason else ""
        await _notify_admins(
            f"⏸ <b>Запрос на паузу участия</b>\n\n"
            f"Челлендж: <b>{ch.title}</b>\n"
            f"Участник: {name}"
            f"{reason_str}\n\n"
            f"Одобрить паузу участника?",
            kb.as_markup(), db
        )
    except Exception:
        pass

    return OkResponse(ok=True, reason="Запрос на паузу отправлен администратору.")


# ─── Запрос на паузу (автор → уведомление admin) ───────────


@router.post("/{challenge_id}/request-pause", response_model=OkResponse)
async def request_pause_challenge(
    challenge_id: int, body: PauseRequest,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Автор просит поставить челлендж на паузу. Причина сохраняется в БД."""
    user_id = tg_user["id"]
    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return OkResponse(ok=False, reason="Челлендж не найден.")
    if ch.user_id != user_id:
        return OkResponse(ok=False, reason="Только автор может запросить паузу.")
    if not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж уже завершён.")
    if ch.pause_requested:
        return OkResponse(ok=False, reason="Запрос уже отправлен, ожидай решения администратора.")
    if ch.pause_until and ch.pause_until > datetime.now():
        return OkResponse(ok=False, reason="Челлендж уже на паузе.")

    ch.pause_requested = True
    ch.pause_reason = body.reason.strip() if body.reason else None
    await db.commit()

    nick_res = await db.execute(select(User.school_nick).where(User.tg_id == user_id))
    author_nick = nick_res.scalar_one_or_none() or f"ID {user_id}"

    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="⏸ Одобрить паузу",  callback_data=f"ch_pause_ok:{challenge_id}")
        kb.button(text="❌ Отказать",        callback_data=f"ch_pause_no:{challenge_id}")
        kb.adjust(2)

        reason_str = f"\nПричина: {ch.pause_reason}" if ch.pause_reason else ""
        text = (
            f"⏸ <b>Запрос на паузу челленджа</b>\n\n"
            f"<b>{ch.title}</b>\n"
            f"Автор: {author_nick}"
            f"{reason_str}\n\n"
            f"Одобрить паузу?"
        )
        await _notify_admins(text, kb.as_markup(), db)
    except Exception as e:
        import logging
        logging.getLogger("challenges").warning(f"Ошибка уведомления: {e}")

    return OkResponse(ok=True, reason="Запрос на паузу отправлен администратору. Ожидай решения.")


# ─── Запрос на разморозку (автор → уведомление admin) ───────

@router.post("/{challenge_id}/request-unfreeze", response_model=OkResponse)
async def request_unfreeze_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Автор просит снять паузу с челленджа."""
    user_id = tg_user["id"]
    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return OkResponse(ok=False, reason="Челлендж не найден.")
    if ch.user_id != user_id:
        return OkResponse(ok=False, reason="Только автор может запросить разморозку.")
    if not (ch.pause_until and ch.pause_until > datetime.now()):
        return OkResponse(ok=False, reason="Челлендж не на паузе.")

    nick_res = await db.execute(select(User.school_nick).where(User.tg_id == user_id))
    author_nick = nick_res.scalar_one_or_none() or f"ID {user_id}"

    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="▶️ Разморозить",  callback_data=f"ch_unfreeze_ok:{challenge_id}")
        kb.button(text="❌ Отказать",     callback_data=f"ch_unfreeze_no:{challenge_id}")
        kb.adjust(2)
        text = (
            f"▶️ <b>Запрос на разморозку челленджа</b>\n\n"
            f"<b>{ch.title}</b>\n"
            f"Автор: {author_nick}\n\n"
            f"Разморозить челлендж?"
        )
        await _notify_admins(text, kb.as_markup(), db)
    except Exception as e:
        import logging
        logging.getLogger("challenges").warning(f"Ошибка уведомления: {e}")

    return OkResponse(ok=True, reason="Запрос на разморозку отправлен администратору.")


# ─── Заморозка (только admin через Mini App) ────────────────

class FreezeRequest(BaseModel):
    days: int = 7


@router.post("/{challenge_id}/freeze", response_model=OkResponse)
async def freeze_challenge(
    challenge_id: int, body: FreezeRequest,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Заморозить челлендж на N дней. Только администратор."""
    from config import ADMIN_IDS
    if tg_user["id"] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Только администратор может замораживать челленджи.")

    ch_res = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return OkResponse(ok=False, reason="Челлендж не найден.")
    if not ch.is_active:
        return OkResponse(ok=False, reason="Челлендж уже завершён.")

    ch.pause_until = datetime.now() + timedelta(days=body.days)
    await db.commit()

    # Уведомляем автора через pending_notifications
    from notify import queue_message as _qm
    await _qm(
        db, ch.user_id,
        f"❄️ Твой челлендж <b>«{ch.title}»</b> заморожен на {body.days} дней.\n"
        f"Пробежки не будут засчитываться до {ch.pause_until.strftime('%d.%m.%Y')}.",
    )

    return OkResponse(ok=True, reason=f"Челлендж заморожен на {body.days} дней.")