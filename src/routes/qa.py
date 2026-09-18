from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.database import get_db
from src.repositories.schema.schemas import AnswerModeResponse, QuoteModeResponse
from src.repositories.transcript_repository import TranscriptRepository
from src.services.dependencies import get_service_deps
from src.services.qa_service import QAService
from src.utils.exceptions.exceptions import LLMError

router = APIRouter(prefix="/api/v1/qa", tags=["Q&A"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    mode: str | None = Field(default=None, pattern="^(answer|quote)$")
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/ask", response_model=AnswerModeResponse | QuoteModeResponse)
async def ask(
    request: AskRequest,
    session: AsyncSession = Depends(get_db),
    dependencies=Depends(get_service_deps),
) -> AnswerModeResponse | QuoteModeResponse:
    service = QAService(TranscriptRepository(session), dependencies)
    try:
        return await service.ask(question=request.question, mode=request.mode, top_k=request.top_k)
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
