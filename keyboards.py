"""keyboards.py — все кнопки для бота."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ─── Главное меню ───

def get_main_kb() -> ReplyKeyboardMarkup:
    """Главное меню для обычных пользователей."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏃 Создать челлендж")],
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📊 Таблица лидеров")],
            [KeyboardButton(text="📅 Мероприятия"), KeyboardButton(text="📅 Создать мероприятие")],
            [KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="IT БЕГОТНЯ 21",
    )


def get_main_kb_with_admin() -> ReplyKeyboardMarkup:
    """Главное меню для администраторов и модераторов (с кнопкой администрирования)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏃 Создать челлендж")],
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📊 Таблица лидеров")],
            [KeyboardButton(text="📅 Мероприятия"), KeyboardButton(text="❓ Помощь")],
            [KeyboardButton(text="⚙️ Администрирование")],
        ],
        resize_keyboard=True,
        input_field_placeholder="IT БЕГОТНЯ 21",
    )


def get_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


# ─── FSM регистрации ───

def get_registration_start_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да, я здесь уже")],
            [KeyboardButton(text="❌ Нет, первый раз")],
        ],
        resize_keyboard=True,
    )


def get_registration_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


# ─── Создание челленджа ───

def get_challenge_type_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Регулярный",       callback_data="ch_type:weekly_runs")
    builder.button(text="🎯 Дневной спринт",   callback_data="ch_type:daily_km")
    builder.button(text="📅 Недельный спринт", callback_data="ch_type:weekly_km")
    builder.button(text="📆 Месячный спринт",  callback_data="ch_type:monthly_km")
    builder.button(text="🏃 Разовый забег",    callback_data="ch_type:race")
    builder.button(text="❌ Отмена",            callback_data="ch_type:cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, создать", callback_data="ch_confirm:yes")
    builder.button(text="❌ Отменить",    callback_data="ch_confirm:no")
    builder.adjust(2)
    return builder.as_markup()


def get_end_date_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Указать дату", callback_data="ch_end:set")
    builder.button(text="♾️ Бессрочный",   callback_data="ch_end:open")
    builder.adjust(2)
    return builder.as_markup()


# ─── Отчёты ───

def get_report_vote_kb(report_id: int, pos: int = 0, neg: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"✅ Засчитать ({pos})", callback_data=f"vote_yes:{report_id}"),
        InlineKeyboardButton(text=f"❌ Фейк ({neg})",      callback_data=f"vote_no:{report_id}"),
    )
    return builder.as_markup()


def get_report_admin_kb(report_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👑 Одобрить",  callback_data=f"adm_approve:{report_id}"),
        InlineKeyboardButton(text="🚫 Отклонить", callback_data=f"adm_reject:{report_id}"),
    )
    return builder.as_markup()


def get_report_kb(report_id: int) -> InlineKeyboardMarkup:
    """Совмещённые кнопки голосования + админ-апрув (для группы)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Засчитать", callback_data=f"vote_yes:{report_id}"),
        InlineKeyboardButton(text="❌ Фейк",      callback_data=f"vote_no:{report_id}"),
    )
    builder.row(InlineKeyboardButton(text="👑 Админ: одобрить", callback_data=f"adm_approve:{report_id}"))
    return builder.as_markup()


def get_report_approved_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Отчёт принят", callback_data="noop"))
    return builder.as_markup()


def get_report_rejected_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отчёт отклонён", callback_data="noop"))
    return builder.as_markup()


# ─── Мероприятия ───

def get_event_participants_kb(event_id: int, going_count: int, not_going_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🏃 Участвую ({going_count})",   callback_data=f"event_join:{event_id}")
    builder.button(text=f"❌ Не пойду ({not_going_count})", callback_data=f"event_skip:{event_id}")
    builder.adjust(2)
    return builder.as_markup()


def get_event_kb(event_id: int, joined: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if joined:
        builder.button(text="✅ Ты участвуешь", callback_data="noop")
        builder.button(text="❌ Отмена участия", callback_data=f"event_leave:{event_id}")
    else:
        builder.button(text="🏃 Участвую!",  callback_data=f"event_join:{event_id}")
        builder.button(text="❌ Не пойду",   callback_data=f"event_skip:{event_id}")
    builder.adjust(2)
    return builder.as_markup()


def get_event_moderation_kb(event_id: int) -> InlineKeyboardMarkup:
    """Кнопки предпросмотра анонса для модератора/админа."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Опубликовать в основную группу", callback_data=f"evt_pub_main:{event_id}")
    builder.button(text="❌ Отклонить",                      callback_data=f"evt_reject:{event_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_event_secondary_kb(event_id: int) -> InlineKeyboardMarkup:
    """Кнопка публикации во вторую группу (показывается после публикации в основную)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📣 Репостнуть во вторую группу", callback_data=f"evt_pub_sec:{event_id}")
    builder.button(text="➡️ Пропустить",                   callback_data=f"evt_skip_sec:{event_id}")
    builder.adjust(1)
    return builder.as_markup()


# ─── Челленджи ───

def get_join_challenge_kb(challenge_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🤝 Присоединиться", callback_data=f"join_ch:{challenge_id}")
    return builder.as_markup()


def get_tournament_kb(tournament_id: int, joined: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if joined:
        builder.button(text="✅ Ты участвуешь", callback_data="noop")
    else:
        builder.button(text="🏆 Принять вызов", callback_data=f"tour_join:{tournament_id}")
    return builder.as_markup()


def get_challenge_link_kb(
    report_id: int,
    challenges: list,
    selected: set[int] | None = None,
) -> InlineKeyboardMarkup:
    from services.challenges import get_type_name

    if selected is None:
        selected = set()

    builder = InlineKeyboardBuilder()
    for ch in challenges:
        is_selected = ch.id in selected
        prefix = "✅" if is_selected else "➕"
        label = f"{prefix} {get_type_name(ch.ch_type)}: {ch.title}"
        if len(label) > 60:
            label = label[:57] + "…"
        builder.button(text=label, callback_data=f"toggle_ch:{report_id}:{ch.id}")

    builder.button(text="✔️ Готово", callback_data=f"link_done:{report_id}")
    builder.adjust(1)
    return builder.as_markup()


# ─── Админ-меню ───

def get_admin_main_kb() -> ReplyKeyboardMarkup:
    """Полная панель для администраторов."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Создать мероприятие")],
            [KeyboardButton(text="🕐 Мероприятия на модерации")],
            [KeyboardButton(text="👥 Управление модераторами")],
            [KeyboardButton(text="📋 Шаблоны мероприятий")],
            [KeyboardButton(text="🏆 Создать турнир")],
            [KeyboardButton(text="⬅️ Главное меню")],
        ],
        resize_keyboard=True,
    )


def get_moderator_main_kb() -> ReplyKeyboardMarkup:
    """Панель для модераторов (без управления модераторами и шаблонами)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Создать мероприятие")],
            [KeyboardButton(text="🕐 Мероприятия на модерации")],
            [KeyboardButton(text="⬅️ Главное меню")],
        ],
        resize_keyboard=True,
    )


def get_moderator_manage_kb() -> ReplyKeyboardMarkup:
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
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Создать шаблон")],
            [KeyboardButton(text="📚 Список шаблонов")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def get_noop_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=" ", callback_data="noop")
    return builder.as_markup()