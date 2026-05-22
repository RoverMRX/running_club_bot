import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DB_URL: str = os.getenv("DB_URL", "sqlite+aiosqlite:///./it_run.db")
PROXY_URL: str | None = os.getenv("PROXY_URL")

# Основная группа клуба
_g = os.getenv("GROUP_ID", "")
GROUP_ID: int | None = int(_g) if _g.strip() else None

# Топики в основной группе
REPORTS_THREAD_ID: int | None  = int(os.getenv("REPORTS_THREAD_ID", "0")) or None
EVENTS_THREAD_ID: int | None   = int(os.getenv("EVENTS_THREAD_ID",  "0")) or None
DIGEST_THREAD_ID: int | None   = int(os.getenv("DIGEST_THREAD_ID",  "0")) or None

# Вторая группа для репоста анонсов (без прав админа)
_sg = os.getenv("SECONDARY_GROUP_ID", "")
SECONDARY_GROUP_ID: int | None   = int(_sg) if _sg.strip() else None
SECONDARY_THREAD_ID: int | None  = int(os.getenv("SECONDARY_THREAD_ID", "0")) or None

# Администраторы (через запятую: "123,456")
_a = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(i.strip()) for i in _a.split(",") if i.strip()]

# Правила голосования
VOTES_REQUIRED: int = int(os.getenv("VOTES_REQUIRED", "3"))

# XP
XP_PER_KM: int    = int(os.getenv("XP_PER_KM",    "10"))
XP_PER_WEEK: int  = int(os.getenv("XP_PER_WEEK",  "50"))
XP_PR_BONUS: int  = int(os.getenv("XP_PR_BONUS",  "50"))   # Личный рекорд

# Milestone-стрики и их XP: {недели: xp}
STREAK_MILESTONES: dict[int, int] = {4: 100, 8: 150, 12: 200, 20: 300}

# XP за выполнение челленджа (по длительности)
XP_CHALLENGE_DAY:    int = int(os.getenv("XP_CHALLENGE_DAY",    "200"))  # < 1 дня
XP_CHALLENGE_WEEK:   int = int(os.getenv("XP_CHALLENGE_WEEK",   "300"))  # до недели
XP_CHALLENGE_MONTH:  int = int(os.getenv("XP_CHALLENGE_MONTH",  "400"))  # до месяца
XP_CHALLENGE_LONG:   int = int(os.getenv("XP_CHALLENGE_LONG",   "500"))  # > 2 месяцев
XP_CHALLENGE_STREAK: int = int(os.getenv("XP_CHALLENGE_STREAK", "150"))  # стрик weekly_runs