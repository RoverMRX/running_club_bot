import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DB_URL: str = os.getenv("DB_URL", "sqlite+aiosqlite:///./it_run.db")
PROXY_URL: str | None = os.getenv("PROXY_URL")

# ID группы/супергруппы клуба (int или None)
_group_raw = os.getenv("GROUP_ID", "")
GROUP_ID: int | None = int(_group_raw) if _group_raw.strip() else None

# ID администраторов через запятую: "123456,789012"
_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(i.strip()) for i in _admin_raw.split(",") if i.strip()]

# Сколько голосов участников нужно для подтверждения отчёта
VOTES_REQUIRED: int = int(os.getenv("VOTES_REQUIRED", "3"))

# XP за 1 км и за закрытую неделю
XP_PER_KM: int = int(os.getenv("XP_PER_KM", "10"))
XP_PER_WEEK: int = int(os.getenv("XP_PER_WEEK", "50"))