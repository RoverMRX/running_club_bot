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

from aiogram.enums import ChatType
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
from database import async_session
from models import Challenge
from sqlalchemy import select
import config

def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

async def _notify_admins_challenge(bot, text: str, kb=None) -> None:
    """Отправляет уведомление всем админам и модераторам в личку."""
    import logging as _log
    _logger = _log.getLogger("challenges")
    from models import Moderator
    async with async_session() as session:
        from sqlalchemy import select as _sel
        mods = await session.execute(_sel(Moderator))
        mod_ids = [m.tg_id for m in mods.scalars().all()]
    recipients = list(config.ADMIN_IDS) + [m for m in mod_ids if m not in config.ADMIN_IDS]
    _logger.info("Уведомляем %d получателей: %s", len(recipients), recipients)
    for uid in recipients:
        try:
            await bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
            _logger.info("Отправлено %s", uid)
        except Exception as e:
            _logger.warning("Не удалось отправить %s: %s", uid, e)

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

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


def _build_my_card_text(ch, all_participants: list[dict], is_child: bool = False, parent_author: str = "") -> str:
    lines = [
        f"<b>{ch.title}</b>",
        f"{_ch_label(ch)} · {_ch_goal_str(ch)}",
    ]
    if is_child:
        lines.append(f"🤝 Участие · Автор: {parent_author}")
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

# FSM для запросов завершения/паузы через бота
class ChallengeRequestStates(StatesGroup):
    enter_close_reason = State()
    enter_pause_reason = State()


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

    ch, author_name = await _get_challenge_with_author(challenge_id)
    if not ch:
        await call.answer("Челлендж не найден.", show_alert=True)
        return

    if ch.parent_id is not None:
        # Дочерний: показываем автора родительского и прогресс дочернего
        async with async_session() as _s:
            pr = await _s.execute(_sa_select(Challenge, User).join(User, User.tg_id == Challenge.user_id).where(Challenge.id == ch.parent_id))
            prow = pr.one_or_none()
        parent_author = (f"@{prow[1].username}" if prow and prow[1].username else (prow[1].school_nick if prow else "?")) if prow else "?"
        participants = await _get_participants_info(ch.parent_id)
        text = _build_my_card_text(ch, participants, is_child=True, parent_author=parent_author)
    else:
        participants = await _get_participants_info(challenge_id)
        text = _build_my_card_text(ch, participants)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from datetime import datetime as _dt
    builder = InlineKeyboardBuilder()

    is_owner = (ch.user_id == call.from_user.id) and ch.parent_id is None
    is_child  = ch.parent_id is not None
    is_paused = bool(ch.pause_until and ch.pause_until > _dt.now())

    if ch.is_active:
        if is_owner:
            # Кнопки для автора
            if not ch.close_requested:
                builder.button(text="🏁 Запросить завершение",
                               callback_data=f"bot_req_close:{ch.id}:{page}")
            else:
                builder.button(text="⏳ Завершение на рассмотрении", callback_data="noop")

            if is_paused:
                builder.button(text="▶️ Запросить разморозку",
                               callback_data=f"bot_req_unfreeze:{ch.id}:{page}")
            elif not ch.pause_requested:
                builder.button(text="⏸ Запросить паузу",
                               callback_data=f"bot_req_pause:{ch.id}:{page}")
            else:
                builder.button(text="⏳ Пауза на рассмотрении", callback_data="noop")

            # Автор тоже может сдаться (зафиксировать провал)
            builder.button(text="🏳️ Сдаться",
                           callback_data=f"ch_surrender_ask:{ch.id}:{page}")

        elif is_child:
            # Кнопки для участника (дочерний челлендж)
            if not ch.close_requested:
                builder.button(text="🏁 Запросить завершение участия",
                               callback_data=f"child_req_close:{ch.id}:{page}")
            else:
                builder.button(text="⏳ Завершение на рассмотрении", callback_data="noop")
            if is_paused:
                builder.button(text="▶️ Запросить разморозку",
                               callback_data=f"bot_req_unfreeze:{ch.id}:{page}")
            elif not ch.pause_requested:
                builder.button(text="⏸ Запросить паузу участия",
                               callback_data=f"child_req_pause:{ch.id}:{page}")
            else:
                builder.button(text="⏳ Пауза на рассмотрении", callback_data="noop")
            builder.button(text="🏳️ Сдаться",
                           callback_data=f"child_surrender_ask:{ch.id}:{page}")

    builder.button(text="⬅️ К списку", callback_data=f"my_page:{page}")
    builder.adjust(1)

    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
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

# ─── Подтверждение/отказ закрытия (admin callback из Mini App) ───

@router.callback_query(F.data.startswith("ch_close_ok:"))
async def cb_close_ok(callback: CallbackQuery) -> None:
    """Администратор разрешил закрыть челлендж."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    challenge_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch:
            await callback.answer("Челлендж не найден.", show_alert=True)
            return
        if not ch.is_active:
            await callback.answer("Уже завершён.", show_alert=True)
            return
        ch.is_active = False
        ch.close_requested = False
        ch.result = "closed"
        owner_id = ch.user_id
        title = ch.title
        await session.commit()

    try:
        msg = "✅ Администратор разрешил завершить челлендж <b>\u00ab" + title + "\u00bb</b>.\nЧелленд закрыт."
        await callback.bot.send_message(owner_id, msg, parse_mode="HTML")
    except Exception:
        pass

    from services.scheduler import _post_to_digest
    await _post_to_digest(
        callback.bot,
        f"🏁 Челлендж <b>\u00ab{title}\u00bb</b> завершён по согласованию с администратором.",
    )

    await callback.message.edit_text(callback.message.text + "\n\n✅ <b>Завершение разрешено.</b>")
    await callback.answer("Челлендж закрыт.")


@router.callback_query(F.data.startswith("ch_close_no:"))
async def cb_close_no(callback: CallbackQuery) -> None:
    """Администратор отказал в закрытии."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    challenge_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch:
            await callback.answer("Челлендж не найден.", show_alert=True)
            return
        ch.close_requested = False
        owner_id = ch.user_id
        title = ch.title
        await session.commit()

    try:
        msg = "❌ Запрос на завершение челленджа <b>\u00ab" + title + "\u00bb</b> отклонён.\nПродолжай бежать! 🏃"
        await callback.bot.send_message(owner_id, msg, parse_mode="HTML")
    except Exception:
        pass

    await callback.message.edit_text(callback.message.text + "\n\n❌ <b>В завершении отказано.</b>")
    await callback.answer("Запрос отклонён.")

# ─── Сдаться (участник, с подтверждением) ───────────────────

@router.callback_query(F.data.startswith("ch_surrender_ask:"))
async def cb_surrender_ask(call: CallbackQuery) -> None:
    """Показываем подтверждение сдачи с таймером."""
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])
    import time
    expires_at = int(time.time()) + 10
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⏳ Подождите 10с...", callback_data="noop")
    kb.button(text="❌ Отмена", callback_data=f"my_open:{challenge_id}:{page}")
    kb.adjust(1)
    await call.message.edit_text(
        "🏳️ <b>Подтверди сдачу</b>\n\n"
        "Результат будет зафиксирован как <b>не выполнен</b>.\n"
        "Кнопка подтверждения появится через 10 секунд.",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )
    await call.answer()
    # Через 10 сек обновляем кнопку
    import asyncio
    await asyncio.sleep(10)
    try:
        kb2 = InlineKeyboardBuilder()
        kb2.button(text="✅ Подтвердить сдачу",
                   callback_data=f"ch_surrender_confirm:{challenge_id}:{page}")
        kb2.button(text="❌ Отмена", callback_data=f"my_open:{challenge_id}:{page}")
        kb2.adjust(1)
        await call.message.edit_reply_markup(reply_markup=kb2.as_markup())
    except Exception:
        pass


@router.callback_query(F.data.startswith("ch_surrender_confirm:"))
async def cb_surrender_confirm(call: CallbackQuery) -> None:
    """Подтверждение сдачи — работает для автора и для участника (старая схема)."""
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])
    user_id = call.from_user.id

    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = ch_res.scalar_one_or_none()
        if not ch:
            await call.answer("Челлендж не найден.", show_alert=True)
            return
        if ch.result:
            await call.answer("Участие уже завершено.", show_alert=True)
            return
        # Автор корневого — сдаётся сам
        if ch.user_id == user_id and ch.parent_id is None:
            ch.result = "failed"
            ch.is_active = False
            title = ch.title
            penalty = ch.penalty
            await session.commit()
        else:
            # Старая схема — через ChallengeParticipant (совместимость)
            from models import ChallengeParticipant as _CP
            p_res = await session.execute(
                select(_CP).where(_CP.challenge_id == challenge_id, _CP.user_id == user_id)
            )
            part = p_res.scalar_one_or_none()
            if not part or part.result:
                await call.answer("Участие не найдено или уже завершено.", show_alert=True)
                return
            part.result = "failed"
            title = ch.title if ch else "Челлендж"
            penalty = part.penalty
            await session.commit()

    # Публикуем в группу
    from sqlalchemy import select as _sel
    async with async_session() as session:
        from models import User as _User
        u = await session.execute(_sel(_User).where(_User.tg_id == user_id))
        user = u.scalar_one_or_none()
    name = f"@{user.username}" if user and user.username else (user.school_nick if user else str(user_id))
    penalty_str = f" 💰 Ставка: {penalty}" if penalty else ""

    from services.scheduler import _post_to_digest
    await _post_to_digest(
        call.bot,
        f"🏳️ <b>{name}</b> сдался в челлендже «{title}».{penalty_str}"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ К списку", callback_data=f"my_page:{page}")
    await call.message.edit_text(
        f"🏳️ Ты вышел из челленджа «{title}».\n"
        f"Результат зафиксирован как не выполнен.{penalty_str}",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )
    await call.answer("Сдача зафиксирована.")


# ─── Запрос завершения участия (participant, не автор) ──────

@router.callback_query(F.data.startswith("part_req_close:"))
async def cb_part_req_close(call: CallbackQuery) -> None:
    """Участник просит завершить своё участие досрочно (без штрафа, на усмотрение админа)."""
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])
    user_id = call.from_user.id

    async with async_session() as session:
        from models import ChallengeParticipant as _CP
        p_res = await session.execute(
            select(_CP).where(_CP.challenge_id == challenge_id, _CP.user_id == user_id)
        )
        part = p_res.scalar_one_or_none()
        if not part or part.result:
            await call.answer("Участие уже завершено.", show_alert=True)
            return
        ch_res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = ch_res.scalar_one_or_none()
        title = ch.title if ch else "Челлендж"
        if hasattr(part, "close_requested"):
            part.close_requested = True
            await session.commit()

    from sqlalchemy import select as _sel
    async with async_session() as session:
        from models import User as _User
        u = await session.execute(_sel(_User).where(_User.tg_id == user_id))
        user = u.scalar_one_or_none()
    author_nick = f"@{user.username}" if user and user.username else (user.school_nick if user else str(user_id))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Закрыть без штрафа",  callback_data=f"part_close_ok:{challenge_id}:{user_id}")
    kb.button(text="❌ Отказать",             callback_data=f"part_close_no:{challenge_id}:{user_id}")
    kb.adjust(2)
    await _notify_admins_challenge(
        call.bot,
        f"🏁 <b>Запрос на закрытие участия</b>\n\n"
        f"Челлендж: <b>{title}</b>\n"
        f"Участник: {author_nick}\n\n"
        f"Закрыть участие без штрафа?",
        kb.as_markup()
    )
    await call.answer("Запрос отправлен администратору.")


@router.callback_query(F.data.startswith("part_close_ok:"))
async def cb_part_close_ok(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    challenge_id, target_user_id = int(parts[1]), int(parts[2])

    async with async_session() as session:
        from models import ChallengeParticipant as _CP
        p_res = await session.execute(
            select(_CP).where(_CP.challenge_id == challenge_id, _CP.user_id == target_user_id)
        )
        part = p_res.scalar_one_or_none()
        if not part:
            await call.answer("Участник не найден.", show_alert=True)
            return
        part.result = "closed"
        ch_res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = ch_res.scalar_one_or_none()
        title = ch.title if ch else "Челлендж"
        await session.commit()

    try:
        await call.bot.send_message(
            target_user_id,
            f"✅ Твоё участие в челлендже <b>«{title}»</b> закрыто без штрафа администратором.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.message.edit_text(call.message.text + "\n\n✅ <b>Закрыто без штрафа.</b>", parse_mode="HTML")
    await call.answer("Участие закрыто.")


@router.callback_query(F.data.startswith("part_close_no:"))
async def cb_part_close_no(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    challenge_id, target_user_id = int(parts[1]), int(parts[2])

    try:
        await call.bot.send_message(
            target_user_id,
            "❌ Запрос на закрытие участия отклонён администратором.\nПродолжай бежать! 🏃",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.message.edit_text(call.message.text + "\n\n❌ <b>Отказано.</b>", parse_mode="HTML")
    await call.answer("Запрос отклонён.")


# ─── Запрос паузы участия (participant) ──────────────────────

@router.callback_query(F.data.startswith("part_req_pause:"))
async def cb_part_req_pause(call: CallbackQuery, state: FSMContext) -> None:
    """Участник просит паузу своего участия."""
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])
    await state.set_state(ChallengeRequestStates.enter_pause_reason)
    await state.update_data(challenge_id=challenge_id, page=page, is_participant=True)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="Без причины ➡️", callback_data="bot_pause_no_reason")
    kb.adjust(1)
    await call.message.edit_text(
        "⏸ <b>Запрос на паузу участия</b>\n\nУкажи причину (или нажми «Без причины»):",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )
    await call.answer()


# ─── Запрос завершения через бота (FSM) ─────────────────────

@router.callback_query(F.data.startswith("bot_req_close:"))
async def cb_bot_req_close_start(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])
    await state.set_state(ChallengeRequestStates.enter_close_reason)
    await state.update_data(challenge_id=challenge_id, page=page)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="Без причины ➡️", callback_data="bot_close_no_reason")
    kb.adjust(1)
    await call.message.edit_text(
        "🏁 <b>Запрос на завершение челленджа</b>\n\n"
        "Укажи причину (или нажми «Без причины»):",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "bot_close_no_reason", ChallengeRequestStates.enter_close_reason)
async def cb_bot_close_no_reason(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await _do_bot_request_close(call.message, call.bot, call.from_user.id,
                                 data["challenge_id"], data["page"], reason=None)
    await call.answer()


@router.message(ChallengeRequestStates.enter_close_reason)
async def step_bot_close_reason(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await _do_bot_request_close(message, message.bot, message.from_user.id,
                                 data["challenge_id"], data["page"], reason=message.text.strip())


async def _do_bot_request_close(obj, bot, user_id: int, challenge_id: int, page: int, reason) -> None:
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch or ch.user_id != user_id or not ch.is_active or ch.close_requested:
            await obj.answer("Невозможно отправить запрос.")
            return
        ch.close_requested = True
        title = ch.title
        if hasattr(ch, 'pause_reason'):
            ch.pause_reason = reason  # переиспользуем поле для причины закрытия
        await session.commit()

    from sqlalchemy import select as _sel
    async with async_session() as session:
        from models import User as _User
        u = await session.execute(_sel(_User).where(_User.tg_id == user_id))
        user = u.scalar_one_or_none()
    author_nick = f"@{user.username}" if user and user.username else (user.school_nick if user else str(user_id))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Разрешить завершение", callback_data=f"ch_close_ok:{challenge_id}")
    kb.button(text="❌ Отказать",             callback_data=f"ch_close_no:{challenge_id}")
    kb.adjust(2)

    reason_str = f"\nПричина: {reason}" if reason else ""
    text = (
        f"🏁 <b>Запрос на завершение челленджа</b>\n\n"
        f"<b>{title}</b>\n"
        f"Автор: {author_nick}"
        f"{reason_str}\n\n"
        f"Разрешить досрочное завершение?"
    )
    await _notify_admins_challenge(bot, text, kb.as_markup())
    await obj.answer(f"✅ Запрос на завершение «{title}» отправлен администратору.")


# ─── Запрос паузы через бота (FSM) ───────────────────────────

@router.callback_query(F.data.startswith("bot_req_pause:"))
async def cb_bot_req_pause_start(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    challenge_id, page = int(parts[1]), int(parts[2])
    await state.set_state(ChallengeRequestStates.enter_pause_reason)
    await state.update_data(challenge_id=challenge_id, page=page)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="Без причины ➡️", callback_data="bot_pause_no_reason")
    kb.adjust(1)
    await call.message.edit_text(
        "⏸ <b>Запрос на паузу челленджа</b>\n\n"
        "Укажи причину (или нажми «Без причины»):",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "bot_pause_no_reason", ChallengeRequestStates.enter_pause_reason)
async def cb_bot_pause_no_reason(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await _do_bot_request_pause(call.message, call.bot, call.from_user.id,
                                 data["challenge_id"], data["page"], reason=None)
    await call.answer()


@router.message(ChallengeRequestStates.enter_pause_reason)
async def step_bot_pause_reason(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("is_child"):
        await _do_child_request_pause(message, message.bot, message.from_user.id,
                                      data["challenge_id"], data["page"], reason=message.text.strip())
    else:
        await _do_bot_request_pause(message, message.bot, message.from_user.id,
                                    data["challenge_id"], data["page"], reason=message.text.strip())


async def _do_bot_request_pause(obj, bot, user_id: int, challenge_id: int, page: int, reason) -> None:
    from datetime import datetime as _dt
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch or ch.user_id != user_id or not ch.is_active or ch.pause_requested:
            await obj.answer("Невозможно отправить запрос.")
            return
        if ch.pause_until and ch.pause_until > _dt.now():
            await obj.answer("Челлендж уже на паузе.")
            return
        ch.pause_requested = True
        ch.pause_reason = reason
        title = ch.title
        await session.commit()

    from sqlalchemy import select as _sel
    async with async_session() as session:
        from models import User as _User
        u = await session.execute(_sel(_User).where(_User.tg_id == user_id))
        user = u.scalar_one_or_none()
    author_nick = f"@{user.username}" if user and user.username else (user.school_nick if user else str(user_id))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⏸ Одобрить паузу", callback_data=f"ch_pause_ok:{challenge_id}")
    kb.button(text="❌ Отказать",       callback_data=f"ch_pause_no:{challenge_id}")
    kb.adjust(2)

    reason_str = f"\nПричина: {reason}" if reason else ""
    text = (
        f"⏸ <b>Запрос на паузу челленджа</b>\n\n"
        f"<b>{title}</b>\n"
        f"Автор: {author_nick}"
        f"{reason_str}\n\n"
        f"Одобрить паузу?"
    )
    await _notify_admins_challenge(bot, text, kb.as_markup())
    await obj.answer(f"✅ Запрос на паузу «{title}» отправлен администратору.")


# ─── Запрос разморозки через бота ────────────────────────────

@router.callback_query(F.data.startswith("bot_req_unfreeze:"))
async def cb_bot_req_unfreeze(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    challenge_id = int(parts[1])

    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch or ch.user_id != call.from_user.id:
            await call.answer("Ошибка.", show_alert=True)
            return
        title = ch.title

    from sqlalchemy import select as _sel
    async with async_session() as session:
        from models import User as _User
        u = await session.execute(_sel(_User).where(_User.tg_id == call.from_user.id))
        user = u.scalar_one_or_none()
    author_nick = f"@{user.username}" if user and user.username else (user.school_nick if user else str(call.from_user.id))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="▶️ Разморозить", callback_data=f"ch_unfreeze_ok:{challenge_id}")
    kb.button(text="❌ Отказать",    callback_data=f"ch_unfreeze_no:{challenge_id}")
    kb.adjust(2)

    text = (
        f"▶️ <b>Запрос на разморозку челленджа</b>\n\n"
        f"<b>{title}</b>\n"
        f"Автор: {author_nick}\n\n"
        f"Разморозить челлендж?"
    )
    await _notify_admins_challenge(call.bot, text, kb.as_markup())
    await call.answer(f"✅ Запрос на разморозку «{title}» отправлен администратору.")


# ─── Одобрение / отказ паузы (admin callback) ────────────────

@router.callback_query(F.data.startswith("ch_pause_ok:"))
async def cb_pause_ok(callback: CallbackQuery) -> None:
    """Администратор одобрил паузу челленджа."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    challenge_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch:
            await callback.answer("Челлендж не найден.", show_alert=True)
            return
        if not ch.is_active:
            await callback.answer("Уже завершён.", show_alert=True)
            return

        from datetime import datetime as _dt
        ch.pause_until = _dt(9999, 12, 31)   # бессрочная пауза до разморозки
        ch.frozen_at = _dt.now()
        ch.pause_requested = False
        owner_id = ch.user_id
        title = ch.title
        await session.commit()

    # Уведомление автора
    try:
        await callback.bot.send_message(
            owner_id,
            f"⏸ Администратор поставил на паузу твой челлендж <b>«{title}»</b>.\n"
            f"Пробежки не будут засчитываться до разморозки. "
            f"Запроси разморозку в Mini App когда будешь готов.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Публикуем в болталку
    from services.scheduler import _post_to_digest
    await _post_to_digest(
        callback.bot,
        f"❄️ Челлендж <b>«{title}»</b> поставлен на паузу по согласованию с администратором.",
    )

    await callback.message.edit_text(
        callback.message.text + "\n\n⏸ <b>Пауза одобрена.</b>",
        parse_mode="HTML",
    )
    await callback.answer("Пауза установлена.")


@router.callback_query(F.data.startswith("ch_pause_no:"))
async def cb_pause_no(callback: CallbackQuery) -> None:
    """Администратор отказал в паузе."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    challenge_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch:
            await callback.answer("Челлендж не найден.", show_alert=True)
            return
        ch.pause_requested = False
        owner_id = ch.user_id
        title = ch.title
        await session.commit()

    try:
        await callback.bot.send_message(
            owner_id,
            f"❌ Запрос на паузу челленджа <b>«{title}»</b> отклонён.\nПродолжай бежать! 🏃",
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.message.edit_text(
        callback.message.text + "\n\n❌ <b>В паузе отказано.</b>",
        parse_mode="HTML",
    )
    await callback.answer("Запрос отклонён.")


# ─── Разморозка по запросу / вручную (admin callback) ────────

@router.callback_query(F.data.startswith("ch_unfreeze_ok:"))
async def cb_unfreeze_ok(callback: CallbackQuery) -> None:
    """Администратор разморозил челлендж."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    challenge_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch:
            await callback.answer("Челлендж не найден.", show_alert=True)
            return

        from datetime import datetime as _dt2
        if ch.frozen_at and ch.deadline:
            ch.deadline = ch.deadline + (_dt2.now() - ch.frozen_at)
        ch.pause_until = None
        ch.frozen_at = None
        owner_id = ch.user_id
        title = ch.title
        await session.commit()

    try:
        await callback.bot.send_message(
            owner_id,
            f"▶️ Твой челлендж <b>«{title}»</b> разморожен! Пробежки снова засчитываются. 🏃",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Публикуем в болталку
    from services.scheduler import _post_to_digest
    await _post_to_digest(
        callback.bot,
        f"▶️ Челлендж <b>«{title}»</b> возобновлён по согласованию с администратором.",
    )

    await callback.message.edit_text(
        callback.message.text + "\n\n▶️ <b>Разморожен.</b>",
        parse_mode="HTML",
    )
    await callback.answer("Челлендж разморожен.")


@router.callback_query(F.data.startswith("ch_unfreeze_no:"))
async def cb_unfreeze_no(callback: CallbackQuery) -> None:
    """Администратор отказал в разморозке."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    challenge_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ch = res.scalar_one_or_none()
        if not ch:
            await callback.answer("Челлендж не найден.", show_alert=True)
            return
        owner_id = ch.user_id
        title = ch.title

    try:
        await callback.bot.send_message(
            owner_id,
            f"❌ Запрос на разморозку челленджа <b>«{title}»</b> отклонён.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.message.edit_text(
        callback.message.text + "\n\n❌ <b>В разморозке отказано.</b>",
        parse_mode="HTML",
    )
    await callback.answer("Запрос отклонён.")

# ─────────────────────────────────────────────────────────────────────────────
# ДОЧЕРНИЕ ЧЕЛЛЕНДЖИ — кнопки участника (новая архитектура)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("child_surrender_ask:"))
async def cb_child_surrender_ask(call: CallbackQuery) -> None:
    """Участник хочет сдаться — дочерний челлендж."""
    parts = call.data.split(":")
    child_id, page = int(parts[1]), int(parts[2])
    import asyncio, time
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⏳ Подождите 10с...", callback_data="noop")
    kb.button(text="❌ Отмена", callback_data=f"my_open:{child_id}:{page}")
    kb.adjust(1)
    await call.message.edit_text(
        "🏳️ <b>Подтверди сдачу</b>\n\n"
        "Результат будет зафиксирован как <b>не выполнен</b>.\n"
        "Кнопка подтверждения появится через 10 секунд.",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )
    await call.answer()
    await asyncio.sleep(10)
    try:
        kb2 = InlineKeyboardBuilder()
        kb2.button(text="✅ Подтвердить сдачу",
                   callback_data=f"child_surrender_confirm:{child_id}:{page}")
        kb2.button(text="❌ Отмена", callback_data=f"my_open:{child_id}:{page}")
        kb2.adjust(1)
        await call.message.edit_reply_markup(reply_markup=kb2.as_markup())
    except Exception:
        pass


@router.callback_query(F.data.startswith("child_surrender_confirm:"))
async def cb_child_surrender_confirm(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    child_id, page = int(parts[1]), int(parts[2])
    user_id = call.from_user.id

    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(
            Challenge.id == child_id, Challenge.user_id == user_id,
            Challenge.parent_id.isnot(None),
        ))
        ch = ch_res.scalar_one_or_none()
        if not ch or ch.result:
            await call.answer("Участие уже завершено.", show_alert=True)
            return
        ch.is_active = False
        ch.result = "failed"
        title = ch.title
        penalty = ch.penalty
        await session.commit()

    # Имя пользователя
    async with async_session() as session:
        from models import User as _User
        u = await session.execute(select(_User).where(_User.tg_id == user_id))
        user = u.scalar_one_or_none()
    name = f"@{user.username}" if user and user.username else (user.school_nick if user else str(user_id))
    penalty_str = f" 💰 Ставка: {penalty}" if penalty else ""

    from services.scheduler import _post_to_digest
    await _post_to_digest(
        call.bot,
        f"🏳️ <b>{name}</b> сдался в челлендже «{title}».{penalty_str}"
    )

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ К списку", callback_data=f"my_page:{page}")
    await call.message.edit_text(
        f"🏳️ Ты вышел из челленджа «{title}».\n"
        f"Результат зафиксирован как не выполнен.{penalty_str}",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )
    await call.answer("Сдача зафиксирована.")


@router.callback_query(F.data.startswith("child_req_close:"))
async def cb_child_req_close(call: CallbackQuery) -> None:
    """Участник просит закрыть своё дочернее участие без штрафа."""
    parts = call.data.split(":")
    child_id, page = int(parts[1]), int(parts[2])
    user_id = call.from_user.id

    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(
            Challenge.id == child_id, Challenge.user_id == user_id,
            Challenge.parent_id.isnot(None),
        ))
        ch = ch_res.scalar_one_or_none()
        if not ch or ch.result:
            await call.answer("Участие уже завершено.", show_alert=True)
            return
        if ch.close_requested:
            await call.answer("Запрос уже отправлен.", show_alert=True)
            return
        ch.close_requested = True
        title = ch.title
        await session.commit()

    async with async_session() as session:
        from models import User as _User
        u = await session.execute(select(_User).where(_User.tg_id == user_id))
        user = u.scalar_one_or_none()
    author_nick = f"@{user.username}" if user and user.username else (user.school_nick if user else str(user_id))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Закрыть без штрафа",  callback_data=f"child_close_ok:{child_id}:{user_id}")
    kb.button(text="❌ Отказать",             callback_data=f"child_close_no:{child_id}:{user_id}")
    kb.adjust(2)
    await _notify_admins_challenge(
        call.bot,
        f"🏁 <b>Запрос на закрытие участия</b>\n\n"
        f"Челлендж: <b>{title}</b>\n"
        f"Участник: {author_nick}\n\n"
        f"Закрыть участие без штрафа?",
        kb.as_markup()
    )
    await call.answer("Запрос отправлен администратору.")


@router.callback_query(F.data.startswith("child_close_ok:"))
async def cb_child_close_ok(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    child_id, target_user_id = int(parts[1]), int(parts[2])
    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(Challenge.id == child_id))
        ch = ch_res.scalar_one_or_none()
        if not ch:
            await call.answer("Не найдено.", show_alert=True)
            return
        ch.is_active = False
        ch.close_requested = False
        ch.result = "closed"
        title = ch.title
        await session.commit()
    try:
        await call.bot.send_message(
            target_user_id,
            f"✅ Твоё участие в челлендже <b>«{title}»</b> закрыто без штрафа.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.message.edit_text(call.message.text + "\n\n✅ <b>Закрыто без штрафа.</b>", parse_mode="HTML")
    await call.answer("Участие закрыто.")


@router.callback_query(F.data.startswith("child_close_no:"))
async def cb_child_close_no(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    child_id, target_user_id = int(parts[1]), int(parts[2])
    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(Challenge.id == child_id))
        ch = ch_res.scalar_one_or_none()
        if ch:
            ch.close_requested = False
            await session.commit()
    try:
        await call.bot.send_message(
            target_user_id,
            "❌ Запрос на закрытие участия отклонён. Продолжай бежать! 🏃",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.message.edit_text(call.message.text + "\n\n❌ <b>Отказано.</b>", parse_mode="HTML")
    await call.answer("Запрос отклонён.")


@router.callback_query(F.data.startswith("child_req_pause:"))
async def cb_child_req_pause(call: CallbackQuery, state: FSMContext) -> None:
    """Участник просит паузу своего дочернего челленджа."""
    parts = call.data.split(":")
    child_id, page = int(parts[1]), int(parts[2])
    await state.set_state(ChallengeRequestStates.enter_pause_reason)
    await state.update_data(challenge_id=child_id, page=page, is_child=True)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="Без причины ➡️", callback_data="child_pause_no_reason")
    kb.adjust(1)
    await call.message.edit_text(
        "⏸ <b>Запрос на паузу участия</b>\n\nУкажи причину (или нажми «Без причины»):",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "child_pause_no_reason", ChallengeRequestStates.enter_pause_reason)
async def cb_child_pause_no_reason(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("is_child"):
        await call.answer()
        return
    await state.clear()
    await _do_child_request_pause(call.message, call.bot, call.from_user.id,
                                   data["challenge_id"], data["page"], reason=None)
    await call.answer()


async def _do_child_request_pause(obj, bot, user_id: int, child_id: int, page: int, reason) -> None:
    from datetime import datetime as _dt
    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(
            Challenge.id == child_id, Challenge.user_id == user_id,
            Challenge.parent_id.isnot(None),
        ))
        ch = ch_res.scalar_one_or_none()
        if not ch or not ch.is_active or ch.pause_requested:
            await obj.answer("Невозможно отправить запрос.")
            return
        if ch.pause_until and ch.pause_until > _dt.now():
            await obj.answer("Участие уже на паузе.")
            return
        ch.pause_requested = True
        ch.pause_reason = reason
        title = ch.title
        await session.commit()

    async with async_session() as session:
        from models import User as _User
        u = await session.execute(select(_User).where(_User.tg_id == user_id))
        user = u.scalar_one_or_none()
    author_nick = f"@{user.username}" if user and user.username else (user.school_nick if user else str(user_id))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⏸ Одобрить паузу", callback_data=f"child_pause_ok:{child_id}:{user_id}")
    kb.button(text="❌ Отказать",       callback_data=f"child_pause_no:{child_id}:{user_id}")
    kb.adjust(2)
    reason_str = f"\nПричина: {reason}" if reason else ""
    await _notify_admins_challenge(
        bot,
        f"⏸ <b>Запрос на паузу участия</b>\n\n"
        f"Челлендж: <b>{title}</b>\n"
        f"Участник: {author_nick}"
        f"{reason_str}\n\nОдобрить паузу участника?",
        kb.as_markup()
    )
    await obj.answer(f"✅ Запрос на паузу «{title}» отправлен администратору.")


@router.callback_query(F.data.startswith("child_pause_ok:"))
async def cb_child_pause_ok(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    child_id, target_user_id = int(parts[1]), int(parts[2])
    from datetime import datetime as _dt
    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(Challenge.id == child_id))
        ch = ch_res.scalar_one_or_none()
        if not ch:
            await call.answer("Не найдено.", show_alert=True)
            return
        ch.pause_until = _dt(9999, 12, 31)
        ch.frozen_at = _dt.now()
        ch.pause_requested = False
        title = ch.title
        await session.commit()
    try:
        await call.bot.send_message(
            target_user_id,
            f"⏸ Твоё участие в челлендже <b>«{title}»</b> поставлено на паузу.\n"
            f"Запроси разморозку когда будешь готов.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.message.edit_text(call.message.text + "\n\n⏸ <b>Пауза одобрена.</b>", parse_mode="HTML")
    await call.answer("Пауза установлена.")


@router.callback_query(F.data.startswith("child_pause_no:"))
async def cb_child_pause_no(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    parts = call.data.split(":")
    child_id, target_user_id = int(parts[1]), int(parts[2])
    async with async_session() as session:
        ch_res = await session.execute(select(Challenge).where(Challenge.id == child_id))
        ch = ch_res.scalar_one_or_none()
        if ch:
            ch.pause_requested = False
            await session.commit()
    try:
        await call.bot.send_message(
            target_user_id,
            "❌ Запрос на паузу участия отклонён. Продолжай бежать! 🏃",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.message.edit_text(call.message.text + "\n\n❌ <b>В паузе отказано.</b>", parse_mode="HTML")
    await call.answer("Запрос отклонён.")
