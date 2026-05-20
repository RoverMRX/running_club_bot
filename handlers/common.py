"""handlers/common.py — базовые команды: /start, профиль, лидеры, помощь."""

import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select

import config
from database import async_session
from models import User
from keyboards import (
    get_main_kb, get_main_kb_with_admin, get_cancel_kb,
    get_registration_start_kb, get_admin_main_kb,
    get_challenges_menu_kb, get_events_menu_kb,
)
from services import users as users_service

router = Router()
log = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    """Проверка администратор."""
    return user_id in config.ADMIN_IDS


async def main_kb_for(user_id: int):
    """Возвращает нужную клавиатуру главного меню в зависимости от роли."""
    from services.events import is_moderator
    if is_admin(user_id):
        return get_main_kb_with_admin()
    async with async_session() as session:
        if await is_moderator(session, user_id):
            return get_main_kb_with_admin()
    return get_main_kb()


# ─────────────────────────────────────────
# FSM регистрации
# ─────────────────────────────────────────

class RegistrationStates(StatesGroup):
    """Состояния FSM регистрации."""
    already_registered = State()  # Уже зарегистрирован?
    school_nick = State()          # Школьный ник
    full_name = State()            # Имя и фамилия


# ─────────────────────────────────────────
# /start
# ─────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Точка входа в бота."""
    await state.clear()

    async with async_session() as session:
        user = await users_service.get_user_by_id(session, message.from_user.id)

    if user:
        # Уже зарегистрирован
        await message.answer(
            f"👋 Привет, <b>{user.school_nick}</b>!\n\n"
            f"Добро пожаловать обратно в <b>IT БЕГОТНЯ 21</b> 🏃",
            reply_markup=await main_kb_for(message.from_user.id),
        )
    else:
        # Первый раз в боте
        await state.set_state(RegistrationStates.already_registered)
        await message.answer(
            "👋 <b>Привет, беговой режим!</b>\n\n"
            "Добро пожаловать в <b>IT БЕГОТНЯ 21</b> — беговой клуб айтишников. 🏃\n\n"
            "Здесь ты можешь:\n"
            "• Ставить и выполнять личные челленджи\n"
            "• Отчитываться перед командой\n"
            "• Участвовать в турнирах и мероприятиях\n"
            "• Подняться в таблице лидеров\n\n"
            "Ты уже когда-то регистрировался в клубе?",
            reply_markup=get_registration_start_kb(),
        )


# ─────────────────────────────────────────
# FSM: Уже регистрировался?
# ─────────────────────────────────────────

@router.message(RegistrationStates.already_registered)
async def registration_check(message: types.Message, state: FSMContext):
    """Обработка ответа: уже регистрировался или нет."""
    if message.text not in ("✅ Да, я здесь уже", "❌ Нет, первый раз"):
        return await message.answer(
            "Выбери вариант из кнопок ниже 👇",
            reply_markup=get_registration_start_kb(),
        )

    # В обоих случаях ведём на регистрацию: раз профиля в БД нет,
    # человек регистрируется как новый
    if message.text == "✅ Да, я здесь уже":
        await message.answer(
            "Хм, твой профиль не нашёлся в системе 🤔\n"
            "Ничего страшного — давай создадим новый!"
        )

    await state.set_state(RegistrationStates.school_nick)
    await message.answer(
        "Как тебя зовут в школе 21?\n"
        "<i>Например: quicksir или leeannaf</i>",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# FSM: Школьный ник
# ─────────────────────────────────────────

@router.message(RegistrationStates.school_nick)
async def registration_school_nick(message: types.Message, state: FSMContext):
    """Ввод школьного ника."""
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer(
            "Отменено. Используй /start чтобы начать заново.",
            reply_markup=get_main_kb(),
        )

    nick = message.text.strip().lstrip("@").lower()

    # Длина
    if len(nick) < 3 or len(nick) > 20:
        return await message.answer(
            "Ник должен быть от 3 до 20 символов.\n"
            "<i>Например: quicksir</i>",
            reply_markup=get_cancel_kb(),
        )

    # Только латинские буквы
    if not nick.isalpha() or not nick.isascii():
        return await message.answer(
            "Ник может содержать только латинские буквы — без цифр, "
            "дефисов, символов и пробелов.\n"
            "<i>Например: quicksir или leeannaf</i>",
            reply_markup=get_cancel_kb(),
        )

    # Уникальность
    if await users_service.exists_school_nick(nick):
        return await message.answer(
            f"Ник <b>{nick}</b> уже занят 😞\n"
            "Попробуй другой:",
            reply_markup=get_cancel_kb(),
        )

    await state.update_data(school_nick=nick)
    await state.set_state(RegistrationStates.full_name)
    await message.answer(
        f"✅ Ник <b>{nick}</b> зарезервирован!\n\n"
        "Теперь как тебя зовут в реальности?\n"
        "<i>Например: Василий Пупкин</i>\n"
        "(или напиши «-» если не хочешь указывать)",
        reply_markup=get_cancel_kb(),
    )


# ─────────────────────────────────────────
# FSM: Имя и фамилия
# ─────────────────────────────────────────

@router.message(RegistrationStates.full_name)
async def registration_full_name(message: types.Message, state: FSMContext):
    """Ввод имени и фамилии — завершает регистрацию."""
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer(
            "Отменено. Используй /start чтобы начать заново.",
            reply_markup=get_main_kb(),
        )

    full_name = None if message.text.strip() == "-" else message.text.strip()

    data = await state.get_data()
    school_nick = data["school_nick"]

    # Создаём пользователя в БД
    async with async_session() as session:
        async with session.begin():
            user = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                full_name=full_name or message.from_user.full_name,
                school_nick=school_nick,
                xp=0,
                level=0,
                season_xp=0,
                streak=0,
            )
            session.add(user)

    await state.clear()

    await message.answer(
        f"🎉 <b>Добро пожаловать в IT БЕГОТНЯ 21!</b>\n\n"
        f"👤 Профиль создан:\n"
        f"   Школьный ник: <b>{school_nick}</b>\n"
        f"   Имя: <b>{full_name or message.from_user.full_name or 'не указано'}</b>\n\n"
        f"Теперь ты можешь создавать челленджи, отчитываться и участвовать в турнирах! 🏃",
        reply_markup=await main_kb_for(message.from_user.id),
    )


# ─────────────────────────────────────────
# Профиль
# ─────────────────────────────────────────

@router.message(F.text == "👤 Мой профиль")
async def cmd_profile(message: types.Message):
    """Показать профиль пользователя."""
    profile = await users_service.get_profile(message.from_user.id)

    if not profile:
        return await message.answer(
            "Сначала пройди регистрацию: /start",
            reply_markup=get_main_kb(),
        )

    user = profile['user']
    level = profile['level']
    xp = profile['xp']
    season_xp = profile['season_xp']
    streak = profile['streak']
    pr = profile['pr']
    own_challenges = profile['own_challenges']

    # Форматируем уровень
    if level < 5:
        level_emoji = "🌱"
        level_name = "Новичок"
    elif level < 20:
        level_emoji = "🌿"
        level_name = "Бегун"
    else:
        level_emoji = "🌳"
        level_name = "Атлет"

    lines = [
        f"👤 <b>{user.school_nick}</b>",
        f"   {user.full_name or 'имя не указано'}",
        "",
        f"{level_emoji} <b>Уровень {level}</b> ({level_name})",
        f"💠 All-Time XP: <b>{xp}</b>",
        f"📊 Сезонный XP: <b>{season_xp}</b>",
        f"🔥 Стрик: <b>{streak} недель</b>",
        f"🎯 Личный рекорд: <b>{pr:.1f} км</b>",
        "",
    ]

    if own_challenges:
        lines.append("<b>Активные челленджи:</b>")
        for ch in own_challenges:
            icon = "📜" if ch.ch_type == "weekly_runs" else "🎯"
            lines.append(f"  {icon} {ch.title}")
    else:
        lines.append("<i>Нет активных челленджей. Создай свой! 🏃</i>")

    await message.answer("\n".join(lines), reply_markup=get_main_kb())


# ─────────────────────────────────────────
# Таблица лидеров
# ─────────────────────────────────────────

@router.message(F.text == "📊 Таблица лидеров")
async def cmd_leaderboard(message: types.Message):
    """Показать таблицу лидеров."""
    leaderboard = await users_service.get_leaderboard(limit=10)

    if not leaderboard:
        return await message.answer(
            "На доске почёта пока никого 🏜️\n"
            "Будь первым! 🏃",
        )

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>ТОП БЕГОВОЙ КЛУБ</b>\n"]

    for lb in leaderboard:
        medal = medals[lb['position'] - 1] if lb['position'] <= 3 else f"{lb['position']}."
        streak_str = f" 🔥{lb['streak']}" if lb['streak'] > 0 else ""
        lines.append(
            f"{medal} {lb['school_nick']} ({lb['username']})\n"
            f"   Level {lb['level']} • {lb['xp']} XP{streak_str}"
        )

    await message.answer("\n".join(lines), reply_markup=get_main_kb())


# ─────────────────────────────────────────
# Помощь
# ─────────────────────────────────────────

@router.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    """Справка по боту."""
    await message.answer(
        "❓ <b>Как пользоваться IT БЕГОТНЯ 21</b>\n\n"

        "<b>📸 Отчёт о тренировке:</b>\n"
        "Напиши в топике Отчёты (фото необязательно):\n"
        "<code>#отчет 7.5</code>\n"
        "Дистанция — первой строкой, описание — ниже.\n\n"

        f"Нужно <b>{config.VOTES_REQUIRED} голоса</b> других участников или одобрение админа.\n\n"

        "<b>🎯 Челленджи:</b>\n"
        "• Кнопка <b>🎯 Челленджи</b> → подменю\n"
        "• 🏃 Создать — новый челлендж (5 типов)\n"
        "• 🤝 Челленджи клуба — список других участников, можно присоединиться\n"
        "• 📋 Мои челленджи — твои активные с прогрессом\n\n"

        "<b>📅 Мероприятия:</b>\n"
        "• Кнопка <b>📅 Мероприятия</b> → подменю\n"
        "• 📋 Ближайшие — все грядущие события\n"
        "• ➕ Создать — предложи своё (уйдёт на модерацию)\n\n"

        "<b>🏆 Турниры:</b>\n"
        "• Еженедельные спринты\n"
        "• Командные забеги\n"
        "• Рейтинговая таблица\n\n"

        "<b>📊 Система уровней:</b>\n"
        "🌱 Новичок (0-4 лвл)\n"
        "🌿 Бегун (5-19 лвл)\n"
        "🌳 Атлет (20+ лвл)\n"
        "1 Level = 100 XP\n\n"

        "<b>💠 XP за:</b>\n"
        "• 1 км = 10 XP\n"
        "• Закрытая неделя = 50 XP\n"
        "• Личный рекорд = 50 XP\n"
        "• Milestone стрик = 100–300 XP\n",
        reply_markup=get_main_kb(),
    )


# ─────────────────────────────────────────
# Админ-меню
# ─────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Админ-панель."""
    if not is_admin(message.from_user.id):
        return

    await message.answer("👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=get_admin_main_kb())


# ─────────────────────────────────────────
# Навигация
# ─────────────────────────────────────────

@router.message(F.text == "🎯 Челленджи")
async def menu_challenges(message: types.Message):
    """Открыть подменю Челленджи."""
    await message.answer("🎯 <b>Челленджи</b>", reply_markup=get_challenges_menu_kb())


@router.message(F.text == "📅 Мероприятия")
async def menu_events(message: types.Message):
    """Открыть подменю Мероприятия."""
    await message.answer("📅 <b>Мероприятия</b>", reply_markup=get_events_menu_kb())


@router.message(F.text == "⬅️ Главное меню")
async def back_to_main(message: types.Message):
    """Вернуться в главное меню."""
    await message.answer("Главное меню", reply_markup=await main_kb_for(message.from_user.id))


@router.message(F.text == "❌ Отмена")
async def msg_cancel(message: types.Message, state: FSMContext):
    """Отмена и выход из FSM."""
    await state.clear()
    await message.answer("Отменено.", reply_markup=await main_kb_for(message.from_user.id))


# ─────────────────────────────────────────
# Noop callback
# ─────────────────────────────────────────

@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    """Пустой callback — ничего не делаем."""
    await callback.answer()