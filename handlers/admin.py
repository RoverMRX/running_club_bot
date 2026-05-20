"""handlers/admin.py — шаблоны мероприятий и управление модераторами."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select, delete

import config
from database import async_session
from keyboards import (
    get_admin_main_kb,
    get_cancel_kb,
    get_moderator_manage_kb,
    get_templates_manage_kb,
)
from models import Moderator
from services.events import create_event_template, get_templates

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ═══════════════════════════════════════════════════════════════
# Панель администрирования
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "⚙️ Администрирование")
async def cmd_admin_panel(message: Message) -> None:
    from services.events import is_moderator
    user_id = message.from_user.id

    is_mod = False
    async with async_session() as session:
        is_mod = await is_moderator(session, user_id)

    if not (_is_admin(user_id) or is_mod):
        return  # Молча игнорируем — кнопки у них быть не должно

    if _is_admin(user_id):
        await message.answer("👑 <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>", reply_markup=get_admin_main_kb())
    else:
        from keyboards import get_moderator_main_kb
        await message.answer("🛡 <b>ПАНЕЛЬ МОДЕРАТОРА</b>", reply_markup=get_moderator_main_kb())


@router.message(F.text == "⬅️ Назад")
async def cmd_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    if _is_admin(message.from_user.id):
        await message.answer("Админ-панель:", reply_markup=get_admin_main_kb())
    else:
        from keyboards import get_moderator_main_kb
        await message.answer("Панель модератора:", reply_markup=get_moderator_main_kb())



# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═
# На модерации — мероприятия ожидающие публикации
# ═

@router.message(F.text == "🗂 На модерации")
async def cmd_moderation_queue(message: Message) -> None:
    from services.events import is_moderator, get_pending_events
    from keyboards import get_event_moderation_kb
    user_id = message.from_user.id
    async with async_session() as session:
        is_mod = await is_moderator(session, user_id)
    if not (_is_admin(user_id) or is_mod):
        return
    events = await get_pending_events()
    if not events:
        await message.answer("✅ Нет мероприятий на модерации.")
        return
    await message.answer("🗂 <b>На модерации: " + str(len(events)) + " шт.</b>")
    for ev in events:
        date_str = ev.event_date.strftime("%d.%m.%Y %H:%M") if ev.event_date else "—"
        parts = ["📅 <b>" + ev.title + "</b>", "⏰ " + date_str]
        if ev.location:
            parts.append("📍 " + ev.location)
        if ev.description:
            parts.append(ev.description)
        await message.answer("\n".join(parts), reply_markup=get_event_moderation_kb(ev.id))


# ═══════════════════════════════════════════════════════════════
# Шаблоны мероприятий (только для администраторов)
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "📐 Шаблоны мероприятий")
async def cmd_templates_menu(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Шаблоны доступны только администраторам.")
        return
    await message.answer("📋 Шаблоны мероприятий:", reply_markup=get_templates_manage_kb())


@router.message(F.text == "📚 Список шаблонов")
async def cmd_list_templates(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    async with async_session() as session:
        templates = await get_templates(session)

    if not templates:
        await message.answer(
            "Шаблонов пока нет. Создай первый через «➕ Создать шаблон».",
            reply_markup=get_templates_manage_kb(),
        )
        return

    lines = ["<b>Активные шаблоны:</b>\n"]
    for tpl in templates:
        ext = "🌍 внешнее" if tpl.is_external else "🏃 клубное"
        lines.append(f"<b>{tpl.name}</b> [{ext}]  ID: <code>{tpl.id}</code>")
        if tpl.location:
            lines.append(f"  📍 {tpl.location}")
        if tpl.distance_km:
            lines.append(f"  🏃 {tpl.distance_km} км")
        if tpl.description:
            lines.append(f"  {tpl.description}")
        lines.append(f"  ⭐ XP: +{tpl.xp_bonus} · ×{tpl.xp_multiplier}\n")

    await message.answer("\n".join(lines), reply_markup=get_templates_manage_kb())


# ── FSM создания шаблона ──────────────────────────────────────

class CreateTemplateFSM(StatesGroup):
    name          = State()
    description   = State()
    location      = State()
    distance_km   = State()
    is_external   = State()
    xp_bonus      = State()
    xp_multiplier = State()


@router.message(F.text == "➕ Создать шаблон")
async def cmd_create_template_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await state.set_state(CreateTemplateFSM.name)
    await message.answer(
        "Создаём шаблон мероприятия.\n\n"
        "<b>Шаблон хранит всё кроме даты</b> — название, описание, место, дистанцию, XP.\n"
        "При создании мероприятия по шаблону нужно указать только дату и время.\n\n"
        "Введи <b>название</b> шаблона (например «Паркран 5км»):",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.name, F.text != "❌ Отмена")
async def fsm_tpl_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(CreateTemplateFSM.description)
    await message.answer(
        "Введи <b>описание</b> мероприятия (или «-» чтобы пропустить):",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.description, F.text != "❌ Отмена")
async def fsm_tpl_description(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(description=None if raw == "-" else raw)
    await state.set_state(CreateTemplateFSM.location)
    await message.answer(
        "Введи <b>место проведения</b> (или «-» чтобы пропустить):\n"
        "<i>Например: Парк Горького, старт у главного входа</i>",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.location, F.text != "❌ Отмена")
async def fsm_tpl_location(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(location=None if raw == "-" else raw)
    await state.set_state(CreateTemplateFSM.distance_km)
    await message.answer(
        "Введи <b>дистанцию</b> в км (или «-» чтобы пропустить):",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.distance_km, F.text != "❌ Отмена")
async def fsm_tpl_distance(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    distance_km: float | None = None
    if raw != "-":
        try:
            distance_km = float(raw.replace(",", "."))
        except ValueError:
            await message.answer("Введи число (например 5.5) или «-» чтобы пропустить:")
            return
    await state.update_data(distance_km=distance_km)
    await state.set_state(CreateTemplateFSM.is_external)
    await message.answer(
        "Мероприятие <b>внешнее</b> (мы участвуем на чужом старте)?\n"
        "Ответь <b>да</b> или <b>нет</b>:",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.is_external, F.text != "❌ Отмена")
async def fsm_tpl_is_external(message: Message, state: FSMContext) -> None:
    answer = message.text.strip().lower()
    if answer not in ("да", "нет", "yes", "no"):
        await message.answer("Ответь «да» или «нет»:")
        return
    await state.update_data(is_external=answer in ("да", "yes"))
    await state.set_state(CreateTemplateFSM.xp_bonus)
    await message.answer(
        "Введи <b>XP-бонус</b> за участие (например <code>100</code>):",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.xp_bonus, F.text != "❌ Отмена")
async def fsm_tpl_xp_bonus(message: Message, state: FSMContext) -> None:
    try:
        xp_bonus = int(message.text.strip())
        assert xp_bonus >= 0
    except (ValueError, AssertionError):
        await message.answer("Введи целое положительное число, например <code>100</code>:")
        return
    await state.update_data(xp_bonus=xp_bonus)
    await state.set_state(CreateTemplateFSM.xp_multiplier)
    await message.answer(
        "Введи <b>множитель XP за км</b> (например <code>1.5</code>):",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.xp_multiplier, F.text != "❌ Отмена")
async def fsm_tpl_xp_multiplier(message: Message, state: FSMContext) -> None:
    try:
        xp_multiplier = float(message.text.strip().replace(",", "."))
        assert xp_multiplier >= 0
    except (ValueError, AssertionError):
        await message.answer("Введи число, например <code>1.5</code>:")
        return

    data = await state.get_data()
    await state.clear()

    async with async_session() as session:
        tpl = await create_event_template(
            session,
            name=data["name"],
            description=data.get("description"),
            location=data.get("location"),
            distance_km=data.get("distance_km"),
            is_external=data["is_external"],
            xp_bonus=data["xp_bonus"],
            xp_multiplier=xp_multiplier,
            created_by=message.from_user.id,
        )

    ext_label = "🌍 внешнее" if tpl.is_external else "🏃 клубное"
    summary = [f"✅ Шаблон <b>{tpl.name}</b> создан! [{ext_label}]"]
    if tpl.location:
        summary.append(f"📍 {tpl.location}")
    if tpl.distance_km:
        summary.append(f"🏃 {tpl.distance_km} км")
    summary.append(f"⭐ XP: +{tpl.xp_bonus} · ×{tpl.xp_multiplier}")
    summary.append(f"\nТеперь при создании мероприятия выбери этот шаблон — нужно будет только указать дату.")

    await message.answer("\n".join(summary), reply_markup=get_templates_manage_kb())


@router.message(F.text == "❌ Отмена", StateFilter(CreateTemplateFSM))
async def fsm_tpl_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание шаблона отменено.", reply_markup=get_admin_main_kb())


# ═══════════════════════════════════════════════════════════════
# Управление модераторами (только для администраторов)
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "👥 Модераторы")
async def cmd_manage_mods(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Управление модераторами доступно только администраторам.")
        return
    await message.answer("👥 Управление модераторами:", reply_markup=get_moderator_manage_kb())


@router.message(F.text == "📋 Список модераторов")
async def cmd_list_mods(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    async with async_session() as session:
        result = await session.execute(select(Moderator).order_by(Moderator.added_at))
        mods = result.scalars().all()

    if not mods:
        await message.answer(
            "Модераторов пока нет.\nДобавь через «➕ Добавить модератора».",
            reply_markup=get_moderator_manage_kb(),
        )
        return

    lines = ["<b>Модераторы:</b>\n"]
    for i, mod in enumerate(mods, 1):
        uname = f"@{mod.username}" if mod.username else "—"
        lines.append(
            f"{i}. {uname}\n"
            f"   ID: <code>{mod.tg_id}</code>\n"
            f"   Добавлен: {mod.added_at.strftime('%d.%m.%Y')}"
        )
    await message.answer("\n".join(lines), reply_markup=get_moderator_manage_kb())


# ── FSM добавления модератора ─────────────────────────────────

class AddModeratorFSM(StatesGroup):
    tg_id = State()


@router.message(F.text == "➕ Добавить модератора")
async def cmd_add_mod_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await state.set_state(AddModeratorFSM.tg_id)
    await message.answer(
        "Отправь <b>Telegram ID</b> пользователя или перешли любое его сообщение.\n\n"
        "<i>Узнать ID: @userinfobot</i>",
        reply_markup=get_cancel_kb(),
    )


@router.message(AddModeratorFSM.tg_id, F.text != "❌ Отмена")
async def fsm_add_mod_id(message: Message, state: FSMContext) -> None:
    if message.forward_from:
        tg_id = message.forward_from.id
        username = message.forward_from.username
    else:
        try:
            tg_id = int(message.text.strip())
            username = None
        except ValueError:
            await message.answer("Не могу распознать ID. Введи число или перешли сообщение:")
            return

    if tg_id in config.ADMIN_IDS:
        await message.answer(
            "Этот пользователь уже является администратором.",
            reply_markup=get_moderator_manage_kb(),
        )
        await state.clear()
        return

    async with async_session() as session:
        existing = await session.execute(select(Moderator).where(Moderator.tg_id == tg_id))
        if existing.scalar_one_or_none():
            await message.answer(
                f"Пользователь <code>{tg_id}</code> уже является модератором.",
                reply_markup=get_moderator_manage_kb(),
            )
            await state.clear()
            return

        session.add(Moderator(tg_id=tg_id, username=username, added_by=message.from_user.id))
        await session.commit()

    uname = f"@{username}" if username else f"ID {tg_id}"
    await message.answer(
        f"✅ Модератор <b>{uname}</b> добавлен!\n"
        f"Теперь он может одобрять отчёты и публиковать мероприятия.",
        reply_markup=get_moderator_manage_kb(),
    )
    await state.clear()


@router.message(F.text == "❌ Отмена", StateFilter(AddModeratorFSM))
async def fsm_add_mod_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=get_moderator_manage_kb())


# ── FSM удаления модератора ───────────────────────────────────

class RemoveModeratorFSM(StatesGroup):
    tg_id = State()


@router.message(F.text == "➖ Удалить модератора")
async def cmd_remove_mod_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    async with async_session() as session:
        result = await session.execute(select(Moderator).order_by(Moderator.added_at))
        mods = result.scalars().all()

    if not mods:
        await message.answer("Модераторов нет.", reply_markup=get_moderator_manage_kb())
        return

    lines = ["Введи <b>Telegram ID</b> модератора для удаления:\n"]
    for mod in mods:
        uname = f"@{mod.username}" if mod.username else "—"
        lines.append(f"• {uname} — <code>{mod.tg_id}</code>")

    await state.set_state(RemoveModeratorFSM.tg_id)
    await message.answer("\n".join(lines), reply_markup=get_cancel_kb())


@router.message(RemoveModeratorFSM.tg_id, F.text != "❌ Отмена")
async def fsm_remove_mod_id(message: Message, state: FSMContext) -> None:
    try:
        tg_id = int(message.text.strip())
    except ValueError:
        await message.answer("Введи числовой Telegram ID:")
        return

    async with async_session() as session:
        result = await session.execute(select(Moderator).where(Moderator.tg_id == tg_id))
        mod = result.scalar_one_or_none()

        if mod is None:
            await message.answer(
                f"Модератор с ID <code>{tg_id}</code> не найден.",
                reply_markup=get_moderator_manage_kb(),
            )
            await state.clear()
            return

        uname = f"@{mod.username}" if mod.username else f"ID {tg_id}"
        await session.execute(delete(Moderator).where(Moderator.tg_id == tg_id))
        await session.commit()

    await message.answer(f"✅ Модератор <b>{uname}</b> удалён.", reply_markup=get_moderator_manage_kb())
    await state.clear()


@router.message(F.text == "❌ Отмена", StateFilter(RemoveModeratorFSM))
async def fsm_remove_mod_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=get_moderator_manage_kb())