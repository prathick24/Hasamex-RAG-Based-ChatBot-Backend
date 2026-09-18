from pydantic import BaseModel, ConfigDict, Field

from src.repositories.schema.schemas import Citation, QuoteResponseItem


class ParsedTurn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    speaker: str
    speaker_index: str
    timestamp: str
    content: str


class ParsedTranscript(BaseModel):
    filename: str
    expert_name: str
    expert_role: str | None = None
    market: str
    turns: list[ParsedTurn]


class SimilarChunk(BaseModel):
    chunk_id: int
    transcript_file: str
    expert_name: str
    market: str
    timestamp: str
    content: str
    distance: float


class SearchResult(BaseModel):
    mode: str
    question: str
    answer: str | None = None
    quotes: list[QuoteResponseItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    mode: str | None = Field(default=None, pattern="^(answer|quote)$")
    top_k: int = Field(default=5, ge=1, le=20)


class ThemeResult(BaseModel):
    topic: str
    themes: list[dict] = Field(default_factory=list)
