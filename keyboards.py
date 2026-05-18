"""keyboards.py — все кнопки для бота."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ─── Главное меню ───
def get_main_kb() -> ReplyKeyboardMarkup:
    """Главное меню для зарегистрированных пользователей."""
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
    """Кнопка отмены."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


# ─── FSM регистрации ───
def get_registration_start_kb() -> ReplyKeyboardMarkup:
    """Первый вопрос: уже регистрировался?"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да, я здесь уже")],
            [KeyboardButton(text="❌ Нет, первый раз")],
        ],
        resize_keyboard=True,
    )


def get_registration_cancel_kb() -> ReplyKeyboardMarkup:
    """Отмена во время регистрации."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


# ─── Создание челленджа ───
def get_challenge_type_kb() -> ReplyKeyboardMarkup:
    """Выбор типа челленджа."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📜 Регулярный (X раз в неделю)")],
            [KeyboardButton(text="🎯 Дневной спринт (N км за день)")],
            [KeyboardButton(text="📅 Недельный спринт (N км за неделю)")],
            [KeyboardButton(text="📆 Месячный спринт (N км за месяц)")],
            [KeyboardButton(text="🏃 Разовый забег (N км за время)")],
            [KeyboardButton(text="♾️ Открытый челлендж (без даты)")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


# ─── Отчёты (P2P голосование + админ апрув) ───
def get_report_kb(report_id: int) -> InlineKeyboardMarkup:
    """Кнопки для голосования за отчёт."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Засчитать", callback_data=f"vote:{report_id}"),
        InlineKeyboardButton(text="❌ Фейк", callback_data=f"vote_no:{report_id}"),
    )
    builder.row(
        InlineKeyboardButton(
            text="👑 Админ: одобрить",
            callback_data=f"adm_approve:{report_id}",
        )
    )
    return builder.as_markup()


def get_report_approved_kb() -> InlineKeyboardMarkup:
    """После принятия отчёта."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Отчёт принят", callback_data="noop"))
    return builder.as_markup()


def get_report_rejected_kb() -> InlineKeyboardMarkup:
    """После отклонения отчёта."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отчёт отклонён", callback_data="noop"))
    return builder.as_markup()


# ─── Мероприятия ───
def get_event_kb(event_id: int, joined: bool = False) -> InlineKeyboardMarkup:
    """Кнопки для регистрации на мероприятие."""
    builder = InlineKeyboardBuilder()
    if joined:
        builder.button(
            text="✅ Ты участвуешь",
            callback_data="noop"
        )
        builder.button(
            text="❌ Отмена",
            callback_data=f"event_leave:{event_id}"
        )
    else:
        builder.button(
            text="🏃 Участвую!",
            callback_data=f"event_join:{event_id}"
        )
        builder.button(
            text="❌ Не пойду",
            callback_data=f"event_skip:{event_id}"
        )
    return builder.as_markup()


def get_event_participants_kb(event_id: int, going_count: int, not_going_count: int) -> InlineKeyboardMarkup:
    """Показывает счётчики участников на кнопках."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🏃 Участвую ({going_count})",
        callback_data=f"event_join:{event_id}"
    )
    builder.button(
        text=f"❌ Не пойду ({not_going_count})",
        callback_data=f"event_skip:{event_id}"
    )
    return builder.as_markup()


# ─── Челленджи (присоединение, турниры) ───
def get_join_challenge_kb(challenge_id: int) -> InlineKeyboardMarkup:
    """Кнопка присоединиться к чужому челленджу."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🤝 Присоединиться",
        callback_data=f"join_ch:{challenge_id}"
    )
    return builder.as_markup()


def get_tournament_kb(tournament_id: int, joined: bool = False) -> InlineKeyboardMarkup:
    """Кнопки для регистрации в турнир."""
    builder = InlineKeyboardBuilder()
    if joined:
        builder.button(text="✅ Ты участвуешь", callback_data="noop")
    else:
        builder.button(
            text="🏆 Принять вызов",
            callback_data=f"tour_join:{tournament_id}"
        )
    return builder.as_markup()


# ─── Админ-меню ───
def get_admin_main_kb() -> ReplyKeyboardMarkup:
    """Админ-панель."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Создать мероприятие")],
            [KeyboardButton(text="👥 Управление модераторами")],
            [KeyboardButton(text="📋 Шаблоны мероприятий")],
            [KeyboardButton(text="🏆 Создать турнир")],
            [KeyboardButton(text="⬅️ Главное меню")],
        ],
        resize_keyboard=True,
    )


def get_moderator_manage_kb() -> ReplyKeyboardMarkup:
    """Управление модераторами."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить модератора")],
            [KeyboardButton(text="➖ Удалить модератора")],
            [KeyboardButton(text="📋 Список модераторов")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def get_templates_manage_kb() -> ReplyKeyboardMarkup:
    """Управление шаблонами мероприятий."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Создать шаблон")],
            [KeyboardButton(text="📚 Список шаблонов")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def get_noop_kb() -> InlineKeyboardMarkup:
    """Пустая кнопка (noop) для отключения интерактивности."""
    builder = InlineKeyboardBuilder()
    builder.button(text=" ", callback_data="noop")
    return builder.as_markup()