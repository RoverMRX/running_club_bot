"""
webapp/backend/main.py — FastAPI бэкенд для Mini App IT БЕГОТНЯ 21.

Запуск:
    uvicorn main:app --reload --port 8000

API доступно по http://localhost:8000
Swagger UI: http://localhost:8000/docs
"""

import sys, os
# Добавляем backend/ в sys.path чтобы роутеры видели database, config, auth, schemas
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from routers import profile, challenges, reports, events, tournaments

app = FastAPI(
    title="IT БЕГОТНЯ 21 — API",
    description="Бэкенд для Telegram Mini App бегового клуба",
    version="1.0.0",
)

# CORS — разрешаем фронту обращаться к бэкенду
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(profile.router)
app.include_router(challenges.router)
app.include_router(reports.router)
app.include_router(events.router)
app.include_router(tournaments.router)


@app.get("/health")
async def health() -> dict:
    """Проверка что бэкенд живой."""
    return {"status": "ok", "service": "IT БЕГОТНЯ 21 API"}