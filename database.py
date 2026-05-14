from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from models import Base
import config

engine = create_async_engine(config.DB_URL, echo=False)

# async_sessionmaker — более современный способ (SQLAlchemy 2.0+)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)