from pydantic import BaseModel, ConfigDict, Field


class TranscriptRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    expert_name: str
    expert_role: str | None
    market: str
    chunk_count: int


class ChunkRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transcript_id: int
    speaker: str
    speaker_index: str
    timestamp: str
    content: str


class ChunkWithTranscript(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: int
    transcript_file: str
    expert_name: str
    market: str
    timestamp: str
    content: str
    distance: float | None = None


class Citation(BaseModel):
    transcript_file: str
    expert_name: str
    market: str
    timestamp: str
    quote: str


class IngestionResult(BaseModel):
    transcripts_count: int
    chunks_count: int
    loaded: bool
    created_transcripts: int = 0
    created_chunks: int = 0


class UploadFileResult(BaseModel):
    filename: str
    status: str = "uploaded"
    transcript_id: int | None = None
    version: int | None = None
    chunk_count: int = 0
    reason: str | None = None


class UploadBatchResult(BaseModel):
    processed: int = 0
    succeeded: int = 0
    results: list[UploadFileResult] = Field(default_factory=list)


class TranscriptListResult(BaseModel):
    transcripts: list[TranscriptRecord] = Field(default_factory=list)


class DeleteTranscriptResult(BaseModel):
    deleted: bool


class InterviewGuideAnswer(BaseModel):
    question_id: int
    expert: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)


class InterviewGuideEntry(BaseModel):
    question_id: int
    question: str
    answers: list[InterviewGuideAnswer]


class Theme(BaseModel):
    type: str
    summary: str
    citations: list[Citation] = Field(default_factory=list)


class ThemeEntry(BaseModel):
    topic: str
    themes: list[Theme]
    error: bool = False


class AnswerModeResponse(BaseModel):
    question: str
    mode: str = "answer"
    answer: str
    citations: list[Citation] = Field(default_factory=list)


class QuoteResponseItem(BaseModel):
    quote: str
    transcript_file: str
    expert_name: str
    market: str
    timestamp: str
    verification_status: str


class QuoteModeResponse(BaseModel):
    question: str
    mode: str = "quote"
    answer: str | None = None
    quotes: list[QuoteResponseItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
