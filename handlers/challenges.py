"""
handlers/challenges.py — FSM создания челленджа (aiogram 3).

Флоу по типам:
  weekly_runs : title → runs → min_km → min_min → start → [choose_end →] end → penalty → confirm
  daily_km    : title → goal_km → start → penalty → confirm
  weekly_km   : title → goal_km → start → penalty → confirm
  monthly_km  : title → goal_km → start → penalty → confirm
  race        : title → goal_km → goal_time → start → penalty → confirm

Inline-кнопки используются для:
  - выбора типа челленджа
  - выбора режима даты окончания (weekly_runs): «указать дату» / «бессрочный»
  - подтверждения создания
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from keyboards import (
    get_challenge_type_inline_kb,
    get_confirm_inline_kb,
    get_end_date_inline_kb,
    get_cancel_kb,
    get_main_kb,
    get_challenges_menu_kb,
)
from services.challenges import create_challenge, get_type_name, get_public_challenges, join_challenge

log = logging.getLogger(__name__)
router = Router()

DATE_FMT = "%d.%m.%Y"

SPRINT_TYPES = {"daily_km", "weekly_km", "monthly_km"}

TYPE_LABELS = {
    "weekly_runs": "📜 Регулярный (N пробежек в неделю)",
    "daily_km":    "🎯 Дневной спринт (N км за день)",
    "weekly_km":   "📅 Недельный спринт (N км за неделю)",
    "monthly_km":  "📆 Месячный спринт (N км за месяц)",
    "race":        "🏃 Разовый забег (N км за время)",
}


# ─── FSM ───
class ChallengeCreate(StatesGroup):
    choose_type     = State()
    enter_title     = State()
    enter_runs      = State()   # weekly_runs: кол-во пробежек в неделю
    enter_min_km    = State()   # weekly_runs: мин. км на пробежку
    enter_min_min   = State()   # weekly_runs: мин. минут на пробежку
    enter_goal_km   = State()   # спринты + race: целевая дистанция
    enter_goal_time = State()   # race: целевое время в минутах
    enter_start     = State()   # дата старта (для race — дата забега)
    choose_end      = State()   # weekly_runs: inline-выбор режима даты окончания
    enter_end       = State()   # weekly_runs: ввод конкретной даты окончания
    enter_penalty   = State()   # цена слова / штраф
    confirm         = State()   # подтверждение


# ─── Вспомогательные функции ───

def _parse_date(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), DATE_FMT)
    except ValueError:
        return None


def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime(DATE_FMT) if dt else "—"


def _build_summary(data: dict) -> str:
    ch_type = data["ch_type"]
    lines = [
        f"*{data['title']}*",
        f"Тип: {get_type_name(ch_type)}",
    ]
    if ch_type == "weekly_runs":
        lines.append(f"Пробежек в неделю: {data['goal_runs']}")
        if data.get("min_per_run"):
            lines.append(f"Мин. км на пробежку: {data['min_per_run']}")
        if data.get("min_minutes_per_run"):
            lines.append(f"Мин. минут на пробежку: {data['min_minutes_per_run']}")
        lines.append(f"Старт: {_fmt_date(data.get('started_at'))}")
        end = data.get("deadline")
        lines.append(f"Конец: {_fmt_date(end) if end else 'бессрочно'}")
    elif ch_type in SPRINT_TYPES:
        days = {"daily_km": 1, "weekly_km": 7, "monthly_km": 30}[ch_type]
        lines.append(f"Цель: {data['goal_value']} км")
        lines.append(f"Старт: {_fmt_date(data.get('started_at'))}")
        lines.append(f"Дедлайн: автоматически +{days} д. от старта")
    elif ch_type == "race":
        lines.append(f"Дистанция: {data['goal_value']} км")
        lines.append(f"Целевое время: {data.get('goal_time', '—')} мин")
        lines.append(f"Дата забега: {_fmt_date(data.get('started_at'))}")
    if data.get("penalty"):
        lines.append(f"Цена слова: {data['penalty']}")
    return "\n".join(lines)


# ─── Точка входа ───

@router.message(F.text == "🏃 Создать челлендж")
async def cmd_create_challenge(message: Message, state: FSMContext) -> None:
    await state.set_state(ChallengeCreate.choose_type)
    await message.answer(
        "Выбери тип челленджа:",
        reply_markup=get_challenge_type_inline_kb(),
    )


# ─── Отмена через reply-кнопку ───

@router.message(F.text == "❌ Отмена", ChallengeCreate)
async def cancel_by_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание челленджа отменено.", reply_markup=get_challenges_menu_kb())


# ─── Шаг 1: выбор типа (callback) ───

@router.callback_query(F.data.startswith("ch_type:"), ChallengeCreate.choose_type)
async def cb_choose_type(call: CallbackQuery, state: FSMContext) -> None:
    ch_type = call.data.split(":", 1)[1]

    if ch_type == "cancel":
        await state.clear()
        await call.message.edit_text("Создание челленджа отменено.")
        await call.message.answer("🎯 Челленджи", reply_markup=get_challenges_menu_kb())
        await call.answer()
        return

    await state.update_data(ch_type=ch_type)
    await call.message.edit_text(f"Тип: {TYPE_LABELS.get(ch_type, ch_type)}")
    await call.answer()

    await state.set_state(ChallengeCreate.enter_title)
    await call.message.answer(
        "Придумай название для челленджа:",
        reply_markup=get_cancel_kb(),
    )


# ─── Шаг 2: название ───

@router.message(ChallengeCreate.enter_title)
async def step_enter_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not title:
        await message.answer("Название не может быть пустым. Попробуй ещё раз:")
        return

    await state.update_data(title=title)
    data = await state.get_data()
    ch_type = data["ch_type"]

    if ch_type == "weekly_runs":
        await state.set_state(ChallengeCreate.enter_runs)
        await message.answer("Сколько пробежек в неделю нужно сделать?")
    else:
        await state.set_state(ChallengeCreate.enter_goal_km)
        label = "дистанция" if ch_type == "race" else "цель"
        await message.answer(f"Укажи {label} в км (например: 10 или 10.5):")


# ─── weekly_runs: кол-во пробежек ───

@router.message(ChallengeCreate.enter_runs)
async def step_enter_runs(message: Message, state: FSMContext) -> None:
    try:
        runs = int(message.text.strip())
        if runs <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи целое положительное число:")
        return

    await state.update_data(goal_runs=runs)
    await state.set_state(ChallengeCreate.enter_min_km)
    await message.answer(
        "Минимальная дистанция для зачёта пробежки (км)?\n"
        "Введи 0, если условия по км нет."
    )


# ─── weekly_runs: мин. км ───

@router.message(ChallengeCreate.enter_min_km)
async def step_enter_min_km(message: Message, state: FSMContext) -> None:
    try:
        km = float(message.text.strip().replace(",", "."))
        if km < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи число ≥ 0 (например: 5 или 0):")
        return

    await state.update_data(min_per_run=km)
    await state.set_state(ChallengeCreate.enter_min_min)
    await message.answer(
        "Минимальная продолжительность для зачёта пробежки (минуты)?\n"
        "Введи 0, если условия по времени нет.\n"
        "_(Пробежка засчитывается, если выполнено ЛЮБОЕ из двух условий)_",
        parse_mode="Markdown",
    )


# ─── weekly_runs: мин. минут ───

@router.message(ChallengeCreate.enter_min_min)
async def step_enter_min_min(message: Message, state: FSMContext) -> None:
    try:
        mins = int(message.text.strip())
        if mins < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи целое число ≥ 0:")
        return

    await state.update_data(min_minutes_per_run=mins)
    await state.set_state(ChallengeCreate.enter_start)
    await message.answer("Дата старта (ДД.ММ.ГГГГ):")


# ─── спринты + race: цель в км ───

@router.message(ChallengeCreate.enter_goal_km)
async def step_enter_goal_km(message: Message, state: FSMContext) -> None:
    try:
        km = float(message.text.strip().replace(",", "."))
        if km <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи положительное число (например: 10 или 21.1):")
        return

    await state.update_data(goal_value=km)
    data = await state.get_data()

    if data["ch_type"] == "race":
        await state.set_state(ChallengeCreate.enter_goal_time)
        await message.answer("Целевое время для забега (в минутах, например: 60):")
    else:
        await state.set_state(ChallengeCreate.enter_start)
        await message.answer("Дата старта (ДД.ММ.ГГГГ):")


# ─── race: целевое время ───

@router.message(ChallengeCreate.enter_goal_time)
async def step_enter_goal_time(message: Message, state: FSMContext) -> None:
    try:
        mins = int(message.text.strip())
        if mins <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи целое положительное число минут (например: 60):")
        return

    await state.update_data(goal_time=mins)
    await state.set_state(ChallengeCreate.enter_start)
    await message.answer("Дата забега (ДД.ММ.ГГГГ):")


# ─── Дата старта (все типы) ───

@router.message(ChallengeCreate.enter_start)
async def step_enter_start(message: Message, state: FSMContext) -> None:
    dt = _parse_date(message.text)
    if dt is None:
        await message.answer("Неверный формат. Используй ДД.ММ.ГГГГ (например: 01.06.2025):")
        return

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if dt < today:
        await message.answer(
            "Дата не может быть в прошлом. Введи сегодняшнюю или будущую дату:"
        )
        return

    await state.update_data(started_at=dt)
    data = await state.get_data()

    if data["ch_type"] == "weekly_runs":
        await state.set_state(ChallengeCreate.choose_end)
        await message.answer(
            "Дата окончания челленджа:",
            reply_markup=get_end_date_inline_kb(),
        )
    else:
        await state.set_state(ChallengeCreate.enter_penalty)
        await message.answer(
            "Цена слова / штраф за невыполнение (или «-» если без штрафа):"
        )


# ─── weekly_runs: выбор режима даты окончания (callback) ───

@router.callback_query(F.data.startswith("ch_end:"), ChallengeCreate.choose_end)
async def cb_choose_end(call: CallbackQuery, state: FSMContext) -> None:
    action = call.data.split(":", 1)[1]

    if action == "open":
        await state.update_data(deadline=None)
        await call.message.edit_text("Дата окончания: ♾️ бессрочно")
        await call.answer()
        await state.set_state(ChallengeCreate.enter_penalty)
        await call.message.answer(
            "Цена слова / штраф за невыполнение (или «-» если без штрафа):"
        )
    else:
        await call.message.edit_text("Дата окончания: введи вручную")
        await call.answer()
        await state.set_state(ChallengeCreate.enter_end)
        await call.message.answer("Введи дату окончания (ДД.ММ.ГГГГ):")


# ─── weekly_runs: ввод даты окончания ───

@router.message(ChallengeCreate.enter_end)
async def step_enter_end(message: Message, state: FSMContext) -> None:
    deadline = _parse_date(message.text)
    if deadline is None:
        await message.answer("Неверный формат. Используй ДД.ММ.ГГГГ:")
        return

    data = await state.get_data()
    if deadline <= data["started_at"]:
        await message.answer("Дата окончания должна быть позже даты старта:")
        return

    await state.update_data(deadline=deadline)
    await state.set_state(ChallengeCreate.enter_penalty)
    await message.answer(
        "Цена слова / штраф за невыполнение (или «-» если без штрафа):"
    )


# ─── Штраф ───

@router.message(ChallengeCreate.enter_penalty)
async def step_enter_penalty(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    penalty = None if text == "-" else text

    await state.update_data(penalty=penalty)
    data = await state.get_data()

    await state.set_state(ChallengeCreate.confirm)
    await message.answer(
        f"Проверь данные:\n\n{_build_summary(data)}",
        parse_mode="Markdown",
        reply_markup=get_confirm_inline_kb(),
    )


# ─── Подтверждение (callback) ───

@router.callback_query(F.data.startswith("ch_confirm:"), ChallengeCreate.confirm)
async def cb_confirm(call: CallbackQuery, state: FSMContext) -> None:
    action = call.data.split(":", 1)[1]

    if action == "no":
        await state.clear()
        await call.message.edit_text("Создание отменено.")
        await call.message.answer("🎯 Челленджи", reply_markup=get_challenges_menu_kb())
        await call.answer()
        return

    data = await state.get_data()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()

    try:
        ch = await create_challenge(
            user_id=call.from_user.id,
            title=data["title"],
            ch_type=data["ch_type"],
            min_per_run=data.get("min_per_run", 0.0),
            min_minutes_per_run=data.get("min_minutes_per_run", 0),
            goal_runs=data.get("goal_runs", 0),
            goal_value=data.get("goal_value", 0.0),
            goal_time=data.get("goal_time"),
            penalty=data.get("penalty"),
            is_public=True,
            started_at=data.get("started_at"),
            deadline=data.get("deadline"),  # для спринтов перезаписывается в сервисе
        )
    except Exception:
        log.exception("Ошибка при создании челленджа user_id=%s", call.from_user.id)
        await call.message.answer("Произошла ошибка при сохранении. Попробуй позже.")
        await state.clear()
        return

    await state.clear()

    deadline_str = _fmt_date(ch.deadline) if ch.deadline else "бессрочно"
    await call.message.answer(
        f"✅ Челлендж *{ch.title}* создан!\n"
        f"Тип: {get_type_name(ch.ch_type)}\n"
        f"Дедлайн: {deadline_str}",
        parse_mode="Markdown",
        reply_markup=get_main_kb(),
    )



# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

from database import async_session
from models import Challenge, ChallengeParticipant, User
from sqlalchemy import select as _sa_select

_PAGE_SIZE = 10


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции и константы для просмотра челленджей
# ─────────────────────────────────────────────────────────────────────────────

from database import async_session
from models import Challenge, ChallengeParticipant, User
from sqlalchemy import select as _sa_select

_PAGE_SIZE = 10

_CH_TYPE_LABELS = {
    "weekly_runs": "🔄 Регулярный",
    "daily_km":    "📅 Дневной",
    "weekly_km":   "📅 Недельный",
    "monthly_km":  "📆 Месячный",
    "race":        "🏁 Забег",
}


def _ch_label(ch) -> str:
    return _CH_TYPE_LABELS.get(ch.ch_type, ch.ch_type)


def _ch_goal_str(ch) -> str:
    if ch.ch_type == "weekly_runs":
        cond = []
        if ch.min_per_run > 0:
            cond.append(f"{ch.min_per_run} км")
        if ch.min_minutes_per_run > 0:
            cond.append(f"{ch.min_minutes_per_run} мин")
        cond_str = " или ".join(cond) if cond else "любая"
        return f"{ch.goal_runs} пробежек/нед · мин: {cond_str}"
    elif ch.ch_type in ("daily_km", "weekly_km", "monthly_km"):
        return f"Цель: {ch.goal_value:.1f} км"
    elif ch.ch_type == "race":
        s = f"Забег: {ch.goal_value:.1f} км"
        if ch.deadline:
            s += f" · {ch.deadline.strftime('%d.%m.%Y')}"
        return s
    return ""


async def _get_participants_info(challenge_id: int) -> list[dict]:
    async with async_session() as session:
        res = await session.execute(
            _sa_select(ChallengeParticipant, User)
            .join(User, User.tg_id == ChallengeParticipant.user_id)
            .where(ChallengeParticipant.challenge_id == challenge_id)
            .order_by(ChallengeParticipant.joined_at)
        )
        rows = []
        for p, u in res.all():
            rows.append({
                "user_id":       u.tg_id,
                "name":          f"@{u.username}" if u.username else u.school_nick,
                "penalty":       p.penalty,
                "current_runs":  p.current_runs,
                "current_value": p.current_value,
            })
        return rows


def _build_challenge_card_text(ch, author_name: str, participants: list[dict]) -> str:
    lines = [
        f"<b>{ch.title}</b>",
        f"{_ch_label(ch)} · {_ch_goal_str(ch)}",
        f"Автор: {author_name}",
    ]
    if ch.penalty:
        lines.append(f"💰 Ставка автора: {ch.penalty}")
    lines.append("")
    if participants:
        lines.append("👥 <b>Участники:</b>")
        for p in participants:
            stake = f" · 💰 {p['penalty']}" if p["penalty"] else ""
            if ch.ch_type == "weekly_runs":
                prog = f"({p['current_runs']} пробежек)"
            else:
                prog = f"({p['current_value']:.1f} км)"
            lines.append(f"• {p['name']}{stake} {prog}")
    return "\n".join(lines)


def _build_my_card_text(ch, all_participants: list[dict]) -> str:
    lines = [
        f"<b>{ch.title}</b>",
        f"{_ch_label(ch)} · {_ch_goal_str(ch)}",
    ]
    if ch.penalty:
        lines.append(f"💰 Твоя ставка: {ch.penalty}")
    lines.append("")
    if ch.ch_type == "weekly_runs":
        pct = min(100, int(ch.current_runs / ch.goal_runs * 100)) if ch.goal_runs else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"📊 Эта неделя: {ch.current_runs}/{ch.goal_runs} пробежек")
        lines.append(f"[{bar}] {pct}%")
        lines.append(f"📏 Набегано: {ch.current_value:.1f} км")
    elif ch.ch_type in ("daily_km", "weekly_km", "monthly_km", "race"):
        pct = min(100, int(ch.current_value / ch.goal_value * 100)) if ch.goal_value else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"📊 Прогресс: {ch.current_value:.1f}/{ch.goal_value:.1f} км")
        lines.append(f"[{bar}] {pct}%")
    others = [p for p in all_participants if p["user_id"] != ch.user_id]
    if others:
        lines.append("")
        lines.append("👥 <b>Другие участники:</b>")
        for p in others:
            stake = f" · 💰 {p['penalty']}" if p["penalty"] else ""
            if ch.ch_type == "weekly_runs":
                prog = f"({p['current_runs']} пробежек)"
            else:
                prog = f"({p['current_value']:.1f} км)"
            lines.append(f"• {p['name']}{stake} {prog}")
    return "\n".join(lines)


async def _get_challenge_with_author(challenge_id: int):
    async with async_session() as session:
        res = await session.execute(
            _sa_select(Challenge, User)
            .join(User, User.tg_id == Challenge.user_id)
            .where(Challenge.id == challenge_id)
        )
        row = res.one_or_none()
        if not row:
            return None, None
        ch, u = row
        return ch, (f"@{u.username}" if u.username else u.school_nick)


def _challenges_list_kb(challenges: list, page: int, total: int, prefix: str):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for ch in challenges:
        label = f"{_ch_label(ch)}: {ch.title[:35]}"
        builder.button(text=label, callback_data=f"{prefix}_open:{ch.id}:{page}")
    builder.adjust(1)
    total_pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
    nav = []
    if page > 0:
        nav.append(("◀️ Назад", f"{prefix}_page:{page-1}"))
    if (page + 1) * _PAGE_SIZE < total:
        nav.append(("Вперёд ▶️", f"{prefix}_page:{page+1}"))
    for text, cb in nav:
        builder.button(text=text, callback_data=cb)
    if nav:
        builder.adjust(1, len(nav))
    if total_pages > 1:
        builder.button(text=f"📄 {page+1}/{total_pages}", callback_data="noop")
        builder.adjust(1)
    return builder.as_markup()


# FSM для ввода личной ставки при присоединении
class JoinChallengeStates(StatesGroup):
    enter_penalty = State()


# ─────────────────────────────────────────────────────────────────────────────
# МОИ ЧЕЛЛЕНДЖИ
# ─────────────────────────────────────────────────────────────────────────────

@router.message(F.text == "📋 Мои челленджи")
async def cmd_my_challenges(message: Message) -> None:
    user_id = message.from_user.id
    async with async_session() as session:
        res = await session.execute(
            _sa_select(Challenge).where(
                Challenge.user_id == user_id,
                Challenge.is_active == True,
            ).order_by(Challenge.created_at.desc())
        )
        challenges = list(res.scalars().all())

    if not challenges:
        await message.answer(
            "У тебя нет активных челленджей.\nНажми <b>🏃 Создать челлендж</b>!",
            reply_markup=get_challenges_menu_kb(),
        )
        return

    await _send_my_page(message, challenges, page=0, edit=False)


async def _send_my_page(obj, challenges: list, page: int, edit: bool) -> None:
    start = page * _PAGE_SIZE
    page_items = challenges[start:start + _PAGE_SIZE]
    kb = _challenges_list_kb(page_items, page, len(challenges), "my")
    text = f"📋 <b>Мои активные челленджи</b> ({len(challenges)} шт.)\nВыбери для подробностей:"
    if edit:
        await obj.edit_text(text, reply_markup=kb)
    else:
        await obj.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("my_page:"))
async def cb_my_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    user_id = call.from_user.id
    async with async_session() as session:
        res = await session.execute(
            _sa_select(Challenge).where(
                Challenge.user_id == user_id,
                Challenge.is_active == True,
            ).order_by(Challenge.created_at.desc())
        )
        challenges = list(res.scalars().all())
    await _send_my_page(call.message, challenges, page, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("my_open:"))
async def cb_my_open(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])

    ch, _ = await _get_challenge_with_author(challenge_id)
    if not ch:
        await call.answer("Челлендж не найден.", show_alert=True)
        return

    participants = await _get_participants_info(challenge_id)
    text = _build_my_card_text(ch, participants)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К списку", callback_data=f"my_page:{page}")
    builder.adjust(1)

    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


# ─────────────────────────────────────────────────────────────────────────────
# ЧЕЛЛЕНДЖИ КЛУБА
# ─────────────────────────────────────────────────────────────────────────────

@router.message(F.text == "🤝 Челленджи клуба")
async def cmd_public_challenges(message: Message) -> None:
    challenges = await get_public_challenges(exclude_user=None, limit=200)
    if not challenges:
        await message.answer(
            "😔 Пока нет публичных челленджей.",
            reply_markup=get_challenges_menu_kb(),
        )
        return
    await _send_club_page(message, challenges, page=0, edit=False)


async def _send_club_page(obj, challenges: list, page: int, edit: bool) -> None:
    start = page * _PAGE_SIZE
    page_items = challenges[start:start + _PAGE_SIZE]
    kb = _challenges_list_kb(page_items, page, len(challenges), "club")
    text = f"🤝 <b>Челленджи клуба</b> ({len(challenges)} шт.)\nВыбери для подробностей:"
    if edit:
        await obj.edit_text(text, reply_markup=kb)
    else:
        await obj.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("club_page:"))
async def cb_club_page(call: CallbackQuery) -> None:
    page = int(call.data.split(":")[1])
    challenges = await get_public_challenges(exclude_user=None, limit=200)
    await _send_club_page(call.message, challenges, page, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("club_open:"))
async def cb_club_open(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])
    user_id = call.from_user.id

    ch, author_name = await _get_challenge_with_author(challenge_id)
    if not ch:
        await call.answer("Челлендж не найден.", show_alert=True)
        return

    participants = await _get_participants_info(challenge_id)
    text = _build_challenge_card_text(ch, author_name, participants)

    is_own = ch.user_id == user_id
    is_joined = any(p["user_id"] == user_id for p in participants)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if is_own:
        builder.button(text="🏃 Это мой челлендж", callback_data="noop")
    elif is_joined:
        builder.button(text="✅ Ты участвуешь", callback_data="noop")
    else:
        builder.button(text="🤝 Присоединиться", callback_data=f"club_join:{challenge_id}:{page}")
    builder.button(text="⬅️ К списку", callback_data=f"club_page:{page}")
    builder.adjust(1)

    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("club_join:"))
async def cb_club_join_start(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])

    await state.set_state(JoinChallengeStates.enter_penalty)
    await state.update_data(challenge_id=challenge_id, page=page)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="Без ставки ➡️", callback_data="join_no_penalty")
    builder.adjust(1)

    await call.message.edit_text(
        "💰 <b>Укажи свою цену слова</b> (ставку):\n\n"
        "Введи текст или нажми «Без ставки».\n"
        "<i>Например: «Куплю всем кофе» или «Отжимаюсь 50 раз»</i>",
        reply_markup=builder.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "join_no_penalty", JoinChallengeStates.enter_penalty)
async def cb_join_no_penalty(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await _do_join(call, data["challenge_id"], data["page"], penalty=None)


@router.message(JoinChallengeStates.enter_penalty)
async def step_join_penalty(message: Message, state: FSMContext) -> None:
    text = message.text.strip() if message.text else ""
    penalty = text if text and text != "-" else None
    data = await state.get_data()
    await state.clear()

    result = await join_challenge(data["challenge_id"], message.from_user.id, penalty=penalty)
    status = "✅" if result["ok"] else "❌"
    await message.answer(f"{status} {result['reason']}", reply_markup=get_challenges_menu_kb())


async def _do_join(call: CallbackQuery, challenge_id: int, page: int, penalty) -> None:
    result = await join_challenge(challenge_id, call.from_user.id, penalty=penalty)
    if not result["ok"]:
        await call.answer(f"❌ {result['reason']}", show_alert=True)
        return

    ch, author_name = await _get_challenge_with_author(challenge_id)
    participants = await _get_participants_info(challenge_id)
    text = _build_challenge_card_text(ch, author_name, participants)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Ты участвуешь", callback_data="noop")
    builder.button(text="⬅️ К списку", callback_data=f"club_page:{page}")
    builder.adjust(1)

    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer(f"✅ {result['reason']}")