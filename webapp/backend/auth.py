"""
webapp/backend/auth.py — верификация Telegram Mini App initData.

Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import logging
from urllib.parse import unquote, parse_qsl

from fastapi import HTTPException, Header
from config import BOT_TOKEN, ADMIN_IDS

log = logging.getLogger("auth")

# DEV_MODE: только для локальной разработки — на проде держать False
DEV_MODE = False


def _check_telegram_auth(init_data: str | None) -> dict:
    """
    Проверяет подпись initData от Telegram.

    Returns:  dict с данными пользователя (id, first_name, username, ...)
    Raises:   HTTPException 401 если подпись неверна или initData отсутствует
    """
    log.warning(f"X-Init-Data received: {repr(init_data[:80]) if init_data else None}")

    # Dev bypass
    if DEV_MODE and not init_data:
        admin_id = ADMIN_IDS[0] if ADMIN_IDS else 0
        return {"id": admin_id, "first_name": "Dev", "username": "devuser"}

    # initData отсутствует — открыли не через Telegram
    if not init_data or len(init_data.strip()) == 0:
        raise HTTPException(
            status_code=401,
            detail="Открой приложение через Telegram-бота, а не через браузер."
        )

    params = dict(parse_qsl(unquote(init_data), keep_blank_values=True))
    received_hash = params.pop("hash", None)

    if not received_hash:
        raise HTTPException(status_code=401, detail="hash missing in initData")

    data_check = "\n".join(
        f"{k}={v}"
        for k, v in sorted(params.items())
    )

    # secret = HMAC-SHA256(key="WebAppData", msg=BOT_TOKEN)
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=BOT_TOKEN.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    expected = hmac.new(
        key=secret_key,
        msg=data_check.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        log.warning(
            f"HMAC mismatch — expected={expected[:16]}... received={received_hash[:16]}..."
        )
        raise HTTPException(status_code=401, detail="invalid hash — initData подделан или устарел")

    user_json = params.get("user", "{}")
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="invalid user JSON in initData")

    if not user.get("id"):
        raise HTTPException(status_code=401, detail="user.id missing in initData")

    return user


async def get_current_user(
    x_init_data: str | None = Header(None, alias="X-Init-Data"),
) -> dict:
    """
    FastAPI dependency — извлекает и проверяет пользователя из заголовка.

    Фронт передаёт заголовок только когда initData есть:
        X-Init-Data: <window.Telegram.WebApp.initData>

    Если заголовка нет (открыли в браузере) — возвращаем 401 с понятным сообщением.
    """
    return _check_telegram_auth(x_init_data)
