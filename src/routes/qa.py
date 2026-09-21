import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.database import get_db
from src.repositories.schema.schemas import AnswerModeResponse, AskRequest
from src.repositories.transcript_repository import TranscriptRepository
from src.services import audit_service
from src.services.dependencies import get_service_deps
from src.services.qa_service import QAService
from src.utils.exceptions.exceptions import LLMError

router = APIRouter(prefix="/api/v1/qa", tags=["Q&A"])


@router.post("/ask", response_model=AnswerModeResponse)
async def ask(
    request: AskRequest,
    session: AsyncSession = Depends(get_db),
    dependencies=Depends(get_service_deps),
) -> AnswerModeResponse:
    service = QAService(TranscriptRepository(session), dependencies)
    start = time.perf_counter()
    try:
        response = await service.ask(question=request.question, top_k=request.top_k)
    except LLMError as exc:
        await audit_service.record_error(
            component="qa",
            message=f"Q&A failed: {exc.message}",
            exception_type=type(exc).__name__,
            endpoint="/api/v1/qa/ask",
            method="POST",
            detail={"question": request.question},
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    latency_ms = round((time.perf_counter() - start) * 1000)
    verification_status = None
    if getattr(response, "quotes", None):
        verification_status = response.quotes[0].verification_status
    await audit_service.record_chat_turn(
        question=request.question,
        mode=response.mode,
        answer=response.answer,
        citations=[citation.model_dump() for citation in response.citations],
        verification_status=verification_status,
        model=dependencies.settings.llm_model,
        latency_ms=latency_ms,
    )
    return response
