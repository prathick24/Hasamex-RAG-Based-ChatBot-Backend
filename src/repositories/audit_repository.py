from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ChatHistory, ErrorLog, LLMUsageLog
from src.utils.exceptions.exceptions import DatabaseWriteError


class AuditRepository:
    """Persist traceability records: chat turns, errors, LLM usage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_chat_turn(
        self,
        *,
        question: str,
        mode: str,
        answer: str | None = None,
        citations: list | None = None,
        verification_status: str | None = None,
        model: str | None = None,
        latency_ms: int | None = None,
    ) -> int:
        try:
            row = ChatHistory(
                question=question,
                mode=mode,
                answer=answer,
                citations=citations or [],
                verification_status=verification_status,
                model=model,
                latency_ms=latency_ms,
            )
            self._session.add(row)
            await self._session.flush()
            await self._session.commit()
            return row.id
        except Exception as exc:
            await self._session.rollback()
            raise DatabaseWriteError(f"Failed to write chat history: {exc}") from exc

    async def add_error(
        self,
        *,
        level: str = "error",
        component: str,
        message: str,
        exception_type: str | None = None,
        endpoint: str | None = None,
        method: str | None = None,
        detail: dict | None = None,
    ) -> int:
        try:
            row = ErrorLog(
                level=level,
                component=component,
                message=message,
                exception_type=exception_type,
                endpoint=endpoint,
                method=method,
                detail=detail,
            )
            self._session.add(row)
            await self._session.flush()
            await self._session.commit()
            return row.id
        except Exception as exc:
            await self._session.rollback()
            raise DatabaseWriteError(f"Failed to write error log: {exc}") from exc

    async def add_llm_usage(
        self,
        *,
        task: str | None = None,
        model: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: int | None = None,
        success: bool = True,
    ) -> int:
        try:
            row = LLMUsageLog(
                task=task,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                success=success,
            )
            self._session.add(row)
            await self._session.flush()
            await self._session.commit()
            return row.id
        except Exception as exc:
            await self._session.rollback()
            raise DatabaseWriteError(f"Failed to write LLM usage: {exc}") from exc