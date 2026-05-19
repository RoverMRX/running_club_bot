"""
test_bot.py — скрипт ручного тестирования IT БЕГОТНЯ 21.

Запуск:
    python test_bot.py                  # все тесты
    python test_bot.py tournaments      # только турниры
    python test_bot.py digest           # только дайджест
    python test_bot.py digest --send    # дайджест + отправить в Telegram

Работает без живого бота — использует in-memory SQLite.
Для --send нужен BOT_TOKEN и GROUP_ID в .env.
"""

import asyncio
import sys
from datetime import datetime, timedelta

# ── Подменяем БД на in-memory ДО импорта приложения ───────────
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

_test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_test_session_factory = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)

# Патчим database.py
import database as _db_module
_db_module.engine = _test_engine
_db_module.async_session = _test_session_factory

# Теперь импортируем модели и сервисы
from models import Base, User, Challenge, Report, WeeklyTournament, TournamentParticipant
from services import tournaments as t_svc
from services import digest as d_svc
import config


# ─────────────────────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────────────────────

PASS = "✅"
FAIL = "❌"
results: list[tuple[str, str, str]] = []  # (suite, name, status)


def _ok(suite: str, name: str):
    results.append((suite, name, PASS))
    print(f"  {PASS} {name}")


def _fail(suite: str, name: str, reason: str = ""):
    results.append((suite, name, FAIL))
    print(f"  {FAIL} {name}" + (f" — {reason}" if reason else ""))


async def _setup_db():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _teardown_db():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


async def _make_user(tg_id: int, nick: str) -> User:
    async with _test_session_factory() as s:
        async with s.begin():
            u = User(tg_id=tg_id, school_nick=nick, username=nick, xp=0, level=0,
                     season_xp=0, streak=0)
            s.add(u)
    async with _test_session_factory() as s:
        from sqlalchemy import select
        r = await s.execute(select(User).where(User.tg_id == tg_id))
        return r.scalar_one()


async def _make_report(user_tg_id: int, km: float, approved: bool = True) -> Report:
    async with _test_session_factory() as s:
        async with s.begin():
            rep = Report(
                message_id=abs(hash((user_tg_id, km, datetime.now().timestamp()))),
                chat_id=-100123,
                user_tg_id=user_tg_id,
                km=km,
                is_approved=approved,
                created_at=datetime.now(),
            )
            s.add(rep)
            await s.flush()
            rep_id = rep.id
    async with _test_session_factory() as s:
        from sqlalchemy import select
        r = await s.execute(select(Report).where(Report.id == rep_id))
        return r.scalar_one()


# ─────────────────────────────────────────────────────────────
# SUITE: Турниры
# ─────────────────────────────────────────────────────────────

async def test_tournaments():
    suite = "tournaments"
    print("\n🏆 ТЕСТ: Турниры")

    await _teardown_db()
    await _setup_db()

    # Создаём пользователей
    u1 = await _make_user(1001, "runner_a")
    u2 = await _make_user(1002, "runner_b")
    u3 = await _make_user(1003, "runner_c")

    # 1. Создание турнира
    tour = await t_svc.create_tournament("Тест-турнир", "km", created_by=9999, duration_days=7)
    if tour and tour.id and tour.is_active:
        _ok(suite, "create_tournament: создан и активен")
    else:
        _fail(suite, "create_tournament: создан и активен")
        return

    # 2. Получение активного турнира
    active = await t_svc.get_active_tournament()
    if active and active.id == tour.id:
        _ok(suite, "get_active_tournament: находит созданный")
    else:
        _fail(suite, "get_active_tournament: находит созданный")

    # 3. Регистрация участников
    r1 = await t_svc.join_tournament(tour.id, 1001)
    if r1 == {"ok": True}:
        _ok(suite, "join_tournament: первая регистрация OK")
    else:
        _fail(suite, "join_tournament: первая регистрация OK", str(r1))

    r2 = await t_svc.join_tournament(tour.id, 1002)
    r3 = await t_svc.join_tournament(tour.id, 1003)

    # 4. Дубль
    r_dup = await t_svc.join_tournament(tour.id, 1001)
    if r_dup.get("error") == "already_joined":
        _ok(suite, "join_tournament: дубль → already_joined")
    else:
        _fail(suite, "join_tournament: дубль → already_joined", str(r_dup))

    # 5. is_participant
    if await t_svc.is_participant(tour.id, 1001):
        _ok(suite, "is_participant: True для участника")
    else:
        _fail(suite, "is_participant: True для участника")

    if not await t_svc.is_participant(tour.id, 9999):
        _ok(suite, "is_participant: False для чужого")
    else:
        _fail(suite, "is_participant: False для чужого")

    # 6. Обновление очков
    await t_svc.update_score(tour.id, 1001, km=10.0)
    await t_svc.update_score(tour.id, 1001, km=5.5)
    await t_svc.update_score(tour.id, 1002, km=20.0)
    await t_svc.update_score(tour.id, 1003, km=3.0)

    lb = await t_svc.get_leaderboard(tour.id)
    if lb[0]["user_tg_id"] == 1002 and abs(lb[0]["score"] - 20.0) < 0.01:
        _ok(suite, "update_score + leaderboard: лидер верный (runner_b 20 км)")
    else:
        _fail(suite, "update_score + leaderboard: лидер верный", str(lb[:2]))

    if abs(lb[1]["score"] - 15.5) < 0.01:
        _ok(suite, "update_score: суммирование (runner_a 10+5.5=15.5 км)")
    else:
        _fail(suite, "update_score: суммирование", f"got {lb[1]['score']}")

    # 7. Финализация — турнир активен, end_date в будущем, принудительно финализируем
    result = await t_svc.finalize_tournament(tour.id)
    if "error" not in result and result["placements"]:
        _ok(suite, "finalize_tournament: вернул placements")
    else:
        _fail(suite, "finalize_tournament: вернул placements", str(result))

    # Победитель — runner_b (20 км)
    winner = result["placements"][0]
    if winner["user_tg_id"] == 1002 and winner["xp"] == 250:
        _ok(suite, "finalize: 1 место верное + 250 XP")
    else:
        _fail(suite, "finalize: 1 место верное + 250 XP", str(winner))

    # 2 место — runner_a, 150 XP
    second = result["placements"][1]
    if second["user_tg_id"] == 1001 and second["xp"] == 150:
        _ok(suite, "finalize: 2 место верное + 150 XP")
    else:
        _fail(suite, "finalize: 2 место верное + 150 XP", str(second))

    # XP действительно начислены в БД
    from sqlalchemy import select
    async with _test_session_factory() as s:
        r = await s.execute(select(User).where(User.tg_id == 1002))
        u = r.scalar_one()
    if u.xp == 250:
        _ok(suite, "finalize: XP записан в БД (runner_b = 250)")
    else:
        _fail(suite, "finalize: XP записан в БД", f"xp={u.xp}")

    # Турнир закрыт
    closed = await t_svc.get_tournament(tour.id)
    if not closed.is_active:
        _ok(suite, "finalize: турнир деактивирован")
    else:
        _fail(suite, "finalize: турнир деактивирован")

    # 8. Повторная финализация
    r2 = await t_svc.finalize_tournament(tour.id)
    if r2.get("error") == "already_finalized":
        _ok(suite, "finalize: повторный вызов → already_finalized")
    else:
        _fail(suite, "finalize: повторный вызов → already_finalized", str(r2))

    # 9. get_expired_tournaments (турнир уже закрыт — не должен попасть)
    expired = await t_svc.get_expired_tournaments()
    if not any(t.id == tour.id for t in expired):
        _ok(suite, "get_expired_tournaments: закрытый не попадает")
    else:
        _fail(suite, "get_expired_tournaments: закрытый не попадает")

    # 10. Тест types: minutes
    tour_min = await t_svc.create_tournament("Минуты", "minutes", 9999, duration_days=3)
    await t_svc.join_tournament(tour_min.id, 1001)
    await t_svc.update_score(tour_min.id, 1001, km=5.0, duration_min=40)
    await t_svc.update_score(tour_min.id, 1001, km=3.0, duration_min=25)
    lb_m = await t_svc.get_leaderboard(tour_min.id)
    if abs(lb_m[0]["score"] - 65.0) < 0.01:
        _ok(suite, "update_score minutes: суммирует минуты (40+25=65)")
    else:
        _fail(suite, "update_score minutes", f"score={lb_m[0]['score']}")

    # 11. Тест type: days
    tour_d = await t_svc.create_tournament("Дни", "days", 9999, duration_days=3)
    await t_svc.join_tournament(tour_d.id, 1001)
    await t_svc.update_score(tour_d.id, 1001, km=5.0)
    await t_svc.update_score(tour_d.id, 1001, km=5.0)
    lb_d = await t_svc.get_leaderboard(tour_d.id)
    if abs(lb_d[0]["score"] - 2.0) < 0.01:
        _ok(suite, "update_score days: считает отчёты как дни (2)")
    else:
        _fail(suite, "update_score days", f"score={lb_d[0]['score']}")


# ─────────────────────────────────────────────────────────────
# SUITE: Дайджест (без отправки в Telegram)
# ─────────────────────────────────────────────────────────────

async def test_digest():
    suite = "digest"
    print("\n📊 ТЕСТ: Дайджест")

    await _teardown_db()
    await _setup_db()

    # Создаём участников
    u1 = await _make_user(2001, "hero_nick")
    u2 = await _make_user(2002, "debtor_nick")

    # Создаём weekly_runs челленджи
    from sqlalchemy import select
    async with _test_session_factory() as s:
        async with s.begin():
            c1 = Challenge(
                user_id=2001, title="Норма героя",
                ch_type="weekly_runs",
                goal_runs=3, current_runs=4,
                current_value=25.0,
                penalty="Кофе на всех",
                is_active=True,
                started_at=datetime.now() - timedelta(days=7),
            )
            c2 = Challenge(
                user_id=2002, title="Норма должника",
                ch_type="weekly_runs",
                goal_runs=3, current_runs=1,
                current_value=5.0,
                penalty="Пицца",
                is_active=True,
                started_at=datetime.now() - timedelta(days=7),
            )
            s.add_all([c1, c2])

    # Создаём мероприятия этой недели
    from models import Event, EventParticipant
    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0)
    async with _test_session_factory() as s:
        async with s.begin():
            ev1 = Event(
                title="5 вёрст",
                event_date=week_start + timedelta(hours=10),
                created_by=2001,
                is_active=True,
                is_pending=False,
                xp_bonus=100,
                xp_multiplier=1.5,
            )
            ev2 = Event(
                title="Long Run",
                event_date=week_start + timedelta(days=3),
                created_by=2001,
                is_active=True,
                is_pending=False,
                xp_bonus=100,
                xp_multiplier=1.5,
            )
            s.add_all([ev1, ev2])
            await s.flush()
            ev1_id = ev1.id
            ev2_id = ev2.id
            # Участники
            for uid in [2001, 2002]:
                s.add(EventParticipant(event_id=ev1_id, user_tg_id=uid, status="going"))
            s.add(EventParticipant(event_id=ev2_id, user_tg_id=2001, status="going"))

    # Создаём отчёты за эту неделю

    async with _test_session_factory() as s:
        async with s.begin():
            for i in range(4):
                s.add(Report(
                    message_id=3000 + i,
                    chat_id=-100,
                    user_tg_id=2001,
                    km=6.0,
                    is_approved=True,
                    created_at=week_start + timedelta(hours=i + 1),
                ))
            s.add(Report(
                message_id=3010,
                chat_id=-100,
                user_tg_id=2002,
                km=5.0,
                is_approved=True,
                created_at=week_start + timedelta(hours=1),
            ))

    # Мок бота — перехватывает send_message
    sent_messages: list[dict] = []

    class MockBot:
        async def send_message(self, chat_id, text, **kwargs):
            sent_messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
            return type("Msg", (), {"message_id": 999})()

    # Запускаем дайджест
    orig_group = config.GROUP_ID
    config.GROUP_ID = -100500  # заглушка

    try:
        await d_svc.send_weekly_digest(MockBot())
    finally:
        config.GROUP_ID = orig_group

    # Проверяем что что-то было отправлено
    if sent_messages:
        _ok(suite, "send_weekly_digest: что-то отправлено")
    else:
        _fail(suite, "send_weekly_digest: что-то отправлено")
        return

    digest_text = sent_messages[0]["text"]

    # Герои и должники в тексте
    if "ГЕРОИ" in digest_text and "hero_nick" in digest_text:
        _ok(suite, "digest: герой упомянут")
    else:
        _fail(suite, "digest: герой упомянут", digest_text[:300])

    if "ДОЛЖНИКИ" in digest_text and "debtor_nick" in digest_text:
        _ok(suite, "digest: должник упомянут")
    else:
        _fail(suite, "digest: должник упомянут", digest_text[:300])

    if "Пицца" in digest_text:
        _ok(suite, "digest: штраф должника упомянут")
    else:
        _fail(suite, "digest: штраф должника упомянут")

    # Топ-5 XP
    if "ТОП-5" in digest_text:
        _ok(suite, "digest: блок ТОП-5 присутствует")
    else:
        _fail(suite, "digest: блок ТОП-5 присутствует")

    # Стрик героя обновился
    async with _test_session_factory() as s:
        from sqlalchemy import select
        r = await s.execute(select(User).where(User.tg_id == 2001))
        hero = r.scalar_one()

    if hero.streak == 1:
        _ok(suite, "digest: стрик героя +1")
    else:
        _fail(suite, "digest: стрик героя +1", f"streak={hero.streak}")

    if hero.xp == config.XP_PER_WEEK:
        _ok(suite, "digest: XP_PER_WEEK начислен герою")
    else:
        _fail(suite, "digest: XP_PER_WEEK начислен герою", f"xp={hero.xp}")

    # Стрик должника сброшен
    async with _test_session_factory() as s:
        r = await s.execute(select(User).where(User.tg_id == 2002))
        debtor = r.scalar_one()

    if debtor.streak == 0:
        _ok(suite, "digest: стрик должника сброшен")
    else:
        _fail(suite, "digest: стрик должника сброшен", f"streak={debtor.streak}")

    # Счётчики сброшены
    async with _test_session_factory() as s:
        r = await s.execute(select(Challenge).where(Challenge.user_id == 2001))
        ch = r.scalar_one()

    if ch.current_runs == 0 and ch.current_value == 0.0:
        _ok(suite, "digest: счётчики челленджа сброшены")
    else:
        _fail(suite, "digest: счётчики челленджа сброшены",
              f"runs={ch.current_runs} val={ch.current_value}")

    # Личные отчёты — должны были отправиться участникам
    personal = [m for m in sent_messages if m["chat_id"] in (2001, 2002)]
    if personal:
        _ok(suite, "digest: личные отчёты по челленджам отправлены")
    else:
        _fail(suite, "digest: личные отчёты по челленджам отправлены")

    # Мероприятия
    if "МЕРОПРИЯТ" in digest_text and "5 вёрст" in digest_text:
        _ok(suite, "digest: блок мероприятий присутствует")
    else:
        _fail(suite, "digest: блок мероприятий присутствует", digest_text[:400])

    # Milestone стрик (если streak == milestone)
    # Проставляем стрик = 3 и добавляем тренировки для второй недели,
    # чтобы герой снова выполнил норму и стрик стал 4
    async with _test_session_factory() as s:
        async with s.begin():
            # Стрик = 3, чтобы после этой недели стал 4
            r = await s.execute(select(User).where(User.tg_id == 2001))
            u = r.scalar_one()
            u.streak = 3

            # Добавляем тренировки на текущую неделю (счётчики уже сброшены)
            r2 = await s.execute(select(Challenge).where(Challenge.user_id == 2001))
            ch = r2.scalar_one()
            ch.current_runs = 4    # норма выполнена (goal=3)
            ch.current_value = 28.0

    sent_messages.clear()
    config.GROUP_ID = -100500
    try:
        await d_svc.send_weekly_digest(MockBot())
    finally:
        config.GROUP_ID = orig_group

    async with _test_session_factory() as s:
        r = await s.execute(select(User).where(User.tg_id == 2001))
        u = r.scalar_one()

    if u.streak == 4:
        _ok(suite, "digest: стрик дошёл до 4")
    else:
        _fail(suite, "digest: стрик дошёл до 4", f"streak={u.streak}")

    # XP за milestone 4 недели (+100)
    expected_xp = config.XP_PER_WEEK * 2 + config.STREAK_MILESTONES.get(4, 0)
    if u.xp == expected_xp:
        _ok(suite, f"digest: milestone 4 недели → +{config.STREAK_MILESTONES.get(4,0)} XP")
    else:
        _fail(suite, "digest: milestone XP",
              f"xp={u.xp} expected={expected_xp}")

    digest2 = sent_messages[0]["text"] if sent_messages else ""
    if "MILESTONE" in digest2 or "недел" in digest2 and "без пропусков" in digest2:
        _ok(suite, "digest: milestone упомянут в тексте")
    else:
        _fail(suite, "digest: milestone упомянут в тексте", digest2[:300])


# ─────────────────────────────────────────────────────────────
# SUITE: Отправка в Telegram (--send)
# ─────────────────────────────────────────────────────────────

async def test_send_to_telegram():
    """Реальная отправка дайджеста в группу. Требует .env с BOT_TOKEN и GROUP_ID."""
    print("\n📡 ОТПРАВКА В TELEGRAM")

    if not config.BOT_TOKEN:
        print("  ⚠️  BOT_TOKEN не задан — пропускаем.")
        return
    if not config.GROUP_ID:
        print("  ⚠️  GROUP_ID не задан — пропускаем.")
        return

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.enums import ParseMode

    session = AiohttpSession(proxy=config.PROXY_URL) if config.PROXY_URL else None
    bot = Bot(
        token=config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        await d_svc.send_weekly_digest(bot)
        print(f"  ✅ Дайджест отправлен в группу {config.GROUP_ID}")
    except Exception as e:
        print(f"  ❌ Ошибка отправки: {e}")
    finally:
        await bot.session.close()


# ─────────────────────────────────────────────────────────────
# Итоги
# ─────────────────────────────────────────────────────────────

def _print_summary():
    print("\n" + "═" * 50)
    total = len(results)
    passed = sum(1 for _, _, s in results if s == PASS)
    failed = total - passed
    print(f"ИТОГО: {passed}/{total} прошло  |  {failed} упало")
    if failed:
        print("\nПровальные тесты:")
        for suite, name, status in results:
            if status == FAIL:
                print(f"  [{suite}] {name}")
    print("═" * 50)
    return failed


# ─────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]
    send_flag = "--send" in args
    suites = [a for a in args if not a.startswith("--")]

    run_all = not suites

    if run_all or "tournaments" in suites:
        await test_tournaments()

    if run_all or "digest" in suites:
        await test_digest()

    if send_flag:
        await test_send_to_telegram()

    failed = _print_summary()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())