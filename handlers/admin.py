"""handlers/admin.py — шаблоны мероприятий и управление модераторами."""

from __future__ import annotations

from aiogram.enums import ChatType
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
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
router.message.filter(F.chat.type == ChatType.PRIVATE)

WEBAPP_URL = "https://run.archer-srv.ru"


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ═══════════════════════════════════════════════════════════════
# Панель администрирования
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "⚙️ Администрирование")
async def cmd_admin_panel(message: Message) -> None:
    from services.events import is_moderator
    user_id = message.from_user.id

    async with async_session() as session:
        is_mod = await is_moderator(session, user_id)

    if not (_is_admin(user_id) or is_mod):
        return

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


# ═══════════════════════════════════════════════════════════════
# Шаблоны мероприятий
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
        "Создаём шаблон мероприятия.\n\nВведи <b>название</b> шаблона:",
        reply_markup=get_cancel_kb(),
    )


@router.message(CreateTemplateFSM.name, F.text != "❌ Отмена")
async def fsm_tpl_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(CreateTemplateFSM.description)
    await message.answer("Введи <b>описание</b> (или «-»):", reply_markup=get_cancel_kb())


@router.message(CreateTemplateFSM.description, F.text != "❌ Отмена")
async def fsm_tpl_description(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(description=None if raw == "-" else raw)
    await state.set_state(CreateTemplateFSM.location)
    await message.answer("Введи <b>место проведения</b> (или «-»):", reply_markup=get_cancel_kb())


@router.message(CreateTemplateFSM.location, F.text != "❌ Отмена")
async def fsm_tpl_location(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(location=None if raw == "-" else raw)
    await state.set_state(CreateTemplateFSM.distance_km)
    await message.answer("Введи <b>дистанцию</b> в км (или «-»):", reply_markup=get_cancel_kb())


@router.message(CreateTemplateFSM.distance_km, F.text != "❌ Отмена")
async def fsm_tpl_distance(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    distance_km: float | None = None
    if raw != "-":
        try:
            distance_km = float(raw.replace(",", "."))
        except ValueError:
            await message.answer("Введи число или «-»:")
            return
    await state.update_data(distance_km=distance_km)
    await state.set_state(CreateTemplateFSM.is_external)
    await message.answer("Мероприятие внешнее? Ответь <b>да</b> или <b>нет</b>:", reply_markup=get_cancel_kb())


@router.message(CreateTemplateFSM.is_external, F.text != "❌ Отмена")
async def fsm_tpl_is_external(message: Message, state: FSMContext) -> None:
    answer = message.text.strip().lower()
    if answer not in ("да", "нет", "yes", "no"):
        await message.answer("Ответь «да» или «нет»:")
        return
    await state.update_data(is_external=answer in ("да", "yes"))
    await state.set_state(CreateTemplateFSM.xp_bonus)
    await message.answer("Введи <b>XP-бонус</b> (например <code>100</code>):", reply_markup=get_cancel_kb())


@router.message(CreateTemplateFSM.xp_bonus, F.text != "❌ Отмена")
async def fsm_tpl_xp_bonus(message: Message, state: FSMContext) -> None:
    try:
        xp_bonus = int(message.text.strip())
        assert xp_bonus >= 0
    except (ValueError, AssertionError):
        await message.answer("Введи целое положительное число:")
        return
    await state.update_data(xp_bonus=xp_bonus)
    await state.set_state(CreateTemplateFSM.xp_multiplier)
    await message.answer("Введи <b>множитель XP за км</b> (например <code>1.5</code>):", reply_markup=get_cancel_kb())


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
    await message.answer(
        f"✅ Шаблон <b>{tpl.name}</b> создан! [{ext_label}]\n"
        f"⭐ XP: +{tpl.xp_bonus} · ×{tpl.xp_multiplier}",
        reply_markup=get_templates_manage_kb(),
    )


@router.message(F.text == "❌ Отмена", StateFilter(CreateTemplateFSM))
async def fsm_tpl_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание шаблона отменено.", reply_markup=get_admin_main_kb())


# ═══════════════════════════════════════════════════════════════
# Управление модераторами
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "👥 Модераторы")
async def cmd_manage_mods(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Только для администраторов.")
        return
    await message.answer("👥 Управление модераторами:", reply_markup=get_moderator_manage_kb())


@router.message(F.text == "📋 Список модераторов")
async def cmd_list_mods(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    async with async_session() as session:
        result = await session.execute(select(Moderator).order_by(Moderator.added_at))
        mods = result.scalars().all()

    if not mods:
        await message.answer("Модераторов пока нет.", reply_markup=get_moderator_manage_kb())
        return

    lines = ["<b>Модераторы:</b>\n"]
    for i, mod in enumerate(mods, 1):
        uname = f"@{mod.username}" if mod.username else "—"
        lines.append(f"{i}. {uname} — <code>{mod.tg_id}</code>")
    await message.answer("\n".join(lines), reply_markup=get_moderator_manage_kb())


class AddModeratorFSM(StatesGroup):
    tg_id = State()


@router.message(F.text == "➕ Добавить модератора")
async def cmd_add_mod_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(AddModeratorFSM.tg_id)
    await message.answer(
        "Отправь <b>Telegram ID</b> или перешли сообщение пользователя.\n<i>Узнать ID: @userinfobot</i>",
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
        await message.answer("Этот пользователь уже администратор.", reply_markup=get_moderator_manage_kb())
        await state.clear()
        return

    async with async_session() as session:
        existing = await session.execute(select(Moderator).where(Moderator.tg_id == tg_id))
        if existing.scalar_one_or_none():
            await message.answer(f"<code>{tg_id}</code> уже модератор.", reply_markup=get_moderator_manage_kb())
            await state.clear()
            return
        session.add(Moderator(tg_id=tg_id, username=username, added_by=message.from_user.id))
        await session.commit()

    uname = f"@{username}" if username else f"ID {tg_id}"
    await message.answer(f"✅ Модератор <b>{uname}</b> добавлен!", reply_markup=get_moderator_manage_kb())
    await state.clear()


@router.message(F.text == "❌ Отмена", StateFilter(AddModeratorFSM))
async def fsm_add_mod_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=get_moderator_manage_kb())


class RemoveModeratorFSM(StatesGroup):
    tg_id = State()


@router.message(F.text == "➖ Удалить модератора")
async def cmd_remove_mod_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
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
            await message.answer(f"Модератор <code>{tg_id}</code> не найден.", reply_markup=get_moderator_manage_kb())
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


# ═══════════════════════════════════════════════════════════════
# Утилиты для группы
# ═══════════════════════════════════════════════════════════════

@router.message(Command("cleanup_kb"))
async def cmd_cleanup_kb(message: Message) -> None:
    """Убрать старую Reply-клавиатуру из группы."""
    if not _is_admin(message.from_user.id):
        return
    from aiogram.types import ReplyKeyboardRemove
    await message.bot.send_message(
        config.GROUP_ID,
        ".",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Клавиатура сброшена в группе.")


@router.message(Command("post_app"))
async def cmd_post_app(message: Message) -> None:
    """
    Опубликовать кнопку Mini App в группе.

    ВАЖНО: Telegram запрещает web_app-кнопки в группах (BUTTON_TYPE_INVALID).
    Поэтому используем обычную url-кнопку — она открывает браузер,
    а не встроенный WebApp, то есть initData от Telegram не будет.

    Правильный способ для группы: попросить участников открыть бота
    в личке и нажать кнопку меню там — тогда initData будет корректным.
    """
    if not _is_admin(message.from_user.id):
        return

    bot_username = (await message.bot.get_me()).username

    # url-кнопка открывает личку с ботом — там уже есть кнопка меню с WebApp
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🏃 IT БЕГОТНЯ — открыть",
            url=f"https://t.me/{bot_username}",
        )
    ]])
    await message.bot.send_message(
        config.GROUP_ID,
        "🏃 <b>IT БЕГОТНЯ 21</b>\n"
        "Нажми кнопку, перейди в личку бота и открой приложение кнопкой меню.",
        reply_markup=kb,
    )
    await message.answer("✅ Опубликовано в группе.")




# ═══════════════════════════════════════════════════════════════
# Запросы по челленджам (завершение / пауза / разморозка)
# ═══════════════════════════════════════════════════════════════

@router.message(F.text == "🎯 Запросы по челленджам")
async def cmd_challenge_requests(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    from models import Challenge, User
    from sqlalchemy import select, or_

    async with async_session() as session:
        res = await session.execute(
            select(Challenge, User)
            .join(User, User.tg_id == Challenge.user_id)
            .where(
                Challenge.is_active == True,
                or_(
                    Challenge.close_requested == True,
                    Challenge.pause_requested == True,
                    Challenge.pause_until != None,
                )
            )
            .order_by(Challenge.created_at.desc())
        )
        rows = list(res.all())

    if not rows:
        await message.answer(
            "✅ Нет активных запросов по челленджам.",
            reply_markup=get_admin_main_kb(),
        )
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    await message.answer(
        f"🎯 <b>Запросы по челленджам</b> ({len(rows)} шт.)\n\nВыбери запрос:",
        reply_markup=get_admin_main_kb(),
    )

    for ch, user in rows:
        author = f"@{user.username}" if user.username else user.school_nick
        if ch.ch_type == "weekly_runs":
            progress = f"{ch.current_runs} пробежек"
        else:
            progress = f"{ch.current_value:.1f} / {ch.goal_value:.1f} км"

        req_type = []
        if ch.close_requested:
            req_type.append("🏁 завершение")
        if ch.pause_requested:
            reason_str = f" (причина: {ch.pause_reason})" if ch.pause_reason else ""
            req_type.append(f"⏸ пауза{reason_str}")

        text = (
            f"<b>{ch.title}</b>\n"
            f"Автор: {author}\n"
            f"Прогресс: {progress}\n"
            f"Запросы: {', '.join(req_type)}"
        )

        builder = InlineKeyboardBuilder()
        if ch.close_requested:
            builder.button(text="✅ Разрешить завершение", callback_data=f"ch_close_ok:{ch.id}")
            builder.button(text="❌ Отказать в завершении", callback_data=f"ch_close_no:{ch.id}")
        if ch.pause_requested:
            builder.button(text="⏸ Одобрить паузу",  callback_data=f"ch_pause_ok:{ch.id}")
            builder.button(text="❌ Отказать в паузе", callback_data=f"ch_pause_no:{ch.id}")
        if ch.pause_until and ch.pause_until > __import__("datetime").datetime.now():
            builder.button(text="▶️ Разморозить сейчас", callback_data=f"ch_unfreeze_ok:{ch.id}")
        builder.adjust(2)

        await message.answer(text, reply_markup=builder.as_markup())
@router.message(Command("set_menu_button"))
async def cmd_set_menu_button(message: Message) -> None:
    """Установить / обновить кнопку меню бота (синяя кнопка в личном чате)."""
    if not _is_admin(message.from_user.id):
        return
    from aiogram.types import MenuButtonWebApp
    try:
        await message.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🏃 Открыть",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        )
        await message.answer(f"✅ Кнопка меню обновлена.\nURL: {WEBAPP_URL}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Управление челленджами (удаление)
# ─────────────────────────────────────────────────────────────────────────────

@router.message(F.text == "🗑 Управление челленджами")
async def cmd_manage_challenges(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    from sqlalchemy import select as _sel
    from models import Challenge as _Ch
    from database import async_session as _sess

    async with _sess() as session:
        # Показываем только активные корневые челленджи
        res = await session.execute(
            _sel(_Ch).where(
                _Ch.parent_id.is_(None),
                _Ch.is_active == True,
            )
            .order_by(_Ch.created_at.desc())
            .limit(30)
        )
        challenges = res.scalars().all()

    if not challenges:
        await message.answer("Нет челленджей.", reply_markup=get_admin_main_kb())
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for ch in challenges:
        status = "🟢" if ch.is_active else "⚫"
        result_label = f" [{ch.result}]" if ch.result else ""
        kb.button(
            text=f"{status} {ch.title}{result_label} (id={ch.id})",
            callback_data=f"adm_ch_info:{ch.id}"
        )
    kb.adjust(1)

    await message.answer(
        "🗑 <b>Управление челленджами</b>\n\n"
        "🟢 — активный · ⚫ — завершён\n\n"
        "Выбери челлендж:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("adm_ch_info:"))
async def cb_adm_ch_info(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    ch_id = int(call.data.split(":")[1])

    from sqlalchemy import select as _sel, func as _func
    from models import Challenge as _Ch
    from database import async_session as _sess

    async with _sess() as session:
        res = await session.execute(_sel(_Ch).where(_Ch.id == ch_id))
        ch = res.scalar_one_or_none()
        if not ch:
            await call.answer("Не найден.", show_alert=True)
            return

        # Считаем дочерние
        cnt = await session.execute(
            _sel(_func.count(_Ch.id)).where(_Ch.parent_id == ch_id)
        )
        participants_count = cnt.scalar() or 0

        active_cnt = await session.execute(
            _sel(_func.count(_Ch.id)).where(
                _Ch.parent_id == ch_id, _Ch.is_active == True
            )
        )
        active_count = active_cnt.scalar() or 0

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()

    if ch.is_active:
        kb.button(text="⛔ Деактивировать (скрыть)", callback_data=f"adm_ch_deactivate:{ch_id}")
    else:
        kb.button(text="✅ Активировать", callback_data=f"adm_ch_activate:{ch_id}")

    kb.button(text="🗑 Удалить полностью", callback_data=f"adm_ch_delete_ask:{ch_id}")
    kb.button(text="❌ Закрыть", callback_data="adm_ch_close_menu")
    kb.adjust(1)

    status = "🟢 Активный" if ch.is_active else f"⚫ Завершён [{ch.result or '—'}]"
    deadline_str = ch.deadline.strftime("%d.%m.%Y") if ch.deadline else "бессрочно"

    await call.message.edit_text(
        f"<b>{ch.title}</b> (id={ch.id})\n\n"
        f"Тип: {ch.ch_type}\n"
        f"Статус: {status}\n"
        f"Дедлайн: {deadline_str}\n"
        f"Участников всего: {participants_count} · активных: {active_count}\n\n"
        f"Выбери действие:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_ch_deactivate:"))
async def cb_adm_ch_deactivate(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    ch_id = int(call.data.split(":")[1])
    from sqlalchemy import select as _sel
    from models import Challenge as _Ch
    from database import async_session as _sess

    async with _sess() as session:
        async with session.begin():
            res = await session.execute(_sel(_Ch).where(_Ch.id == ch_id))
            ch = res.scalar_one_or_none()
            if ch:
                ch.is_active = False
                ch.result = "closed"

    await call.message.edit_text(
        call.message.text + "\n\n⚫ <b>Деактивирован.</b>",
        parse_mode="HTML"
    )
    await call.answer("Челлендж деактивирован.")


@router.callback_query(F.data.startswith("adm_ch_activate:"))
async def cb_adm_ch_activate(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    ch_id = int(call.data.split(":")[1])
    from sqlalchemy import select as _sel
    from models import Challenge as _Ch
    from database import async_session as _sess

    async with _sess() as session:
        async with session.begin():
            res = await session.execute(_sel(_Ch).where(_Ch.id == ch_id))
            ch = res.scalar_one_or_none()
            if ch:
                ch.is_active = True
                ch.result = None

    await call.message.edit_text(
        call.message.text + "\n\n🟢 <b>Активирован.</b>",
        parse_mode="HTML"
    )
    await call.answer("Челлендж активирован.")


@router.callback_query(F.data.startswith("adm_ch_delete_ask:"))
async def cb_adm_ch_delete_ask(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    ch_id = int(call.data.split(":")[1])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⚠️ Да, удалить", callback_data=f"adm_ch_delete_confirm:{ch_id}")
    kb.button(text="❌ Отмена", callback_data=f"adm_ch_info:{ch_id}")
    kb.adjust(2)

    await call.message.edit_text(
        "⚠️ <b>Удалить челлендж полностью?</b>\n\n"
        "Удалятся сам челлендж и все дочерние (участники).\n"
        "Отчёты участников <b>сохранятся</b>.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_ch_delete_confirm:"))
async def cb_adm_ch_delete_confirm(call: CallbackQuery) -> None:
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    ch_id = int(call.data.split(":")[1])
    from sqlalchemy import select as _sel, delete as _del
    from models import Challenge as _Ch
    from database import async_session as _sess

    async with _sess() as session:
        async with session.begin():
            # Сначала удаляем дочерние
            await session.execute(_del(_Ch).where(_Ch.parent_id == ch_id))
            # Затем сам челлендж
            await session.execute(_del(_Ch).where(_Ch.id == ch_id))

    await call.message.edit_text(
        "🗑 <b>Челлендж удалён.</b>",
        parse_mode="HTML"
    )
    await call.answer("Удалено.")


@router.callback_query(F.data == "adm_ch_close_menu")
async def cb_adm_ch_close_menu(call: CallbackQuery) -> None:
    await call.message.delete()
    await call.answer()
