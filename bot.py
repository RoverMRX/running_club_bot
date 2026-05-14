import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from sqlalchemy import select

from config import config
from models import Base, User
from database import engine, async_session
from keyboards import get_main_kb
import handlers

logging.basicConfig(level=logging.INFO)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def cmd_start(message: types.Message):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            new_user = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name
            )
            session.add(new_user)
            await session.commit()
            text = f"Привет, {message.from_user.first_name}! Ты в системе."
        else:
            text = f"С возвращением, {message.from_user.first_name}!"

    await message.answer(text, reply_markup=get_main_kb())

async def main():
    await init_db()
    bot_session = AiohttpSession(proxy=config.PROXY_URL)
    bot = Bot(token=config.BOT_TOKEN, session=bot_session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    # Регистрация
    dp.message.register(cmd_start, Command("start"))
    dp.include_router(handlers.router)

    print(f"🚀 Бот @{(await bot.get_me()).username} запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())