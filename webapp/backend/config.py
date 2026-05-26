"""webapp/backend/config.py — настройки бэкенда Mini App."""

import os
from dotenv import load_dotenv

# Загружаем .env из корня проекта (две папки вверх)
_root = os.path.join(os.path.dirname(__file__), "..", "..")
load_dotenv(os.path.join(_root, ".env"))

BOT_TOKEN: str       = os.getenv("BOT_TOKEN", "")
DB_URL: str          = os.getenv("DB_URL", "sqlite+aiosqlite:///./it_run.db")
ADMIN_IDS: list[int] = [
    int(i.strip())
    for i in os.getenv("ADMIN_IDS", "").split(",")
    if i.strip()
]

# Вторичная группа для репоста анонсов
_sg = os.getenv("SECONDARY_GROUP_ID", "")
SECONDARY_GROUP_ID: int | None = int(_sg) if _sg.strip() else None
SECONDARY_THREAD_ID: int | None = int(os.getenv("SECONDARY_THREAD_ID", "0")) or None

def _parse_secondary_targets() -> list[tuple[int, int | None]]:
    raw = os.getenv("SECONDARY_TARGETS", "").strip()
    result = []
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                gid, tid = part.split(":", 1)
                result.append((int(gid), int(tid) if tid.strip() else None))
            else:
                result.append((int(part), None))
    elif SECONDARY_GROUP_ID:
        result.append((SECONDARY_GROUP_ID, SECONDARY_THREAD_ID))
    return result

SECONDARY_TARGETS: list[tuple[int, int | None]] = _parse_secondary_targets()

# Ссылка-приглашение в клуб (для репоста в вторичную группу)
CLUB_INVITE_LINK: str = os.getenv("CLUB_INVITE_LINK", "https://t.me/+HLikNXKlA3YwNDRi")

# Основная группа и топик событий
_g = os.getenv("GROUP_ID", "")
GROUP_ID: int | None = int(_g) if _g.strip() else None
EVENTS_THREAD_ID: int | None = int(os.getenv("EVENTS_THREAD_ID", "0")) or None
DIGEST_THREAD_ID: int | None = int(os.getenv("DIGEST_THREAD_ID", "0")) or None
REPORTS_THREAD_ID: int | None = int(os.getenv("REPORTS_THREAD_ID", "0")) or None

# Если DB_URL относительный — резолвим от корня проекта
if DB_URL.startswith("sqlite+aiosqlite:///./"):
    _db_file = DB_URL.replace("sqlite+aiosqlite:///./", "")
    _abs = os.path.join(_root, _db_file)
    DB_URL = f"sqlite+aiosqlite:///{_abs}"

# CORS — в dev разрешаем всё, в prod ограничить своим доменом
CORS_ORIGINS: list[str] = os.getenv(
    "CORS_ORIGINS", "*"
).split(",")