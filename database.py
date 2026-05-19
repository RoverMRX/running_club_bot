from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from models import Base
import config

engine = create_async_engine(config.DB_URL, echo=False)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Создаёт все таблицы и накатывает миграции для старых БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Миграции: добавляем новые колонки если их ещё нет
    migrations = [
        # EventTemplate: место и дистанция теперь хранятся в шаблоне
        "ALTER TABLE event_templates ADD COLUMN location TEXT",
        "ALTER TABLE event_templates ADD COLUMN distance_km REAL",
        # Event: флаг ожидания модерации
        "ALTER TABLE events ADD COLUMN is_pending BOOLEAN DEFAULT 1",
    ]

    async with async_session() as session:
        for sql in migrations:
            try:
                await session.execute(text(sql))
                await session.commit()
            except Exception:
                # Колонка уже существует — игнорируем
                await session.rollback()