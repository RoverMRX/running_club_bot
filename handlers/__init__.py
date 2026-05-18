"""Handlers package — все роутеры собраны здесь."""

from aiogram import Router
from .common import router as common_router
from .challenges import router as challenges_router

# Объединяем все роутеры
router = Router()
router.include_router(common_router)
router.include_router(challenges_router)

__all__ = ["router"]