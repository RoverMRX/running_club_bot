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
        # Рефакторинг архитектуры: parent_id для дочерних челленджей участников
        "ALTER TABLE challenges ADD COLUMN parent_id INTEGER REFERENCES challenges(id)",
        # Время в отчётах (для race-челленджей)
        "ALTER TABLE reports ADD COLUMN duration_sec INTEGER",
    ]

    async with async_session() as session:
        for sql in migrations:
            try:
                await session.execute(text(sql))
                await session.commit()
            except Exception:
                # Колонка уже существует — игнорируем
                await session.rollback()

    # Миграция данных: конвертируем ChallengeParticipant → дочерние Challenge
    await _migrate_participants_to_children()


async def _migrate_participants_to_children() -> None:
    """
    Одноразовая миграция: для каждого ChallengeParticipant без дочернего Challenge
    создаём дочерний Challenge с parent_id = challenge_id участника.
    Безопасна для повторного вызова (идемпотентна).
    """
    async with async_session() as session:
        from datetime import datetime as _dt

        # Получаем всех участников у которых ещё нет дочернего челленджа
        parts_res = await session.execute(
            text("""
                SELECT cp.id, cp.challenge_id, cp.user_id, cp.joined_at,
                       cp.current_value, cp.current_runs, cp.current_time,
                       cp.penalty, cp.result, cp.closed_reason
                FROM challenge_participants cp
                WHERE NOT EXISTS (
                    SELECT 1 FROM challenges c
                    WHERE c.parent_id = cp.challenge_id
                      AND c.user_id = cp.user_id
                )
            """)
        )
        rows = parts_res.fetchall()
        if not rows:
            return

        import logging as _log
        _log.getLogger("database").info(
            "Мигрируем %d ChallengeParticipant → дочерние Challenge", len(rows)
        )

        for row in rows:
            (part_id, ch_id, user_id, joined_at,
             cur_val, cur_runs, cur_time,
             penalty, result, closed_reason) = row

            # Получаем родительский челлендж
            parent_res = await session.execute(
                text("SELECT * FROM challenges WHERE id = :id"), {"id": ch_id}
            )
            parent = parent_res.fetchone()
            if not parent:
                continue

            # Рассчитываем дедлайн дочернего: длительность оригинала от даты вступления
            child_deadline = None
            if parent.deadline and parent.started_at:
                try:
                    p_deadline = _dt.fromisoformat(str(parent.deadline))
                    p_started  = _dt.fromisoformat(str(parent.started_at))
                    duration   = p_deadline - p_started
                    joined     = _dt.fromisoformat(str(joined_at)) if joined_at else _dt.now()
                    child_deadline = joined + duration
                except Exception:
                    pass

            # Определяем is_active: если result уже есть — неактивен
            is_active = result is None

            await session.execute(
                text("""
                    INSERT INTO challenges
                        (user_id, title, ch_type,
                         min_per_run, min_minutes_per_run, goal_runs, goal_value, goal_time,
                         current_value, current_runs, current_time,
                         penalty, is_public, is_active,
                         started_at, deadline,
                         close_requested, pause_requested, result, frozen_at,
                         parent_id, created_at)
                    VALUES
                        (:user_id, :title, :ch_type,
                         :min_per_run, :min_minutes_per_run, :goal_runs, :goal_value, :goal_time,
                         :current_value, :current_runs, :current_time,
                         :penalty, 0, :is_active,
                         :started_at, :deadline,
                         0, 0, :result, NULL,
                         :parent_id, :created_at)
                """),
                {
                    "user_id":             user_id,
                    "title":               parent.title,
                    "ch_type":             parent.ch_type,
                    "min_per_run":         getattr(parent, "min_per_run", None) or 0.0,
                    "min_minutes_per_run": getattr(parent, "min_minutes_per_run", None) or 0,
                    "goal_runs":           getattr(parent, "goal_runs", None) or 0,
                    "goal_value":          getattr(parent, "goal_value", None) or 0.0,
                    "goal_time":           getattr(parent, "goal_time", None),
                    "current_value":       cur_val or 0.0,
                    "current_runs":        cur_runs or 0,
                    "current_time":        cur_time or 0,
                    "penalty":             penalty,
                    "is_active":           1 if is_active else 0,
                    "started_at":          joined_at,
                    "deadline":            child_deadline.isoformat() if child_deadline else None,
                    "result":              result,
                    "parent_id":           ch_id,
                    "created_at":          joined_at,
                }
            )

        await session.commit()
        _log.getLogger("database").info("Миграция ChallengeParticipant завершена.")