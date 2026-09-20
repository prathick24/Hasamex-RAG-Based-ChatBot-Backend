from fastapi import APIRouter

from src.routes.analysis import router as analysis_router
from src.routes.audit import router as audit_router
from src.routes.ingest import router as ingest_router
from src.routes.qa import router as qa_router

router = APIRouter()
router.include_router(ingest_router)
router.include_router(analysis_router)
router.include_router(qa_router)
router.include_router(audit_router)

__all__ = ["router"]
