from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ---------------------------------------------------------------------------
# Главное меню
# ---------------------------------------------------------------------------

def get_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏃 Создать челлендж")],
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📊 Таблица лидеров")],
            [KeyboardButton(text="📅 Мероприятия"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="IT БЕГОТНЯ 21",
    )


def get_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Создание челленджа
# ---------------------------------------------------------------------------

def get_challenge_type_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📜 Регулярность (X раз по Y км/нед)")],
            [KeyboardButton(text="🎯 Разовая цель (суммарно N км)")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Peer Review: голосование за отчёт
#
# Формат callback_data:
#   "vote:{report_id}"        — голос участника
#   "adm_approve:{report_id}" — мгновенное одобрение админом
# ---------------------------------------------------------------------------

def get_report_kb(report_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Засчитать", callback_data=f"vote:{report_id}"),
        InlineKeyboardButton(text="❌ Фейк", callback_data=f"vote_no:{report_id}"),
    )
    builder.row(
        InlineKeyboardButton(
            text="👑 Админ: одобрить мгновенно",
            callback_data=f"adm_approve:{report_id}",
        )
    )
    return builder.as_markup()


def get_report_approved_kb() -> InlineKeyboardMarkup:
    """Заглушка после принятия отчёта — кнопки уже нажимать не нужно."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Отчёт принят", callback_data="noop"))
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Мероприятия
# ---------------------------------------------------------------------------

def get_event_kb(event_id: int, joined: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if joined:
        builder.row(InlineKeyboardButton(text="✅ Ты участвуешь", callback_data="noop"))
    else:
        builder.row(
            InlineKeyboardButton(text="🏃 Участвую!", callback_data=f"event_join:{event_id}")
        )
    return builder.as_markup()