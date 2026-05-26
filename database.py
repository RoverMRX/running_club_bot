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
        # Ачивменты
        """CREATE TABLE IF NOT EXISTS achievements (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            image_url TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS user_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_tg_id INTEGER NOT NULL,
            slug TEXT NOT NULL REFERENCES achievements(slug),
            earned_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_user_ach ON user_achievements(user_tg_id)",
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
    # Заполняем справочник ачивментов (идемпотентно)
    await _seed_achievements()
    # Ретроактивно выдаём ачивки по историческим данным
    await _backfill_achievements()


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


async def _seed_achievements() -> None:
    """Заполняет справочник ачивментов. Добавляет только отсутствующие."""
    ACHIEVEMENTS = [
        # slug, name, description, category
        # км
        ("km_1",       "Первый километр",      "Суммарно пробежал 1 км",                         "km"),
        ("km_10",      "10 км в копилке",       "Суммарно пробежал 10 км",                        "km"),
        ("km_100",     "Сотня",                 "Суммарно пробежал 100 км",                       "km"),
        ("km_500",     "Полтысячи",             "Суммарно пробежал 500 км",                       "km"),
        ("km_1000",    "Тысячник",              "Суммарно пробежал 1000 км",                      "km"),
        ("km_5000",    "Легенда",               "Суммарно пробежал 5000 км",                      "km"),
        # стрик
        ("streak_1",   "Первая неделя",         "Стрик 1 неделя",                                 "streak"),
        ("streak_4",   "Месяц без остановок",   "Стрик 4 недели подряд",                          "streak"),
        ("streak_12",  "Квартал",               "Стрик 12 недель подряд",                         "streak"),
        ("streak_24",  "Полгода",               "Стрик 24 недели подряд",                         "streak"),
        ("streak_52",  "Год бега",              "Стрик 52 недели подряд",                         "streak"),
        # PR
        ("pr_5",       "5 км покорены",         "Одна пробежка ≥ 5 км",                           "pr"),
        ("pr_10",      "Десятка",               "Одна пробежка ≥ 10 км",                          "pr"),
        ("pr_half",    "Полумарафон",           "Одна пробежка ≥ 21.1 км",                        "pr"),
        ("pr_marathon","Марафон",               "Одна пробежка ≥ 42.2 км",                        "pr"),
        # события
        ("first_report",    "Первый отчёт",     "Первый одобренный отчёт о пробежке",             "event"),
        ("first_event",     "Первое мероприятие","Первое посещённое клубное мероприятие",         "event"),
        ("first_challenge", "Первый челлендж",  "Создал или вступил в первый челлендж",           "event"),
        # турниры
        ("tournament_gold", "Золото",           "Первое место в турнире",                         "tournament"),
        ("tournament_hat",  "Хет-трик",         "Три победы в турнирах",                          "tournament"),
        # особые
        ("early_bird",  "Ранняя пташка",        "Пробежка с отчётом до 07:00 🌅",                "special"),
        ("night_owl",   "Ночной бегун",         "Пробежка с отчётом после 22:00 🌙",             "special"),
        ("winter_run",  "Зимний воин",          "Пробежка в декабре, январе или феврале ❄️",     "special"),
    ]

    async with async_session() as session:
        for slug, name, description, category in ACHIEVEMENTS:
            existing = await session.execute(
                text("SELECT slug FROM achievements WHERE slug = :slug"), {"slug": slug}
            )
            if not existing.fetchone():
                await session.execute(
                    text("""INSERT INTO achievements (slug, name, description, category, image_url)
                            VALUES (:slug, :name, :desc, :cat, :url)"""),
                    {
                        "slug": slug,
                        "name": name,
                        "desc": description,
                        "cat":  category,
                        "url":  f"/achievements/{slug}.png",
                    }
                )
        await session.commit()


async def _backfill_achievements() -> None:
    """
    Ретроактивно выдаёт ачивки по существующим данным.
    Запускается при каждом старте, но идемпотентна — не дублирует.
    """
    import logging as _log
    logger = _log.getLogger("database")

    async with async_session() as session:
        # Получаем всех пользователей у кого есть одобренные отчёты
        from sqlalchemy import select as _sel, func as _func
        users_res = await session.execute(
            text("SELECT DISTINCT user_tg_id FROM reports WHERE is_approved=1")
        )
        user_ids = [r[0] for r in users_res.fetchall()]

    if not user_ids:
        return

    logger.info("Backfill ачивментов для %d пользователей", len(user_ids))

    from services.achievements import check_and_grant as _check
    from models import User as _User, Report as _Report, UserAchievement as _UA

    for uid in user_ids:
        try:
            async with async_session() as session:
                # Суммарный пробег
                total_res = await session.execute(
                    text("SELECT COALESCE(SUM(km),0) FROM reports WHERE user_tg_id=:u AND is_approved=1"),
                    {"u": uid}
                )
                total_km = float(total_res.scalar() or 0)

                # Максимальная пробежка
                max_res = await session.execute(
                    text("SELECT COALESCE(MAX(km),0) FROM reports WHERE user_tg_id=:u AND is_approved=1"),
                    {"u": uid}
                )
                max_km = float(max_res.scalar() or 0)

                # Стрик
                user_res = await session.execute(
                    text("SELECT streak FROM users WHERE tg_id=:u"), {"u": uid}
                )
                row = user_res.fetchone()
                streak = int(row[0] or 0) if row else 0

                # Кол-во отчётов
                cnt_res = await session.execute(
                    text("SELECT COUNT(*) FROM reports WHERE user_tg_id=:u AND is_approved=1"),
                    {"u": uid}
                )
                report_count = cnt_res.scalar() or 0

                # Ранние/ночные/зимние пробежки из created_at
                early_res = await session.execute(
                    text("SELECT COUNT(*) FROM reports WHERE user_tg_id=:u AND is_approved=1 AND CAST(strftime('%H', created_at) AS INT) < 7"),
                    {"u": uid}
                )
                has_early = (early_res.scalar() or 0) > 0

                night_res = await session.execute(
                    text("SELECT COUNT(*) FROM reports WHERE user_tg_id=:u AND is_approved=1 AND CAST(strftime('%H', created_at) AS INT) >= 22"),
                    {"u": uid}
                )
                has_night = (night_res.scalar() or 0) > 0

                winter_res = await session.execute(
                    text("SELECT COUNT(*) FROM reports WHERE user_tg_id=:u AND is_approved=1 AND CAST(strftime('%m', created_at) AS INT) IN (12,1,2)"),
                    {"u": uid}
                )
                has_winter = (winter_res.scalar() or 0) > 0

                # Уже выданные ачивки
                earned_res = await session.execute(
                    text("SELECT slug FROM user_achievements WHERE user_tg_id=:u"), {"u": uid}
                )
                already = {r[0] for r in earned_res.fetchall()}

            # Выдаём недостающие
            to_grant = []

            for threshold, slug in [(1,"km_1"),(10,"km_10"),(100,"km_100"),(500,"km_500"),(1000,"km_1000"),(5000,"km_5000")]:
                if total_km >= threshold and slug not in already:
                    to_grant.append(slug)

            for threshold, slug in [(5,"pr_5"),(10,"pr_10"),(21.1,"pr_half"),(42.2,"pr_marathon")]:
                if max_km >= threshold and slug not in already:
                    to_grant.append(slug)

            for weeks, slug in [(1,"streak_1"),(4,"streak_4"),(12,"streak_12"),(24,"streak_24"),(52,"streak_52")]:
                if streak >= weeks and slug not in already:
                    to_grant.append(slug)

            if report_count >= 1 and "first_report" not in already:
                to_grant.append("first_report")
            if has_early and "early_bird" not in already:
                to_grant.append("early_bird")
            if has_night and "night_owl" not in already:
                to_grant.append("night_owl")
            if has_winter and "winter_run" not in already:
                to_grant.append("winter_run")

            if to_grant:
                async with async_session() as session:
                    async with session.begin():
                        for slug in to_grant:
                            session.add(__import__('models').UserAchievement(
                                user_tg_id=uid, slug=slug
                            ))
                logger.info("Backfill: выдано %d ачивок для %s", len(to_grant), uid)

        except Exception as e:
            logger.warning("Backfill error for %s: %s", uid, e)

    logger.info("Backfill ачивментов завершён")
