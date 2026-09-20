"""Best-effort traceability records.

Every recorder opens its own short-lived DB session and swallows failures so
that a storage hiccup never breaks the primary request/analysis flow.
"""
import logging

from src.repositories.audit_repository import AuditRepository
from src.repositories.database import db

logger = logging.getLogger("hasamex.audit")


async def _record(function) -> None:
    try:
        async with db.session() as session:
            repository = AuditRepository(session)
            await function(repository)
    except Exception:
        logger.exception("audit_record_failed")


async def record_chat_turn(**kwargs) -> None:
    await _record(lambda repo: repo.add_chat_turn(**kwargs))


async def record_error(
    *,
    level: str = "error",
    component: str,
    message: str,
    exception_type: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    detail: dict | None = None,
) -> None:
    await _record(
        lambda repo: repo.add_error(
            level=level,
            component=component,
            message=message,
            exception_type=exception_type,
            endpoint=endpoint,
            method=method,
            detail=detail,
        )
    )


async def record_llm_usage(payload: dict) -> None:
    await _record(lambda repo: repo.add_llm_usage(**payload))