# Requirements Document

## Introduction

This feature covers the analysis of three expert-call transcripts (Europe – Robotic Surgery Market) collected by Hasamex. The application must read and parse expert-call transcripts, answer a predefined interview guide for each expert, extract exact quotes with source timestamps, identify common themes and disagreements across all three experts, and allow users to ask free-form questions across the entire transcript corpus.

The requirement is aligned with the technical case study brief delivered by the Hasamex engineering team. The goal is a working, demoable application (not production-grade) that demonstrates practical AI engineering skills: accurate parsing, grounded LLM answers with citations, hallucination prevention, and ability to explain architecture decisions.

## Glossary

- **Expert-Call Transcript**: A text file containing a recorded interview between an interviewer and a domain expert, with `MM:SS` timestamps at the start of each speaker turn.
- **Interview Guide**: A fixed set of questions asked to each expert during the call. All three transcripts answer the same six-question guide.
- **Chunk**: A single expert speaker turn extracted from a transcript, stored with its timestamp and speaker metadata. Interviewer questions are bundled onto the following expert answer (prefixed `Q:`), so each chunk is self-contained and carries the timeframe/scope the answer depends on.
- **Embedding**: A dense numeric vector (384-dimensions, `all-MiniLM-L6-v2`) representing the semantic meaning of a chunk's text, used for vector similarity search.
- **Vector Store**: PostgreSQL table (`chunks`) with a `pgvector` `vector(384)` column enabling `<=>` cosine-distance search.
- **Citation**: The source reference attached to each answer/quote — transcript filename, expert name, role, market, and timestamp(s). Every important answer must be traceable to the source transcript.
- **RAG (Retrieval-Augmented Generation)**: Pipeline where relevant chunks are retrieved from the vector store by semantic similarity, then passed to the LLM as grounding context to generate an answer.
- **Quote Verification**: Programmatic substring-match check ensuring a generated quote exists verbatim in the source transcript before it is shown to the user.
- **Hallucination**: An LLM-generated statement or quote that is not grounded in (or contradicts) the source transcripts.

## Requirements

### Requirement 1: Transcript Parsing and Ingestion

**User Story:** As a user, I want the three expert-call transcripts to be automatically read, parsed into timestamped chunks, embedded, and stored in PostgreSQL so that all downstream analysis is grounded in structured, traceable data.

#### Acceptance Criteria

1. THE application SHALL read all `.txt` files present in the `datas/` directory at startup (Transcript_1_France.txt, Transcript_2_Germany.txt, Transcript_3_UK.txt).
2. THE parser SHALL extract structured metadata from the header of each transcript: expert name, expert role, and market (country). Format: `Expert N – Name`, `Role: ...`, `Market: ...`.
3. THE parser SHALL split the transcript body into speaker turns using the `MM:SS` timestamp regex `^(?:\d{1,2}:)?\d{2}:\d{2}`.
4. Each chunk SHALL record: `transcript_id` (FK), `speaker` (Interviewer or Expert), `timestamp` (`MM:SS`), raw `content`, and speaker index.
5. Every chunk SHALL be embedded using `sentence-transformers/all-MiniLM-L6-v2` (384-dim) and the embedding SHALL be stored in a `vector(384)` pgvector column.
6. Ingestion SHALL be idempotent: re-running ingestion SHALL NOT create duplicate chunks (unique key on `transcript_id + speaker_index`; use `ON CONFLICT DO NOTHING`).
7. The system SHALL expose the parsed transcript and chunk counts via the health/ready endpoint.

### Requirement 2: Interview Guide Answering

**User Story:** As a user, I want to see each of the six interview-guide questions answered for each of the three experts, with the answer grounded in and cited to the exact transcript source.

#### Acceptance Criteria

1. THE system SHALL read the six questions from `datas/Interview_Guide.txt`.
2. For each question, and for each expert (3 experts), the system SHALL generate an answer from the expert's own transcript chunks via RAG (retrieval scoped to that expert's transcript only).
3. Each generated answer SHALL be attached with a list of citations, each citation containing: `transcript_file`, `expert_name`, `expert_role`, `market`, `timestamp`, and the exact source `chunk_text`.
4. THE generation prompt SHALL include a strict output contract requiring the LLM to return JSON, answered in batches of up to 3 questions per call: `{"answers": [{"question_id": int, "answer": str, "citations": [{"transcript_file", "expert_name", "timestamp", "quote"}]}]}`.
5. If no relevant chunk is retrieved for a question+expert, THE answer SHALL state "Not mentioned in this transcript" and include an empty citations array.
6. Answers SHALL be generated per expert such that cross-expert contamination is prevented (retrieval is filtered by `transcript_id`).
7. THE guide SHALL be failure-tolerant: if an LLM call for a batch fails after retries, THE system SHALL respond with a friendly generic message per question ("Oops - we hit a snag generating this one...") and empty citations, and SHALL still terminate the stream with a `done` event (a failed batch must never leave the stream unfinished).

### Requirement 3: Exact Quote Extraction (via Chat)

**User Story:** As a user, I want to retrieve verbatim quotes from the transcripts with their exact source timestamps, so that claims in the analysis can be verified against the raw material — without a separate quotes page.

#### Acceptance Criteria

1. THE chat endpoint `POST /api/v1/qa/ask` SHALL always return a verbatim-quote section alongside the LLM answer — no mode selection or intent detection required.
2. The quoted text SHALL be the raw chunk content from hybrid search (semantic + keyword) — never LLM-written or paraphrased.
3. Quotes returned SHALL be exact substrings of the stored chunk text — never paraphrased.
4. THE system SHALL programmatically verify each quote against the source chunk using a substring match before returning it (`quote in chunk_text`).
5. If a chunk fails verification, THE system SHALL flag it `verification_status: "verification_failed"` (never silently fabricated).
6. Each quote SHALL be rendered with citation metadata: transcript filename, expert name, market, and one or more timestamps.
7. When a question maps to multiple relevant chunks (possibly across experts), ALL matching quotes SHALL be returned, each with its own citation — the system SHALL NOT collapse multiple sources into a single unverifiable composite.

### Requirement 4: Theme and Disagreement Identification

**User Story:** As a research user, I want the system to surface the common themes agreed by all three experts and the points where experts disagree or differ in emphasis, with supporting citations for each theme.

#### Acceptance Criteria

1. THE system SHALL organise analysis by the six interview-guide questions (topics).
2. For each topic, THE system SHALL retrieve the top-K most similar chunks **per expert transcript** (each expert's scoped results merged by chunk id, no distance cutoff — per-expert scoping guarantees every expert's relevant passages are in context even when a convoluted topic sentence scores low globally) and return a theme summary describing: consensus points, divergent points (disagreements), and differences in emphasis.
3. Each theme entry SHALL cite the supporting experts (name, market, timestamp, quote) that back the claim.
4. THE system SHALL distinguish between **direct disagreement** (experts state conflicting facts/numbers/timelines) and **difference in emphasis** (experts agree but weight factors differently) and label each theme accordingly.
5. Example expected outcome: on purchase timeline (Q6), France = 6–12 months, Germany = 9–18 months, UK = 6–9 months — the theme SHALL surface this numeric range as a disagreement and cite all three timestamps.
6. Per-topic analysis SHALL be isolated and failure-tolerant: malformed theme/citation entries are dropped (logged, never crashing the stream), and a transient LLM failure on one topic alone leaves the remaining topics unaffected; the stream SHALL always terminate with a `done` event. A failed topic SHALL be flagged as an error (`error: true` entry) so the UI can show an explicit "snag – please refresh" message, which is distinct from a successfully analysed topic that genuinely finds no themes ("No themes identified for this topic.").

### Requirement 5: Cross-Transcript Question Answering (RAG Chat)

**User Story:** As a user, I want to ask any free-form question across the entire transcript corpus and receive a grounded answer with citations to whichever experts/hospitals are relevant, OR request exact verbatim quotes when needed.

#### Acceptance Criteria

1. THE system SHALL accept a free-text user question via API.
2. THE system SHALL embed the question and retrieve the top-K most similar chunks (default K=5) from ALL transcripts via cosine similarity (`<=>` operator, pgvector).
3. THE system SHALL pass only the retrieved chunks as context to the LLM, with a system prompt that: (a) forbids inventing information, (b) requires answers cite their sources by timestamp, (c) requires a polite "could not find it in these transcripts" response that names the covered topics when no retrieved chunk is relevant.
4. THE answer SHALL include the list of citations used (transcript file, expert, timestamp, quote).
5. If the question is off-topic (no relevant chunks above a similarity threshold), THE system SHALL return a graceful, friendly "not covered" response rather than guessing — generated by the LLM with a dedicated scope system prompt so replies are warm and varied; a canned message is the last-resort fallback when the LLM is unavailable.
6. Greetings, pleasantries, and capability questions (e.g. "hi", "thank you", "what can you do?") SHALL short-circuit to a conversational scope reply (no retrieval) produced by the LLM from the same scope system prompt, cached per question.
7. Every answer SHALL include the verbatim-quote section (hybrid search, no LLM) in addition to the synthesized, cited answer (see Requirement 3).
8. THE endpoint SHALL be stateless; question history is the responsibility of the frontend, not the backend.

### Requirement 6: Source Traceability and Hallucination Prevention

**User Story:** As an interviewer, I want every important answer and quote to be defensible against the raw transcripts, proving the application does not fabricate content.

#### Acceptance Criteria

1. Every answer and every quote returned by the API SHALL carry at least one citation `{transcript_file, expert_name, market, timestamp, quote}`.
2. Quote verification SHALL be performed programmatically (substring match) as the final gate before any quote is returned.
3. THE system prompt SHALL include operational rules: "Only use the provided context. Never add information not present in the context. If the context does not answer the question, say so politely. Never answer harshly or robotically."
4. THE LLM SHALL be configured with low temperature (0.0–0.2) for analysis and quote tasks to reduce variance/hallucination.
5. Retrieved chunks SHALL be truncated/size-capped before prompting to prevent context overflow and to keep prompts within the token budget.
6. THE system SHALL cache deterministic LLM results keyed by `(task, question, context-hash)` to avoid repeat cost and unstable output.

### Requirement 7: Frontend User Experience (Streamlit)

**User Story:** As a demo reviewer, I want a simple usable single-page app with clearly separated sections for interview-guide answers, themes/disagreements, and Q&A chat, so that I can validate each deliverable in under a minute.

#### Acceptance Criteria

1. THE frontend SHALL be a Streamlit single-page app with tabs: "Interview Guide Answers", "Themes & Disagreements", and "Ask a Question".
2. In "Interview Guide Answers", THE UI SHALL render each of the 6 questions, and for each expert show the generated answer with expandable citations (timestamp + quote).
3. In "Themes & Disagreements", THE UI SHALL render a list of theme cards per topic, each labelled `Consensus` / `Disagreement` / `Emphasis`, with expert citations beneath.
4. In "Ask a Question", THE UI SHALL provide a chat-style input; each assistant reply SHALL render the LLM answer, its citations, and the verbatim quote cards (transcript, expert, timestamp, quote text) together.
5. THE UI SHALL handle loading states (spinner during LLM calls) and display API errors gracefully without crashing. Interview-guide answers and themes SHALL be rendered progressively from the NDJSON stream endpoints (`/interview-guide/stream`, `/themes/stream`) as batches/topics complete.
6. THE UI SHALL render the interview-guide and themes from frontend session state once a stream completes, so a rerun (tab click, chat input, any widget interaction) never restarts the stream silently. A failed stream SHALL surface an error with an explicit Retry action instead of re-streaming on every rerun.
7. THE UI SHALL persist the chat conversation in frontend session state; messages must remain visible across reruns, with new turns only appended when a new question is submitted.
8. In "Ask a Question", THE UI SHALL render the message history inside a fixed-height scrollable container with the chat input pinned at the bottom, so the page does not grow and only the chat area scrolls.
9. THE UI SHALL call the FastAPI backend over HTTP; no LLM or DB access from the frontend layer.

### Requirement 8: Transcript Upload, Versioning, and Soft-Delete (Backend)

**User Story:** As an operator, I want to add or replace a transcript by uploading a file (multiple at once) so the corpus is updated without shell access to the server, while older versions of a file stay hidden and the affected cached analysis is refreshed.

#### Acceptance Criteria

1. THE system SHALL expose `POST /api/v1/transcripts/upload` accepting multipart `.txt` files (multiple per request, max 5 MB each) and SHALL return a per-file result reporting `uploaded`, `replaced`, or `error` with a reason.
2. THE system SHALL reject non-`.txt` files and malformed transcripts per file without failing the whole batch.
3. Uploading a filename that already has an active transcript SHALL soft-delete the previous version (`is_active = false`) and insert a new active row with an incremented `version`; only one active version SHALL exist per filename (partial unique index on `filename WHERE is_active`).
4. Retrieval (vector + keyword search), counts, and the transcript list SHALL consider only active transcripts, so replaced files disappear from all analysis.
5. `GET /api/v1/transcripts` SHALL list active transcripts with their metadata and chunk counts.
6. THE system SHALL auto-ingest all `.txt` files in `datas/` at startup whenever the database holds no active transcripts (`SEED_ON_STARTUP`, default enabled) — a best-effort, idempotent operation that never blocks startup and makes analysis usable immediately without a manual ingest endpoint.
7. Uploading a transcript SHALL purge the in-memory interview-guide cache for that filename so the next guide request regenerates it.

### Requirement 9: Internal Traceability (Record Keeping)

**User Story:** As an operator, I want the backend to keep a durable record of Q&A turns, errors, and Groq usage so I can audit what happened after the fact without trusting memory or logs.

#### Acceptance Criteria

1. THE system SHALL record every Q&A turn into a `chat_history` table: question, mode, answer, citations (JSON), verification status, model, and latency.
2. THE system SHALL record every Groq call into a `llm_usage_log` table: task, model, prompt/completion/total tokens, latency, and success — so token spend is auditable per analysis feature.
3. THE system SHALL record failures into an `error_logs` table with level, component, message, exception type, endpoint, method, and structured detail — covering Q&A errors and per-topic/batch analysis failures.
4. Recording SHALL be best-effort: a storage failure SHALL be logged and never abort the primary request or break the streaming contract.
5. Traceability SHALL be inspectable directly via the `chat_history`, `error_logs`, and `llm_usage_log` tables (no operator read endpoints are exposed; the UI consumes live results only).

## Out of Scope

- Authentication / multi-user support (local demo tool only).
- Conversation memory: the backend records every Q&A turn in `chat_history` for traceability, but follow-up answers do not use prior turns — the visible conversation is owned by the frontend.
- PDF/audio transcription support (transcripts are plain text only).
- Deployment to cloud (local run via `make run`).
- File-manager/frontend UI for uploads (uploads are performed via `POST /api/v1/transcripts/upload`; the Streamlit UI is read-only for analysis).
- Operational machinery for 30+ transcript scale: ingestion worker with per-file status tracking, re-embedding diffs, fine-grained chunk versioning, HNSW/IVFFlat index creation and tuning. The application design is scale-ready (file-driven ingestion reading all `.txt` files in `datas/`, `LIMIT top_k` retrieval, configurable constants) so that adding transcripts is additive — but the heavy ingestion/indexing tooling is deliberately out of scope for this story and explained during the demo.
- Fine-tuning of any model.