"""One router exposing the existing RAG and Context HTTP aliases."""

from fastapi import APIRouter

from modules.evidence.compilation.api import router as context_alias_router
from modules.evidence.indexing.api import router as rag_alias_router

router = APIRouter()
router.include_router(rag_alias_router)
router.include_router(context_alias_router)

