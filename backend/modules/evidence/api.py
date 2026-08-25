"""Canonical Evidence routes."""

from fastapi import APIRouter

from modules.evidence.compilation.api import handler_router as compilation_handler_router
from modules.evidence.indexing.api import handler_router as indexing_handler_router

router = APIRouter(prefix="/api/evidence")
router.include_router(indexing_handler_router, prefix="/indexing")
router.include_router(compilation_handler_router, prefix="/compilation")
