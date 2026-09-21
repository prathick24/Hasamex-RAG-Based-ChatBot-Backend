from pydantic import BaseModel, ConfigDict


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
