import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import async_session
from models import Challenge, User, Vote
from sqlalchemy import select, update, func

router = Router()

# 1. СЮДА ВПИШИ СВОЙ ID (узнать можно у @userinfobot)
ADMIN_IDS = [584284564] 

# 2. СЮДА ВПИШИ ID ТЕМЫ (узнаешь из консоли после первого сообщения в тему)
# Пока тут None — работает во всех темах. Как узнаешь ID — замени None на число.
CHALLENGE_TOPIC_ID = 3

class ChallengeForm(StatesGroup):
    choosing_type = State()
    input_value = State()
    input_penalty = State()

# --- Фильтр темы и логирование ID ---
async def check_topic(message: types.Message):
    # Этот принт покажет тебе ID темы в консоли!
    if message.message_thread_id:
        print(f"[TOPIC ID] Сообщение в теме: {message.message_thread_id}")
    
    if CHALLENGE_TOPIC_ID is None:
        return True
    return message.message_thread_id == CHALLENGE_TOPIC_ID

# --- Создание челленджа ---
@router.message(Command("challenge"))
@router.message(F.text == "🏃 Создать челлендж")
async def cmd_challenge(message: types.Message, state: FSMContext):
    if not await check_topic(message): return

    await state.set_state(ChallengeForm.choosing_type)
    kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Разы в неделю"), types.KeyboardButton(text="Дистанция (км)")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer(f"@{message.from_user.username}, выбирай тип:", reply_markup=kb)

@router.message(ChallengeForm.choosing_type)
async def process_type(message: types.Message, state: FSMContext):
    await state.update_data(type=message.text)
    await state.set_state(ChallengeForm.input_value)
    await message.answer("Введи цель (число):", reply_markup=types.ReplyKeyboardRemove())

@router.message(ChallengeForm.input_value)
async def process_value(message: types.Message, state: FSMContext):
    val = message.text.replace(',', '.')
    try:
        await state.update_data(value=float(val))
        await state.set_state(ChallengeForm.input_penalty)
        await message.answer("Что проставишь в случае провала?")
    except ValueError:
        await message.answer("Введи число!")

@router.message(ChallengeForm.input_penalty)
async def process_penalty(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        async with session.begin():
            new_ch = Challenge(
                user_id=message.from_user.id,
                type=data['type'],
                goal_value=data['value'],
                penalty=message.text,
                current_value=0.0,
                is_active=True
            )
            session.add(new_ch)
    await state.clear()
    await message.answer(f"✅ <b>Челлендж создан!</b>\nЦель: {data['value']} {data['type']}")

# --- Обработка отчета ---
@router.message(F.photo, F.caption.contains("#отчет"))
async def handle_report(message: types.Message):
    if not await check_topic(message): return

    # Вытаскиваем цифру из подписи "#отчет 10"
    try:
        val_str = message.caption.replace("#отчет", "").strip()
        added_value = float(val_str) if val_str else 1.0
    except ValueError:
        added_value = 1.0

    async with async_session() as session:
        res = await session.execute(
            select(Challenge).where(Challenge.user_id == message.from_user.id, Challenge.is_active == True)
            .order_by(Challenge.id.desc()).limit(1)
        )
        challenge = res.scalar()
        if not challenge: return

    builder = InlineKeyboardBuilder()
    # Обычная кнопка (нужно 3 голоса)
    builder.button(text="✅ Засчитать (0/3)", callback_data=f"v_{message.from_user.id}_{message.message_id}_{added_value}")
    
    # Кнопка только для админов (мгновенно закрывает)
    if message.from_user.id in ADMIN_IDS:
        builder.button(text="👑 Админ: Одобрить", callback_data=f"adm_{message.from_user.id}_{added_value}")

    await message.reply(
        f"🏃 <b>Отчет от @{message.from_user.username}!</b>\n"
        f"Добавляем: <b>{added_value}</b> к цели.\n"
        f"Нужно 3 голоса или 👑 Админ.",
        reply_markup=builder.as_markup()
    )

# --- Логика кнопок (Голоса и Админ) ---
@router.callback_query(F.data.startswith(("v_", "adm_")))
async def process_vote(callback: types.CallbackQuery):
    is_admin = callback.data.startswith("adm_")
    parts = callback.data.split("_")
    target_user_id = int(parts[1])
    added_value = float(parts[-1])

    # Проверка админа
    if is_admin and callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("У тебя нет прав админа!", show_alert=True)

    # За себя нельзя (кроме админа самому себе для теста)
    if not is_admin and target_user_id == callback.from_user.id:
        return await callback.answer("За себя нельзя!", show_alert=True)

    async with async_session() as session:
        # Если нажал админ — одобряем сразу
        # Если не админ — пока просто добавим логику одобрения сразу для теста, 
        # позже прикрутим таблицу Vote для подсчета 3-х человек.
        
        res = await session.execute(
            select(Challenge).where(Challenge.user_id == target_user_id, Challenge.is_active == True)
        )
        ch = res.scalar()
        
        if ch:
            ch.current_value += added_value
            if ch.current_value >= ch.goal_value:
                ch.is_active = False
                await callback.message.edit_text(f"🏁 <b>ЦЕЛЬ ВЫПОЛНЕНА!</b>\nИтого: {ch.current_value}/{ch.goal_value}")
            else:
                await callback.message.edit_text(f"📈 <b>Прогресс обновлен!</b>\nТеперь: {ch.current_value}/{ch.goal_value}")
            
            await session.commit()
            await callback.answer("Успешно!")