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
        # vote_message_id — для снятия кнопок после апрува
        "ALTER TABLE reports ADD COLUMN vote_message_id INTEGER",
        "ALTER TABLE challenge_participants ADD COLUMN penalty TEXT",
        # tournament_id уже есть в модели, но мог быть создан без него
        "ALTER TABLE reports ADD COLUMN tournament_id_v2 INTEGER",  # noqa: не нужна, просто guard
        # close_requested и очередь уведомлений
        "ALTER TABLE challenges ADD COLUMN close_requested BOOLEAN DEFAULT 0",
        "ALTER TABLE challenges ADD COLUMN pause_requested BOOLEAN DEFAULT 0",
        "ALTER TABLE challenges ADD COLUMN pause_reason TEXT",
        "ALTER TABLE challenge_participants ADD COLUMN result TEXT",
        "ALTER TABLE challenge_participants ADD COLUMN closed_reason TEXT",
        "ALTER TABLE challenge_participants ADD COLUMN close_requested BOOLEAN DEFAULT 0",
        "ALTER TABLE challenge_participants ADD COLUMN pause_requested BOOLEAN DEFAULT 0",
        "ALTER TABLE challenges ADD COLUMN result TEXT",
        "ALTER TABLE challenges ADD COLUMN frozen_at DATETIME",
        "CREATE TABLE IF NOT EXISTS pending_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_tg_id INTEGER NOT NULL, text TEXT NOT NULL, kb_json TEXT, created_at DATETIME, sent BOOLEAN DEFAULT 0)",
    ]

    async with async_session() as session:
        for sql in migrations:
            try:
                await session.execute(text(sql))
                await session.commit()
            except Exception:
                # Колонка уже существует — игнорируем
                await session.rollback()