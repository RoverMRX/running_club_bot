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

# Если DB_URL относительный — резолвим от корня проекта
if DB_URL.startswith("sqlite+aiosqlite:///./"):
    _db_file = DB_URL.replace("sqlite+aiosqlite:///./", "")
    _abs = os.path.join(_root, _db_file)
    DB_URL = f"sqlite+aiosqlite:///{_abs}"

# CORS — в dev разрешаем всё, в prod ограничить своим доменом
CORS_ORIGINS: list[str] = os.getenv(
    "CORS_ORIGINS", "*"
).split(",")