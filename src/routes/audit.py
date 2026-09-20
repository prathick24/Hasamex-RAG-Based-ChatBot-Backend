from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.audit_repository import AuditRepository
from src.repositories.database import get_db

router = APIRouter(prefix="/api/v1", tags=["Audit"])


@router.get("/chat/history")
async def list_chat_history(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    repository = AuditRepository(session)
    return await repository.list_chat_history(limit)


@router.get("/error-logs")
async def list_error_logs(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    repository = AuditRepository(session)
    return await repository.list_error_logs(limit)


@router.get("/llm-usage")
async def list_llm_usage(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    repository = AuditRepository(session)
    return await repository.list_llm_usage(limit)