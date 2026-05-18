"""
handlers/challenges.py — создание челленджей и присоединение к чужим.

FSM создания подстраивается под выбранный тип челленджа.
"""

import logging
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from keyboards import (
    get_main_kb, get_cancel_kb, get_challenge_type_kb, get_join_challenge_kb,
)
from services import challenges as ch_service
from services import users as users_service

router = Router()
log = logging.getLogger(__name__)


# ─────────────────────────────────────────
# FSM создания челленджа
# ─────────────────────────────────────────

class ChallengeCreate(StatesGroup):
    title       = State()  # Название
    ch_type     = State()  # Тип
    cond_km     = State()  # Мин. км за пробежку (weekly_runs)
    cond_min    = State()  # Мин. минут за пробежку (weekly_runs)
    goal_runs   = State()  # Раз в неделю (weekly_runs)
    goal_value  = State()  # Суммарно км (спринты, race)
    goal_time   = State()  # Лимит времени (race)
    start_date  = State()  # Дата начала
    end_date    = State()  # Дата окончания (опционально)
    penalty     = State()  # Цена слова


# Маппинг текста кнопки → тип
TYPE_MAP = {
    "📜 Регулярный (X раз в неделю)":          "weekly_runs",
    "🎯 Дневной спринт (N км за день)":        "daily_km",
    "📅 Недельный спринт (N км за неделю)":    "weekly_km",
    "📆 Месячный спринт (N км за месяц)":      "monthly_km",
    "🏃 Разовый забег (N км за время)":        "race",
    "♾️ Открытый челлендж (без даты)":          "open",
}


def _parse_float(text: str) -> float | None:
    """Парсит число (запятая или точка)."""
    try:
        return float(text.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _parse_date(text: str) -> datetime | None:
    """Парсит дату ДД.ММ.ГГГГ."""
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y")
    except (ValueError, AttributeError):
        return None


async def _cancel(message: types.Message, state: FSMContext):
    """Отмена создания."""
    await state.clear()
    await message.answer("Создание челленджа отменено.", reply_markup=get_main_kb())


# ─────────────────────────────────────────
# Старт создания
# ─────────────────────────────────────────

@router.message(F.text == "🏃 Создать челлендж")
@router.message(Command("create_challenge"))
async def start_create(message: types.Message, state: FSMContext):
    """Начало FSM создания челленджа."""
    # Проверяем регистрацию
    profile = await users_service.get_profile(message.from_user.id)
    if not profile:
        return await message.answer(
            "Сначала пройди регистрацию: /start",
            reply_markup=get_main_kb(),
        )

    await state.set_state(ChallengeCreate.title)
    await message.answer(
        "📝 <b>Создание челленджа</b>\n\n"
        "Введи название:\n"
        "<i>Например: «Вернуться к бегу» или «Полумарафон осенью»</i>",
        reply_markup=get_cancel_kb(),
    )


@router.message(ChallengeCreate.title)
async def ch_title(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    title = message.text.strip()
    if len(title) < 3 or len(title) > 80:
        return await message.answer(
            "Название должно быть от 3 до 80 символов. Попробуй ещё раз:",
            reply_markup=get_cancel_kb(),
        )

    await state.update_data(title=title)
    await state.set_state(ChallengeCreate.ch_type)
    await message.answer(
        "Выбери <b>тип</b> челленджа:",
        reply_markup=get_challenge_type_kb(),
    )


# ─────────────────────────────────────────
# Выбор типа → ветвление
# ─────────────────────────────────────────

@router.message(ChallengeCreate.ch_type)
async def ch_type(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    ch_type_code = TYPE_MAP.get(message.text)
    if not ch_type_code:
        return await message.answer(
            "Выбери тип кнопкой из списка ниже 👇",
            reply_markup=get_challenge_type_kb(),
        )

    await state.update_data(ch_type=ch_type_code)

    if ch_type_code == "weekly_runs":
        # Регулярный — спрашиваем условия зачёта пробежки
        await state.set_state(ChallengeCreate.cond_km)
        await message.answer(
            "📜 <b>Регулярный челлендж</b>\n\n"
            "Условие зачёта одной пробежки.\n"
            "Сначала — <b>минимум километров</b> за пробежку.\n"
            "<i>Введи число (например: 3) или «-» если километраж не важен</i>",
            reply_markup=get_cancel_kb(),
        )
    elif ch_type_code in ("daily_km", "weekly_km", "monthly_km"):
        # Спринты — спрашиваем суммарную цель
        period = {"daily_km": "день", "weekly_km": "неделю", "monthly_km": "месяц"}[ch_type_code]
        await state.set_state(ChallengeCreate.goal_value)
        await message.answer(
            f"🎯 <b>Спринт</b>\n\n"
            f"Сколько километров суммарно нужно набегать за {period}?\n"
            f"<i>Например: 50</i>",
            reply_markup=get_cancel_kb(),
        )
    elif ch_type_code == "race":
        # Разовый забег — дистанция, потом время
        await state.set_state(ChallengeCreate.goal_value)
        await message.answer(
            "🏃 <b>Разовый забег</b>\n\n"
            "Какую дистанцию нужно пробежать (км)?\n"
            "<i>Например: 21.1 для полумарафона</i>",
            reply_markup=get_cancel_kb(),
        )
    elif ch_type_code == "open":
        # Открытый — сразу к цене слова
        await state.set_state(ChallengeCreate.penalty)
        await message.answer(
            "♾️ <b>Открытый челлендж</b>\n\n"
            "Без дедлайна — закроешь вручную когда выполнишь.\n\n"
            "💰 Введи «цену слова» — что будет если не справишься?\n"
            "<i>Например: «Куплю всем пиццу» или «-» чтобы пропустить</i>",
            reply_markup=get_cancel_kb(),
        )


# ─────────────────────────────────────────
# Регулярный: условие км
# ─────────────────────────────────────────

@router.message(ChallengeCreate.cond_km)
async def ch_cond_km(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    if message.text.strip() == "-":
        min_km = 0.0
    else:
        min_km = _parse_float(message.text)
        if min_km is None or min_km < 0:
            return await message.answer(
                "Введи число (например: 3) или «-»:",
                reply_markup=get_cancel_kb(),
            )

    await state.update_data(min_per_run=min_km)
    await state.set_state(ChallengeCreate.cond_min)
    await message.answer(
        "Теперь — <b>минимум минут</b> активности за пробежку.\n"
        "<i>Введи число (например: 20) или «-» если время не важно</i>\n\n"
        "ℹ️ Если задашь оба условия — пробежка засчитается при выполнении "
        "<b>любого</b> из них.",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# Регулярный: условие минут
# ─────────────────────────────────────────

@router.message(ChallengeCreate.cond_min)
async def ch_cond_min(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    if message.text.strip() == "-":
        min_minutes = 0
    else:
        val = _parse_float(message.text)
        if val is None or val < 0:
            return await message.answer(
                "Введи число (например: 20) или «-»:",
                reply_markup=get_cancel_kb(),
            )
        min_minutes = int(val)

    data = await state.get_data()
    # Хотя бы одно условие должно быть задано
    if data.get("min_per_run", 0) == 0 and min_minutes == 0:
        return await message.answer(
            "Нужно задать хотя бы одно условие — километры или минуты.\n"
            "Введи минимум минут:",
            reply_markup=get_cancel_kb(),
        )

    await state.update_data(min_minutes_per_run=min_minutes)
    await state.set_state(ChallengeCreate.goal_runs)
    await message.answer(
        "Сколько <b>пробежек в неделю</b> нужно делать?\n"
        "<i>Например: 3</i>",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# Регулярный: пробежек в неделю
# ─────────────────────────────────────────

@router.message(ChallengeCreate.goal_runs)
async def ch_goal_runs(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    val = _parse_float(message.text)
    if val is None or val < 1 or val > 21:
        return await message.answer(
            "Введи число от 1 до 21:",
            reply_markup=get_cancel_kb(),
        )

    await state.update_data(goal_runs=int(val))
    await state.set_state(ChallengeCreate.start_date)
    await message.answer(
        "Когда <b>стартуем</b>?\n"
        "<i>Введи дату ДД.ММ.ГГГГ или «-» чтобы начать сегодня</i>",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# Спринты / забег: цель в км
# ─────────────────────────────────────────

@router.message(ChallengeCreate.goal_value)
async def ch_goal_value(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    val = _parse_float(message.text)
    if val is None or val <= 0:
        return await message.answer(
            "Введи положительное число (например: 50):",
            reply_markup=get_cancel_kb(),
        )

    await state.update_data(goal_value=val)
    data = await state.get_data()

    if data["ch_type"] == "race":
        # Для забега — спрашиваем лимит времени
        await state.set_state(ChallengeCreate.goal_time)
        await message.answer(
            "За какое <b>время</b> нужно уложиться (минут)?\n"
            "<i>Например: 120 для полумарафона за 2 часа.\n"
            "Или «-» если без ограничения по времени</i>",
            reply_markup=get_cancel_kb(),
        )
    else:
        # Спринты — переходим к дате старта
        await state.set_state(ChallengeCreate.start_date)
        await message.answer(
            "Когда <b>стартуем</b>?\n"
            "<i>Введи дату ДД.ММ.ГГГГ или «-» чтобы начать сегодня</i>",
            reply_markup=get_cancel_kb(),
        )


# ─────────────────────────────────────────
# Забег: лимит времени
# ─────────────────────────────────────────

@router.message(ChallengeCreate.goal_time)
async def ch_goal_time(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    if message.text.strip() == "-":
        goal_time = None
    else:
        val = _parse_float(message.text)
        if val is None or val <= 0:
            return await message.answer(
                "Введи число минут (например: 120) или «-»:",
                reply_markup=get_cancel_kb(),
            )
        goal_time = int(val)

    await state.update_data(goal_time=goal_time)
    await state.set_state(ChallengeCreate.start_date)
    await message.answer(
        "Когда <b>стартуем</b>?\n"
        "<i>Введи дату ДД.ММ.ГГГГ или «-» чтобы начать сегодня</i>",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# Дата начала
# ─────────────────────────────────────────

@router.message(ChallengeCreate.start_date)
async def ch_start_date(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    if message.text.strip() == "-":
        start = datetime.now()
    else:
        start = _parse_date(message.text)
        if start is None:
            return await message.answer(
                "Неверный формат. Введи дату как ДД.ММ.ГГГГ (например: 01.06.2026) или «-»:",
                reply_markup=get_cancel_kb(),
            )

    await state.update_data(start_date=start.isoformat())
    await state.set_state(ChallengeCreate.end_date)
    await message.answer(
        "Когда <b>финиш</b>?\n"
        "<i>Введи дату ДД.ММ.ГГГГ или «-» чтобы челлендж был бессрочным</i>",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# Дата окончания
# ─────────────────────────────────────────

@router.message(ChallengeCreate.end_date)
async def ch_end_date(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    if message.text.strip() == "-":
        end = None
    else:
        end = _parse_date(message.text)
        if end is None:
            return await message.answer(
                "Неверный формат. Введи дату как ДД.ММ.ГГГГ или «-»:",
                reply_markup=get_cancel_kb(),
            )
        # Проверяем что финиш позже старта
        data = await state.get_data()
        start = datetime.fromisoformat(data["start_date"])
        if end <= start:
            return await message.answer(
                "Дата финиша должна быть позже даты старта. Попробуй ещё раз:",
                reply_markup=get_cancel_kb(),
            )

    await state.update_data(end_date=end.isoformat() if end else None)
    await state.set_state(ChallengeCreate.penalty)
    await message.answer(
        "💰 Введи «цену слова» — что будет если не справишься?\n"
        "<i>Например: «Куплю всем пиццу» или «-» чтобы пропустить</i>",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# Цена слова → создание
# ─────────────────────────────────────────

@router.message(ChallengeCreate.penalty)
async def ch_penalty(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await _cancel(message, state)

    penalty = None if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()

    # Готовим параметры
    start_date = datetime.fromisoformat(data["start_date"]) if data.get("start_date") else datetime.now()
    end_date = datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None

    challenge = await ch_service.create_challenge(
        user_id=message.from_user.id,
        title=data["title"],
        ch_type=data["ch_type"],
        min_per_run=data.get("min_per_run", 0.0),
        min_minutes_per_run=data.get("min_minutes_per_run", 0),
        goal_runs=data.get("goal_runs", 0),
        goal_value=data.get("goal_value", 0.0),
        goal_time=data.get("goal_time"),
        penalty=penalty,
        is_public=True,
        started_at=start_date,
        deadline=end_date,
    )

    await state.clear()

    # Формируем сводку
    lines = [
        "✅ <b>Челлендж создан!</b>\n",
        f"{ch_service.get_type_name(challenge.ch_type)}",
        f"<b>{challenge.title}</b>\n",
    ]

    if challenge.ch_type == "weekly_runs":
        cond = []
        if challenge.min_per_run > 0:
            cond.append(f"от {challenge.min_per_run:g} км")
        if challenge.min_minutes_per_run > 0:
            cond.append(f"от {challenge.min_minutes_per_run} мин")
        lines.append(f"📊 {challenge.goal_runs} пробежек в неделю")
        lines.append(f"   зачёт пробежки: {' или '.join(cond)}")
    elif challenge.ch_type in ("daily_km", "weekly_km", "monthly_km"):
        period = {"daily_km": "день", "weekly_km": "неделю", "monthly_km": "месяц"}[challenge.ch_type]
        lines.append(f"📊 Цель: {challenge.goal_value:g} км за {period}")
    elif challenge.ch_type == "race":
        time_str = f" за {challenge.goal_time} мин" if challenge.goal_time else ""
        lines.append(f"📊 Цель: {challenge.goal_value:g} км{time_str}")
    elif challenge.ch_type == "open":
        lines.append("📊 Без дедлайна — закроешь когда выполнишь")

    if challenge.deadline:
        lines.append(f"📅 До {challenge.deadline.strftime('%d.%m.%Y')}")
    elif challenge.ch_type != "open":
        lines.append("📅 Бессрочный")

    if challenge.penalty:
        lines.append(f"💰 Цена слова: {challenge.penalty}")

    lines.append("\n🌍 Челлендж публичный — другие могут присоединиться!")

    await message.answer("\n".join(lines), reply_markup=get_main_kb())


# ─────────────────────────────────────────
# Список публичных челленджей для присоединения
# ─────────────────────────────────────────

@router.message(Command("public_challenges"))
async def list_public(message: types.Message):
    """Показать публичные челленджи для присоединения."""
    challenges = await ch_service.get_public_challenges(
        exclude_user=message.from_user.id, limit=15
    )

    if not challenges:
        return await message.answer(
            "Сейчас нет публичных челленджей для присоединения.\n"
            "Создай свой — и другие смогут присоединиться к тебе! 🏃",
            reply_markup=get_main_kb(),
        )

    await message.answer(f"🌍 <b>Публичные челленджи</b> ({len(challenges)})")

    for ch in challenges:
        count = await ch_service.get_participants_count(ch.id)
        owner = await users_service.get_profile(ch.user_id)
        owner_nick = owner['user'].school_nick if owner else "—"

        lines = [
            f"{ch_service.get_type_name(ch.ch_type)}",
            f"<b>{ch.title}</b>",
            f"👤 Автор: {owner_nick}",
        ]
        if ch.ch_type == "weekly_runs":
            lines.append(f"📊 {ch.goal_runs} пробежек/неделю")
        elif ch.goal_value > 0:
            lines.append(f"📊 Цель: {ch.goal_value:g} км")
        if count > 0:
            lines.append(f"🤝 Присоединились: {count}")

        await message.answer(
            "\n".join(lines),
            reply_markup=get_join_challenge_kb(ch.id),
        )


# ─────────────────────────────────────────
# Присоединение к челленджу
# ─────────────────────────────────────────

@router.callback_query(F.data.startswith("join_ch:"))
async def cb_join_challenge(callback: types.CallbackQuery):
    """Обработка кнопки присоединения."""
    challenge_id = int(callback.data.split(":")[1])

    # Проверяем регистрацию
    profile = await users_service.get_profile(callback.from_user.id)
    if not profile:
        return await callback.answer("Сначала пройди регистрацию: /start", show_alert=True)

    result = await ch_service.join_challenge(challenge_id, callback.from_user.id)

    if result['ok']:
        await callback.answer(f"✅ {result['reason']}", show_alert=True)
    else:
        await callback.answer(result['reason'], show_alert=True)