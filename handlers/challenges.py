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
)
from services.challenges import create_challenge, get_type_name

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
    await message.answer("Создание челленджа отменено.", reply_markup=get_main_kb())


# ─── Шаг 1: выбор типа (callback) ───

@router.callback_query(F.data.startswith("ch_type:"), ChallengeCreate.choose_type)
async def cb_choose_type(call: CallbackQuery, state: FSMContext) -> None:
    ch_type = call.data.split(":", 1)[1]

    if ch_type == "cancel":
        await state.clear()
        await call.message.edit_text("Создание челленджа отменено.")
        await call.message.answer("Главное меню:", reply_markup=get_main_kb())
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
        await call.message.answer("Главное меню:", reply_markup=get_main_kb())
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