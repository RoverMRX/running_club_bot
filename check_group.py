# check_group.py
import asyncio
import config
from aiogram import Bot

async def main():
    bot = Bot(token=config.BOT_TOKEN)
    try:
        chat = await bot.get_chat(config.GROUP_ID)
        print(f"✅ Группа найдена: {chat.title}")
        print(f"   Тип: {chat.type}")
        me = await bot.get_me()
        member = await bot.get_chat_member(config.GROUP_ID, me.id)
        print(f"   Статус бота в группе: {member.status}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

asyncio.run(main())