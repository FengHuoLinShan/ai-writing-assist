"""Canonical Evidence routes plus one-release RAG and Context aliases."""

from fastapi import APIRouter

from modules.evidence.compilation.api import handler_router as compilation_handler_router
from modules.evidence.compilation.api import router as context_alias_router
from modules.evidence.indexing.api import handler_router as indexing_handler_router
from modules.evidence.indexing.api import router as rag_alias_router

router = APIRouter(prefix="/api/evidence")
router.include_router(indexing_handler_router, prefix="/indexing")
router.include_router(compilation_handler_router, prefix="/compilation")

alias_router = APIRouter()
alias_router.include_router(rag_alias_router)
alias_router.include_router(context_alias_router)
