"""Handlers package — все роутеры собраны здесь."""

from aiogram import Router

from .common import router as common_router
from .challenges import router as challenges_router
from .reports import router as reports_router
from .events import router as events_router
from .tournaments import router as tournaments_router
from .admin import router as admin_router

router = Router()
router.include_router(common_router)
router.include_router(challenges_router)
router.include_router(reports_router)
router.include_router(events_router)
router.include_router(tournaments_router)
router.include_router(admin_router)

__all__ = ["router"]