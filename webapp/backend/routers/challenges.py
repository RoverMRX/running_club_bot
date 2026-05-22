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


async def _notify_admins(text: str, kb=None) -> None:
    """Уведомить всех администраторов через бота."""
    try:
        from config import ADMIN_IDS
        bot = _make_bot()
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, reply_markup=kb)
            except Exception:
                pass
        await bot.session.close()
    except Exception as e:
        import logging
        logging.getLogger("challenges").warning(f"Ошибка уведомления админов: {e}")


async def _enrich_challenge(ch: Challenge, db: AsyncSession, viewer_id: int | None = None) -> ChallengeOut:
    author_res = await db.execute(select(User).where(User.tg_id == ch.user_id))
    author = author_res.scalar_one_or_none()

    parts_res = await db.execute(
        select(ChallengeParticipant, User)
        .join(User, User.tg_id == ChallengeParticipant.user_id)
        .where(ChallengeParticipant.challenge_id == ch.id)
        .order_by(ChallengeParticipant.joined_at)
    )
    participants = []
    is_participant = False
    for p, u in parts_res.all():
        if viewer_id and u.tg_id == viewer_id:
            is_participant = True
        participants.append(ChallengeParticipantOut(
            user_id=u.tg_id, username=u.username, school_nick=u.school_nick,
            penalty=p.penalty, current_runs=p.current_runs, current_value=p.current_value,
        ))

    is_owner = viewer_id is not None and ch.user_id == viewer_id

    days_left: int | None = None
    if ch.deadline:
        days_left = max(0, (ch.deadline - datetime.now()).days)

    # Заморожен ли сейчас
    is_paused = bool(ch.pause_until and ch.pause_until > datetime.now())

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
        participants=participants,
    )


# ─── Мои активные ────────────────────────────────────────────

@router.get("/my", response_model=list[ChallengeOut])
async def get_my_challenges(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    user_id = tg_user["id"]
    own_res = await db.execute(
        select(Challenge).where(Challenge.user_id == user_id, Challenge.is_active == True)
        .order_by(Challenge.created_at.desc())
    )
    joined_res = await db.execute(
        select(Challenge)
        .join(ChallengeParticipant, ChallengeParticipant.challenge_id == Challenge.id)
        .where(ChallengeParticipant.user_id == user_id, Challenge.user_id != user_id, Challenge.is_active == True)
        .order_by(Challenge.created_at.desc())
    )
    all_ch = list(own_res.scalars().all()) + list(joined_res.scalars().all())
    return [await _enrich_challenge(ch, db, user_id) for ch in all_ch]


# ─── История ─────────────────────────────────────────────────

@router.get("/my/history", response_model=list[ChallengeOut])
async def get_my_history(
    tg_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    user_id = tg_user["id"]
    own_res = await db.execute(
        select(Challenge).where(Challenge.user_id == user_id, Challenge.is_active == False)
        .order_by(Challenge.created_at.desc()).limit(30)
    )
    joined_res = await db.execute(
        select(Challenge)
        .join(ChallengeParticipant, ChallengeParticipant.challenge_id == Challenge.id)
        .where(ChallengeParticipant.user_id == user_id, Challenge.user_id != user_id, Challenge.is_active == False)
        .order_by(Challenge.created_at.desc()).limit(20)
    )
    all_ch = list(own_res.scalars().all()) + list(joined_res.scalars().all())
    return [await _enrich_challenge(ch, db, user_id) for ch in all_ch]


# ─── Публичные ───────────────────────────────────────────────

@router.get("/club", response_model=list[ChallengeOut])
async def get_club_challenges(
    db: AsyncSession = Depends(get_db),
    tg_user: dict = Depends(get_current_user),
    page: int = 0, page_size: int = 10,
) -> list[ChallengeOut]:
    res = await db.execute(
        select(Challenge).where(Challenge.is_public == True, Challenge.is_active == True)
        .order_by(Challenge.created_at.desc()).offset(page * page_size).limit(page_size)
    )
    return [await _enrich_challenge(ch, db, tg_user["id"]) for ch in res.scalars().all()]


@router.get("/club/count")
async def get_club_challenges_count(db: AsyncSession = Depends(get_db)) -> dict:
    res = await db.execute(
        select(func.count()).where(Challenge.is_public == True, Challenge.is_active == True)
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
    if not ch.is_public:
        return OkResponse(ok=False, reason="Челлендж закрыт для присоединения.")
    if ch.user_id == user_id:
        return OkResponse(ok=False, reason="Это твой собственный челлендж.")
    exist = await db.execute(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == challenge_id,
            ChallengeParticipant.user_id == user_id,
        )
    )
    if exist.scalar_one_or_none():
        return OkResponse(ok=False, reason="Ты уже участвуешь в этом челлендже.")
    db.add(ChallengeParticipant(challenge_id=challenge_id, user_id=user_id, penalty=body.penalty))
    await db.commit()
    return OkResponse(ok=True, reason=f"Ты присоединился к «{ch.title}»!")


# ─── Покинуть ────────────────────────────────────────────────

@router.post("/{challenge_id}/leave", response_model=OkResponse)
async def leave_challenge(
    challenge_id: int,
    tg_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = tg_user["id"]
    part = await db.execute(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == challenge_id,
            ChallengeParticipant.user_id == user_id,
        )
    )
    p = part.scalar_one_or_none()
    if not p:
        return OkResponse(ok=False, reason="Ты не участвуешь в этом челлендже.")
    await db.delete(p)
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
        await _notify_admins(text, kb.as_markup())
    except Exception as e:
        import logging
        logging.getLogger("challenges").warning(f"Ошибка уведомления: {e}")

    return OkResponse(ok=True, reason="Запрос отправлен администратору. Ожидай решения.")


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

    # Уведомляем автора
    try:
        from config import BOT_TOKEN
        from aiogram import Bot
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            ch.user_id,
            f"❄️ Твой челлендж <b>«{ch.title}»</b> заморожен на {body.days} дней.\n"
            f"Пробежки не будут засчитываться до {ch.pause_until.strftime('%d.%m.%Y')}.",
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception:
        pass

    return OkResponse(ok=True, reason=f"Челлендж заморожен на {body.days} дней.")