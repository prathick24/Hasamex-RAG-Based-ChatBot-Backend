from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ChatHistory, ErrorLog, LLMUsageLog
from src.utils.exceptions.exceptions import DatabaseWriteError, RepositoryError


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

    async def _list_rows(self, model, limit: int) -> list[dict]:
        try:
            stmt = select(model).order_by(model.id.desc()).limit(limit)
            result = await self._session.execute(stmt)
            rows = list(result.scalars())
            return [self._row_to_dict(row) for row in rows]
        except Exception as exc:
            raise RepositoryError(f"Failed to read {model.__tablename__}") from exc

    def _row_to_dict(self, row) -> dict:
        return {
            column.name: getattr(row, column.name)
            for column in row.__table__.columns
        }

    async def list_chat_history(self, limit: int = 50) -> list[dict]:
        return await self._list_rows(ChatHistory, limit)

    async def list_error_logs(self, limit: int = 50) -> list[dict]:
        return await self._list_rows(ErrorLog, limit)

    async def list_llm_usage(self, limit: int = 50) -> list[dict]:
        return await self._list_rows(LLMUsageLog, limit)