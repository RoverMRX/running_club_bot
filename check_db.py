import asyncio
from sqlalchemy import select
from database import async_session
from models import User

async def main():
    async with async_session() as session:
        res = await session.execute(select(User))
        users = res.scalars().all()
        if not users:
            print("База пустая — пользователей нет")
        for u in users:
            print(f"{u.tg_id} | {u.school_nick} | {u.full_name} | XP:{u.xp} | Level:{u.level}")

asyncio.run(main())