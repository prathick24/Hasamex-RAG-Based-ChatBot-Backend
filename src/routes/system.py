from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.database import get_db
from src.repositories.transcript_repository import TranscriptRepository
from src.settings import get_settings

router = APIRouter(tags=["System"])


@router.get("/")
async def root() -> dict:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
    }


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: AsyncSession = Depends(get_db)) -> JSONResponse:
    repository = TranscriptRepository(session)
    pg_ok = await repository.pgvector_available()
    tables_ok = await repository.tables_available()

    transcripts_count = await repository.count_transcripts() if pg_ok else 0
    chunks_count = await repository.count_chunks() if pg_ok else 0

    dependencies = {
        "postgres": pg_ok,
        "pgvector": pg_ok,
        "tables": tables_ok,
    }
    is_ready = pg_ok and tables_ok
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "dependencies": dependencies,
        "transcripts_count": transcripts_count,
        "chunks_count": chunks_count,
    }
    if not is_ready:
        return JSONResponse(status_code=503, content=payload)
    return JSONResponse(status_code=200, content=payload)
