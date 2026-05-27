"""
handlers/tournaments.py — обработчики турниров.

Точки входа (создание, только админ):
  /tournament_new          — начать FSM
  Кнопка «🏆 Создать турнир» — то же самое

Точки входа (участники):
  /tournament              — показать активный турнир
  Callback tour_join:<id>  — принять вызов
  Callback tour_table:<id> — таблица результатов

Отмена FSM:
  Reply-кнопка «❌ Отмена» или /cancel
  Inline-кнопка tour_cancel
"""

from __future__ import annotations

import logging

from aiogram.enums import ChatType
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from keyboards import get_cancel_kb, get_tournament_kb
from services.tournaments import (
    TOUR_TYPE_NAMES,
    create_tournament,
    get_active_tournament,
    get_leaderboard,
    get_tournament,
    is_participant,
    join_tournament,
)

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ─────────────────────────────────────────────────────────────
# Inline-клавиатуры
# ─────────────────────────────────────────────────────────────

def _tour_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in TOUR_TYPE_NAMES.items():
        builder.button(text=label, callback_data=f"tour_type:{key}")
    builder.button(text="❌ Отменить", callback_data="tour_cancel")
    builder.adjust(1)
    return builder.as_markup()


def _tour_duration_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for days in (3, 5, 7, 14):
        builder.button(text=f"{days} дней", callback_data=f"tour_dur:{days}")
    builder.button(text="❌ Отменить", callback_data="tour_cancel")
    builder.adjust(2)
    return builder.as_markup()


def _tour_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Создать турнир", callback_data="tour_confirm")
    builder.button(text="❌ Отменить",       callback_data="tour_cancel")
    builder.adjust(1)
    return builder.as_markup()


def _tour_info_kb(tournament_id: int, joined: bool = False) -> InlineKeyboardMarkup:
    """Кнопка участия всегда активна — персональный статус через cb.answer."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Принять вызов", callback_data=f"tour_join:{tournament_id}")
    builder.button(text="📊 Таблица", callback_data=f"tour_table:{tournament_id}")
    builder.adjust(1)
    return builder.as_markup()


def _fmt_score(score: float, tour_type: str) -> str:
    if tour_type in ("km", "team_km"):
        return f"{score:.1f} км"
    if tour_type == "minutes":
        return f"{int(score)} мин"
    if tour_type == "days":
        return f"{int(score)} дн"
    return str(score)


# ─────────────────────────────────────────────────────────────
# FSM состояния
# ─────────────────────────────────────────────────────────────

class TourCreate(StatesGroup):
    title    = State()   # единственный текстовый шаг
    t_type   = State()   # только inline
    duration = State()   # только inline
    confirm  = State()   # только inline


# ─────────────────────────────────────────────────────────────
# Отмена (перехватываем раньше всех шагов FSM)
# ─────────────────────────────────────────────────────────────

_CANCEL_TEXTS = {"❌ Отмена", "🚫 Отмена", "Отмена", "/cancel"}


@router.message(StateFilter(TourCreate), Command("cancel"))
@router.message(StateFilter(TourCreate), F.text.in_(_CANCEL_TEXTS))
async def tour_cancel_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    from keyboards import get_admin_main_kb
    await message.answer("❌ Создание турнира отменено.", reply_markup=get_admin_main_kb())


@router.callback_query(StateFilter(TourCreate), F.data == "tour_cancel")
async def tour_cancel_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ Создание турнира отменено.")
    await cb.answer()


# ─────────────────────────────────────────────────────────────
# Шаг 0 — старт FSM
# ─────────────────────────────────────────────────────────────

@router.message(Command("tournament_new"))
@router.message(F.text == "🏆 Создать турнир")
async def admin_tournament_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Только для администраторов.")
        return

    await state.clear()  # сбрасываем незавершённое
    await state.set_state(TourCreate.title)

    await message.answer(
        "🏆 <b>Создание турнира</b>\n\n"
        "Введи название (3–80 символов):\n"
        "<i>Для отмены — кнопка «❌ Отмена» или /cancel</i>",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────────────────────────
# Шаг 1 — название (текст)
# ─────────────────────────────────────────────────────────────

@router.message(TourCreate.title)
async def tour_step_title(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, введи текстовое название:")
        return

    title = message.text.strip()
    if len(title) < 3:
        await message.answer("⚠️ Слишком короткое название (минимум 3 символа). Попробуй ещё:")
        return
    if len(title) > 80:
        await message.answer("⚠️ Слишком длинное название (максимум 80 символов). Попробуй ещё:")
        return

    await state.update_data(title=title)
    await state.set_state(TourCreate.t_type)

    # Убираем Reply-клавиатуру перед Inline
    await message.answer(
        f"✅ Название: <b>{title}</b>\n\nВыбери тип турнира:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("👇", reply_markup=_tour_type_kb())


# ─────────────────────────────────────────────────────────────
# Шаг 2 — тип (только inline)
# ─────────────────────────────────────────────────────────────

@router.message(TourCreate.t_type)
async def tour_step_type_guard(message: Message) -> None:
    await message.answer("👆 Выбери тип кнопкой выше.")


@router.callback_query(TourCreate.t_type, F.data.startswith("tour_type:"))
async def tour_step_type(cb: CallbackQuery, state: FSMContext) -> None:
    t_type = cb.data.split(":")[1]
    if t_type not in TOUR_TYPE_NAMES:
        await cb.answer("Неизвестный тип.", show_alert=True)
        return

    label = TOUR_TYPE_NAMES[t_type]
    await state.update_data(t_type=t_type)
    await state.set_state(TourCreate.duration)

    await cb.message.edit_text(
        f"✅ Тип: <b>{label}</b>\n\nВыбери длительность турнира:",
        reply_markup=_tour_duration_kb(),
    )
    await cb.answer()


# ─────────────────────────────────────────────────────────────
# Шаг 3 — длительность (только inline)
# ─────────────────────────────────────────────────────────────

@router.message(TourCreate.duration)
async def tour_step_duration_guard(message: Message) -> None:
    await message.answer("👆 Выбери длительность кнопкой выше.")


@router.callback_query(TourCreate.duration, F.data.startswith("tour_dur:"))
async def tour_step_duration(cb: CallbackQuery, state: FSMContext) -> None:
    days = int(cb.data.split(":")[1])
    await state.update_data(duration=days)

    data = await state.get_data()
    type_label = TOUR_TYPE_NAMES.get(data["t_type"], data["t_type"])

    await state.set_state(TourCreate.confirm)
    await cb.message.edit_text(
        "📋 <b>Проверь данные:</b>\n\n"
        f"Название:     <b>{data['title']}</b>\n"
        f"Тип:          <b>{type_label}</b>\n"
        f"Длительность: <b>{days} дней</b>\n\n"
        "Всё верно?",
        reply_markup=_tour_confirm_kb(),
    )
    await cb.answer()


# ─────────────────────────────────────────────────────────────
# Шаг 4 — подтверждение (только inline)
# ─────────────────────────────────────────────────────────────

@router.message(TourCreate.confirm)
async def tour_step_confirm_guard(message: Message) -> None:
    await message.answer("👆 Нажми кнопку «✅ Создать турнир» или «❌ Отменить».")


@router.callback_query(TourCreate.confirm, F.data == "tour_confirm")
async def tour_step_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()

    # Защита от потери state (перезапуск бота во время FSM)
    if not all(k in data for k in ("title", "t_type", "duration")):
        await state.clear()
        await cb.message.edit_text(
            "⚠️ Данные формы потерялись (бот перезапускался?).\n"
            "Начни заново: /tournament_new"
        )
        await cb.answer()
        return

    await state.clear()

    try:
        tournament = await create_tournament(
            title=data["title"],
            tournament_type=data["t_type"],
            created_by=cb.from_user.id,
            duration_days=data["duration"],
        )
    except Exception as e:
        log.error(f"Ошибка создания турнира: {e}", exc_info=True)
        await cb.message.edit_text(
            "❌ Ошибка при создании турнира. Попробуй ещё раз (/tournament_new)."
        )
        await cb.answer()
        return

    type_label = TOUR_TYPE_NAMES.get(tournament.tournament_type, tournament.tournament_type)
    end_str    = tournament.end_date.strftime("%d.%m.%Y %H:%M")

    await cb.message.edit_text(
        f"✅ Турнир <b>{tournament.title}</b> создан!\n"
        f"Тип: {type_label}\n"
        f"Завершается: {end_str}"
    )
    # Возвращаем клавиатуру после завершения FSM
    from keyboards import get_admin_main_kb
    await cb.message.answer("✅ Готово!", reply_markup=get_admin_main_kb())
    await cb.answer("Турнир создан! 🏆")

    # Анонс в группу
    if config.GROUP_ID:
        try:
            await cb.message.bot.send_message(
                config.GROUP_ID,
                f"🏆 <b>НОВЫЙ ТУРНИР: {tournament.title}</b>\n\n"
                f"Тип: {type_label}\n"
                f"Завершается: {end_str}\n\n"
                "Нажми кнопку и прими вызов! 💪",
                message_thread_id=config.EVENTS_THREAD_ID,
                reply_markup=get_tournament_kb(tournament.id, joined=False),
            )
        except Exception as e:
            log.warning(f"Анонс турнира в группу не отправлен: {e}")


# ─────────────────────────────────────────────────────────────
# /tournament — просмотр активного
# ─────────────────────────────────────────────────────────────

@router.message(Command("tournament"))
async def cmd_tournament(message: Message) -> None:
    tournament = await get_active_tournament()
    if not tournament:
        await message.answer("🏆 Сейчас нет активных турниров.")
        return

    user_id    = message.from_user.id
    joined     = await is_participant(tournament.id, user_id)
    type_label = TOUR_TYPE_NAMES.get(tournament.tournament_type, tournament.tournament_type)
    end_str    = tournament.end_date.strftime("%d.%m.%Y %H:%M")

    text = (
        f"🏆 <b>{tournament.title}</b>\n"
        f"Тип: {type_label}\n"
        f"Завершается: {end_str}\n"
        f"Участников: {len(tournament.participants)}"
    )
    if not joined:
        text += "\n\n👇 Нажми <b>«Принять вызов»</b>, чтобы участвовать!"

    await message.answer(text, reply_markup=_tour_info_kb(tournament.id, joined))


# ─────────────────────────────────────────────────────────────
# Callback: регистрация участника
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tour_join:"))
async def cb_join_tournament(cb: CallbackQuery) -> None:
    tournament_id = int(cb.data.split(":")[1])
    user_id       = cb.from_user.id

    result = await join_tournament(tournament_id, user_id)

    if result.get("error") == "already_joined":
        await cb.answer("Ты уже участвуешь! 🏆")
        return
    if result.get("error") == "not_active":
        await cb.answer("Этот турнир уже завершён.", show_alert=True)
        return
    if result.get("error"):
        await cb.answer("Что-то пошло не так, попробуй позже.", show_alert=True)
        return

    # Не редактируем групповое сообщение — кнопка общая для всех
    # Каждый видит свой статус через personal answer
    await cb.answer("🏆 Ты в деле! Удачи!", show_alert=True)

    # Уведомление в личку
    tournament = await get_tournament(tournament_id)
    if tournament:
        type_label = TOUR_TYPE_NAMES.get(tournament.tournament_type, tournament.tournament_type)
        try:
            await cb.message.bot.send_message(
                user_id,
                f"✅ Ты зарегистрирован в турнире <b>{tournament.title}</b>!\n"
                f"Тип: {type_label}\n"
                "Все одобренные тренировки автоматически войдут в зачёт 🏃",
            )
        except Exception:
            pass  # бот заблокирован пользователем


# ─────────────────────────────────────────────────────────────
# Callback: таблица результатов
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tour_table:"))
async def cb_tournament_table(cb: CallbackQuery) -> None:
    tournament_id = int(cb.data.split(":")[1])
    tournament    = await get_tournament(tournament_id)

    if not tournament:
        await cb.answer("Турнир не найден.", show_alert=True)
        return

    rows = await get_leaderboard(tournament_id, limit=10)
    if not rows:
        await cb.answer("Пока никто не участвует.", show_alert=True)
        return

    medals = ["🥇", "🥈", "🥉"]
    lines  = [f"🏆 <b>{tournament.title}</b> — таблица\n"]
    for row in rows:
        pos       = row["position"]
        medal     = medals[pos - 1] if pos <= 3 else f"{pos}."
        user      = row["user"]
        name      = (f"@{user.username}" if user.username else user.school_nick) if user else f"id{row['user_tg_id']}"
        score_str = _fmt_score(row["score"], tournament.tournament_type)
        lines.append(f"{medal} {name} — {score_str}")

    await cb.message.answer("\n".join(lines))
    await cb.answer()