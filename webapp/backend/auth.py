"""
webapp/backend/auth.py — верификация Telegram Mini App initData.

Telegram передаёт initData при открытии Mini App.
Мы проверяем HMAC-подпись чтобы убедиться что данные настоящие.

Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
from urllib.parse import unquote, parse_qsl

from fastapi import HTTPException, Header
from config import BOT_TOKEN, ADMIN_IDS

# DEV_MODE: если initData == "dev", возвращаем первого админа
# Только для локальной разработки — на проде отключить!
DEV_MODE = True


def _check_telegram_auth(init_data: str) -> dict:
    """
    Проверяет подпись initData от Telegram.

    Returns:
        dict с данными пользователя (id, first_name, username, ...)

    Raises:
        HTTPException 401 если подпись неверна
    """
    # Dev bypass для локальной разработки
    if DEV_MODE and init_data == "dev":
        admin_id = ADMIN_IDS[0] if ADMIN_IDS else 0
        return {"id": admin_id, "first_name": "Dev", "username": "devuser"}

    params = dict(parse_qsl(unquote(init_data), keep_blank_values=True))
    received_hash = params.pop("hash", None)

    if not received_hash:
        raise HTTPException(status_code=401, detail="hash missing")

    # Строка для проверки — отсортированные параметры через \n
    data_check = "\n".join(
        f"{k}={v}"
        for k, v in sorted(params.items())
    )

    # Секретный ключ = HMAC-SHA256(BOT_TOKEN, "WebAppData")
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()

    # Ожидаемый хэш
    expected = hmac.new(
        secret_key,
        data_check.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(status_code=401, detail="invalid hash")

    # Парсим user из JSON
    user_json = params.get("user", "{}")
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="invalid user data")

    return user


async def get_current_user(
    x_init_data: str = Header(..., alias="X-Init-Data"),
) -> dict:
    """
    FastAPI dependency — извлекает и проверяет пользователя из заголовка.

    Фронт передаёт: X-Init-Data: <window.Telegram.WebApp.initData>

    Returns:
        {"id": 123, "username": "...", "first_name": "..."}
    """
    return _check_telegram_auth(x_init_data)


async def get_current_user_optional(
    x_init_data: str | None = Header(None, alias="X-Init-Data"),
) -> dict | None:
    """Та же проверка но не обязательная (для dev/тестов)."""
    if not x_init_data:
        return None
    return _check_telegram_auth(x_init_data)