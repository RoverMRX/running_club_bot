"""handlers/admin.py — админ-панель: модераторы, шаблоны, управление."""

import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select

import config
from database import async_session
from models import Moderator, EventTemplate
from keyboards import get_main_kb, get_cancel_kb, get_admin_main_kb

router = Router()
log = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


class ModeratorSetup(StatesGroup):
    action = State()  # "add" или "remove"
    user_id = State()


class TemplateSetup(StatesGroup):
    name = State()
    description = State()
    is_external = State()
    xp_bonus = State()
    xp_multiplier = State()


# ──────────────────────────────────────────
# Админ-меню
# ──────────────────────────────────────────

@router.message(F.text == "👥 Управление модераторами")
async def admin_moderators(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await state.clear()
    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Добавить модератора")],
            [types.KeyboardButton(text="➖ Удалить модератора")],
            [types.KeyboardButton(text="📋 Список модераторов")],
            [types.KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )
    await message.answer("👥 <b>Управление модераторами</b>", reply_markup=kb)


@router.message(F.text == "➕ Добавить модератора")
async def add_moderator(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(ModeratorSetup.action)
    await state.update_data(action="add")
    await message.answer(
        "Введи Telegram ID пользователя (числовой ID):",
        reply_markup=get_cancel_kb(),
    )


@router.message(F.text == "➖ Удалить модератора")
async def remove_moderator(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(ModeratorSetup.action)
    await state.update_data(action="remove")
    await message.answer(
        "Введи Telegram ID модератора для удаления:",
        reply_markup=get_cancel_kb(),
    )


@router.message(ModeratorSetup.action)
async def process_moderator(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_admin_main_kb())
    
    try:
        user_id = int(message.text.strip())
    except ValueError:
        return await message.answer("Введи числовой ID.")
    
    data = await state.get_data()
    action = data.get("action")
    
    async with async_session() as session:
        async with session.begin():
            if action == "add":
                # Проверяем уже ли модератор
                m_res = await session.execute(
                    select(Moderator).where(Moderator.tg_id == user_id)
                )
                if m_res.scalar_one_or_none():
                    await state.clear()
                    return await message.answer(
                        "Этот пользователь уже модератор.",
                        reply_markup=get_admin_main_kb(),
                    )
                
                # Добавляем
                mod = Moderator(
                    tg_id=user_id,
                    added_by=message.from_user.id,
                )
                session.add(mod)
                result = f"✅ Модератор <code>{user_id}</code> добавлен."
            
            else:  # remove
                m_res = await session.execute(
                    select(Moderator).where(Moderator.tg_id == user_id)
                )
                mod = m_res.scalar_one_or_none()
                if not mod:
                    await state.clear()
                    return await message.answer(
                        "Модератор не найден.",
                        reply_markup=get_admin_main_kb(),
                    )
                await session.delete(mod)
                result = f"✅ Модератор <code>{user_id}</code> удалён."
    
    await state.clear()
    await message.answer(result, reply_markup=get_admin_main_kb())


@router.message(F.text == "📋 Список модераторов")
async def list_moderators(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    async with async_session() as session:
        m_res = await session.execute(select(Moderator))
        mods = m_res.scalars().all()
    
    if not mods:
        await message.answer("Модераторов нет.", reply_markup=get_admin_main_kb())
        return
    
    lines = ["👥 <b>Список модераторов:</b>\n"]
    for m in mods:
        name = f"@{m.username}" if m.username else m.full_name or f"ID {m.tg_id}"
        lines.append(f"• {name} (ID: <code>{m.tg_id}</code>)")
    
    await message.answer("\n".join(lines), reply_markup=get_admin_main_kb())


# ──────────────────────────────────────────
# Шаблоны мероприятий
# ──────────────────────────────────────────

@router.message(F.text == "📋 Шаблоны мероприятий")
async def admin_templates(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Создать шаблон")],
            [types.KeyboardButton(text="📚 Список шаблонов")],
            [types.KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )
    await message.answer("📋 <b>Шаблоны мероприятий</b>", reply_markup=kb)


@router.message(F.text == "➕ Создать шаблон")
async def create_template(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.chat.type != "private":
        return await message.reply("Только в личке!")
    
    await state.set_state(TemplateSetup.name)
    await message.answer(
        "📝 <b>Создание шаблона</b>\n\n"
        "Название (например: «5 вёрст» или «Long Run»):",
        reply_markup=get_cancel_kb(),
    )


@router.message(TemplateSetup.name)
async def tpl_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    await state.update_data(name=message.text.strip())
    await state.set_state(TemplateSetup.description)
    await message.answer("Описание (или «-»):", reply_markup=get_cancel_kb())


@router.message(TemplateSetup.description)
async def tpl_desc(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    desc = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(description=desc)
    await state.set_state(TemplateSetup.is_external)
    
    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="✅ Мы организаторы (свое мероприятие)")],
            [types.KeyboardButton(text="🚶 Мы гости (5 вёрст, городской забег)")],
            [types.KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )
    await message.answer("Тип мероприятия:", reply_markup=kb)


@router.message(TemplateSetup.is_external)
async def tpl_external(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    
    is_ext = "гости" in message.text.lower()
    await state.update_data(is_external=is_ext)
    await state.set_state(TemplateSetup.xp_bonus)
    await message.answer(
        "Бонус XP за участие (число):\n"
        "Обычно: 100 (свое) или 75 (гость)",
        reply_markup=get_cancel_kb(),
    )


@router.message(TemplateSetup.xp_bonus)
async def tpl_bonus(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    try:
        bonus = int(message.text.strip())
    except ValueError:
        return await message.answer("Введи число.")
    
    await state.update_data(xp_bonus=bonus)
    await state.set_state(TemplateSetup.xp_multiplier)
    await message.answer(
        "Множитель XP за км (число):\n"
        "Обычно: 1.0 или 1.5",
        reply_markup=get_cancel_kb(),
    )


@router.message(TemplateSetup.xp_multiplier)
async def tpl_multiplier(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await message.answer("Отменено.", reply_markup=get_main_kb())
    try:
        mult = float(message.text.replace(",", "."))
    except ValueError:
        return await message.answer("Введи число.")
    
    data = await state.get_data()
    async with async_session() as session:
        async with session.begin():
            tpl = EventTemplate(
                name=data["name"],
                description=data.get("description"),
                is_external=data["is_external"],
                xp_bonus=data["xp_bonus"],
                xp_multiplier=mult,
                created_by=message.from_user.id,
            )
            session.add(tpl)
    
    await state.clear()
    ext_str = "Мы гости" if data["is_external"] else "Мы организаторы"
    await message.answer(
        f"✅ Шаблон создан!\n\n"
        f"📋 <b>{data['name']}</b>\n"
        f"{ext_str}\n"
        f"Бонус: {data['xp_bonus']} XP × {mult} км",
        reply_markup=get_admin_main_kb(),
    )


@router.message(F.text == "📚 Список шаблонов")
async def list_templates(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    
    async with async_session() as session:
        t_res = await session.execute(select(EventTemplate).where(EventTemplate.is_active == True))
        templates = t_res.scalars().all()
    
    if not templates:
        await message.answer("Шаблонов нет.", reply_markup=get_admin_main_kb())
        return
    
    lines = ["📋 <b>Доступные шаблоны:</b>\n"]
    for t in templates:
        ext_str = "🚶 гость" if t.is_external else "✅ организатор"
        lines.append(
            f"• <b>{t.name}</b> ({ext_str})\n"
            f"  Бонус: {t.xp_bonus} XP × {t.xp_multiplier} км"
        )
    
    await message.answer("\n".join(lines), reply_markup=get_admin_main_kb())


# ──────────────────────────────────────────
# Навигация админ-меню
# ──────────────────────────────────────────

@router.message(F.text == "⬅️ Назад")
async def admin_back(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=get_admin_main_kb())


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=get_admin_main_kb())