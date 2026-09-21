## SOLDEF-TRANSCRIPT-ANALYSIS — Hasamex Expert-Call Transcript Analysis

### <u>Project Details</u>

- **Project ID:** HASAMEX-TA
- **Project Name:** Hasamex Expert-Call Transcript Analysis

### <u>Story Details</u>

- **Story ID:** TA-101
- **Story Name:** Transcript Analysis Application
- **Story Description:**
  Build a working application that analyses three expert-call transcripts (European Robotic Surgery Market) from the Hasamex technical case study. The application must parse the transcripts into timestamped chunks, answer the six-question interview guide per expert with traceable citations, extract verified exact quotes, identify common themes and disagreements across experts, and allow free-form cross-transcript Q&A. Every important answer must be traceable to the source transcript (hallucination prevention).

### <u>Table of Contents</u>

- [Section 1: Functional Requirements](#section-1-functional-requirements)
- [Section 2: Non Functional Requirements](#section-2-non-functional-requirements)
- [Section 3: In Scope and Out Scope](#section-3-in-scope-and-out-scope)
- [Section 4: Solution Diagrams](#section-4-solution-diagrams)

---

### <u>Section 1: Functional Requirements</u>

#### <u>1.1 Overview</u>

The application performs end-to-end analysis of three plain-text expert-call transcripts (Transcript_1_France.txt, Transcript_2_Germany.txt, Transcript_3_UK.txt) driven by the six-question interview guide in datas/Interview_Guide.txt. The pipeline is: parse → chunk → embed → store → retrieve → generate.

1. **Ingestion:** Each transcript is parsed to extract expert metadata (name, role, market) from the header and split the body into speaker turns using `MM:SS` timestamp regex. Each expert turn becomes a chunk record with `transcript_id`, `speaker`, `timestamp`, `content`, and a `speaker_index` (IN_00, EX_00, ...) for ordering and idempotency. To keep chunks self-contained, the interviewer question that precedes an expert answer is bundled into that chunk's content as a `Q:` prefix — the answer then carries the timeframe/scope it relies on (e.g. "next three to five years"). Interviewer-only turns are not stored as separate chunks.
2. **Embedding:** Every chunk is embedded with `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions) locally — no external embedding API.
3. **Storage:** Chunks + embeddings are stored in PostgreSQL with the pgvector extension (cosine similarity via `<=>`). Ingestion is idempotent (`ON CONFLICT DO NOTHING` on transcript_id + speaker_index).
4. **Interview Guide Answers:** For each of the 6 questions and each expert, retrieval is scoped to that expert's transcript only, and the LLM (Groq, open-source model) generates an answer with citations. Retrieval per-expert prevents cross-expert contamination.
5. **Exact Quote Extraction:** Built into the chat — EVERY question returns hybrid search (semantic + keyword) verified verbatim chunks with timestamps alongside the LLM answer, so no mode selection is needed.
6. **Themes & Disagreements:** Per interview-guide topic, chunks from all three experts are retrieved and the LLM returns a theme breakdown labelled `Consensus` / `Disagreement` / `Emphasis` with citations.
7. **Cross-Transcript Q&A:** The user's free-form question is embedded, top-K chunks are retrieved across ALL transcripts via cosine similarity, and the LLM generates a grounded answer with citations — plus verified verbatim quotes for every question. When nothing relevant is found (or for greetings/capability questions), a dedicated scope system prompt drives the LLM to produce a warm, varied conversational scope reply; canned strings are only the fallback if the LLM is unavailable.

The application follows the layered architecture mandated by the project standards: Routes → Middleware → Services → Repositories → Data Store, with Groq LLM and local sentence-transformers accessed via client modules. A Streamlit frontend consumes the FastAPI backend. The UI is simple and usable: tabs for Interview Guide Answers, Themes & Disagreements, and Ask a Question (which includes exact-quote retrieval).

#### <u>1.2 Requirement Details</u>

- **FR-001: Transcript Parsing and Ingestion**
- **FR-002: Interview Guide Answering (Per Expert)**
- **FR-003: Exact Quote Extraction with Verification**
- **FR-004: Theme and Disagreement Identification**
- **FR-005: Cross-Transcript Question Answering (RAG Chat)**
- **FR-006: Citation and Hallucination Control**
- **FR-007: Streamlit Frontend**
- **FR-008: Internal Traceability (Record Keeping)**

---

##### <u>1.2.1 FR-001: Transcript Parsing and Ingestion</u>

##### Description:
The application reads all transcripts from the `datas/` directory at startup, parses them into structured, timestamped chunks, embeds each chunk, and persists everything into PostgreSQL (pgvector) idempotently.

##### Input Source Files:

| File | Expert | Role | Market |
|------|--------|------|--------|
| `datas/Transcript_1_France.txt` | Dr. Jean Martin | Head of Urology | France |
| `datas/Transcript_2_Germany.txt` | Anna Keller | Former Hospital Procurement Director | Germany |
| `datas/Transcript_3_UK.txt` | Dr. Emily Carter | Consultant Urologist | United Kingdom |

##### Parsing Rules:
- **Header:** First three non-empty lines map to `Expert N – Name` (expert_name), `Role: ...` (expert_role), `Market: ...` (market).
- **Body:** The remainder is split on lines matching timestamp regex `^\d{1,2}:\d{2}$` (handles `MM:SS`). Each timestamped line starts a new turn; text accumulates until the next timestamp.
- **Speaker:** Determined from the speaker label prefix (`Interviewer:` or expert name `Dr. Martin:` / `Anna Keller:`). If the line does not start with a known label, the previous speaker is inherited.
- **Chunk record fields:** `transcript_id` (FK), `speaker` (`Interviewer` or `Expert`), `speaker_index` (sequential `IN_00`, `EX_00`, ...), `timestamp` (`MM:SS`), `content` (trimmed, non-empty; expert chunks prefixed with the preceding interviewer question as `Q: ...\nA: ...`), `embedding`.

##### Storage & Idempotency:
- Tables: `transcripts` and `chunks` (ER diagram in `design/er_diagram.mmd`).
- Chunks have a unique key on `(transcript_id, speaker_index)` enabling `INSERT ... ON CONFLICT DO NOTHING`.
- Re-running ingestion re-parses files but does NOT duplicate rows; chunk counts reported are the final counts.

##### Embedding:
- Model: `all-MiniLM-L6-v2`, 384 dimensions.
- Run locally via `sentence-transformers`; no API key required.

##### Acceptance Criteria:
- All 3 transcripts parsed into chunks with correct expert metadata.
- Every chunk has a timestamp, speaker, and speaker_index; timestamps are preserved verbatim (`MM:SS`).
- Embeddings stored as `vector(384)` in pgvector; cosine search works via `<=>`.
- Re-running ingestion does not create duplicates (idempotency verified by counts).
- `/ready` reports transcripts_count and chunks_count.

---

##### <u>1.2.2 FR-002: Interview Guide Answering (Per Expert)</u>

##### Description:
For each of the six interview-guide questions, the application returns an answer generated from the specific expert's own transcript chunks only, with citations to the source transcript.

##### Questions (from `datas/Interview_Guide.txt`):
1. How would you describe current adoption of robotic surgery in your market?
2. What are the main barriers to adoption?
3. How important are hospital budgets and ROI in purchasing decisions?
4. How important are surgeon training and clinical outcomes?
5. What adoption trend do you expect over the next 3–5 years?
6. What is the typical hospital decision-making timeline for purchasing a new robotic system?

##### Retrieval (scoped per expert, question↔question):
- The guide question alone is embedded with the same sentence-transformers model.
- Every chunk stores two vectors: `embedding` over the bundled `Q: …\nA: …` text (used by the Themes and Q&A indexes) and `question_embedding` over only its interviewer question (the guide index).
- The guide matches question-to-question on `question_embedding` — no distance cutoff — because the guide questions are fixed, so the near-verbatim question match always ranks the correct chunk.
- Top-2 chunks retrieved from the expert's transcript only: `WHERE transcripts.id = :expert_id AND chunks.question_embedding IS NOT NULL ORDER BY chunks.question_embedding <=> :question_vec LIMIT 2`.
- This guarantees no cross-expert leakage in the answer.

##### Generation:
- LLM tasks: interview-guide answer.
- Prompt contract (per prompt-engineering standards): Role, Mission, Context (retrieved chunks only), Inputs, Constraints, Rules, Critical Rules, Output Contract, Error Handling.
- Output is strict JSON, answered in batches of up to 3 questions per LLM call:
  `{"answers": [{"question_id": int, "answer": str, "citations": [{"transcript_file": str, "expert_name": str, "market": str, "timestamp": str, "quote": str}]}]}`.
- Temperature: 0.0–0.2 for stable, grounded output.
- If no relevant chunk is retrieved, answer = "Not mentioned in this transcript", citations = [].
- Failure containment: if an LLM call for a batch fails after retries, each question in that batch falls back to the friendly message "Oops - we hit a snag generating this one..." with empty citations; the stream still emits every batch and a final `done` event (a failed batch never leaves the stream unfinished).

##### Caching:
- Deterministic result cached keyed by `(task="interview_guide_batch", model, transcript filename, question-text + retrieved-context hash)` to avoid repeat cost and variance.

##### Acceptance Criteria:
- 6 questions × 3 experts = 18 answers returned (or cached).
- Every answer cites at least one `(transcript_file, expert_name, timestamp, quote)` unless "Not mentioned".
- Citations come only from the queried expert's transcript.
- Answers are testable: every citation quote exists (substring) in the cited transcript.

---

##### <u>1.2.3 FR-003: Exact Quote Extraction with Verification (via Chat)</u>

##### Description:
Quote retrieval is built into the chat endpoint — there is no separate quotes page/endpoint. EVERY call to the chat endpoint returns a verbatim-quote section in addition to the LLM answer: raw transcript chunks, each verified programmatically and cited with its timestamp, so claims can be checked word-for-word.

##### Hybrid Search (quotes section):
- Semantic: embed the query, cosine search across all chunks (`<=>`).
- Keyword: ILIKE / tsvector match on `chunks.content` for exact-term recall (e.g. "budget approval").
- Results merged; deduplicated by chunk id; top-K returned.

##### No-LLM guarantee:
- The quotes section is the raw retrieval output — no LLM generation or rewriting. No AI interpretation is applied; the LLM is only used for the separate synthesis answer.

##### Quote Verification (hallucination gate):
1. Retrieved chunk content is used verbatim (no LLM quote selection).
2. Programmatic check: retrieved top-K chunks pass substring relevance filtering (`query_term in content` for keyword hits; semantic hits verified for content validity).
3. Each returned quote carries `verification_status: "verified"`.
4. Any chunk failing verification is dropped and never silently fabricated.

##### Multiple sources:
- When multiple chunks from different experts match, ALL qualified quotes are returned, each with its own citation — the system does not collapse multiple sources into one unverifiable composite.

##### Acceptance Criteria:
- Quotes are exact substrings of stored chunk content (verifiable).
- Each quote carries transcript_file, expert_name, market, timestamp.
- The quotes section performs zero additional LLM calls.
- Multiple matching experts each surface with their own citation.

---

##### <u>1.2.4 FR-004: Theme and Disagreement Identification</u>

##### Description:
The application surfaces, per interview-guide topic, what the three experts agree on (consensus), where they differ (disagreement), and where they simply differ in emphasis.

##### Process:
- For each of the 6 topics/question, run per-expert similarity search (top-K within each expert transcript, no distance cutoff) and merge the scoped results by chunk id (each chunk tagged by expert). Per-expert scoping prevents the single-global-search failure mode where a topic's passages from one expert rank below the global cutoff and silently vanish.
- Assemble the retrieved chunks into one context block tagged `[timestamp] [expert (market)] [file]` (real filename exposed so citations carry true source filenames, RULE-205).
- LLM called with `task="themes"`, `max_tokens=4096` (room for the full themes JSON + citations), typed output contract returning:
```
{
  "topic": str,
  "themes": [
    {"type": "Consensus"|"Disagreement"|"Emphasis",
     "summary": str,
     "citations": [{transcript_file, expert_name, market, timestamp, quote}]}
  ]
}
```
- Labelling rule: experts state conflicting facts/numbers/timelines → `Disagreement`; experts agree but weight factors differently → `Emphasis`; experts converge on the same point → `Consensus`.
- Per-topic isolation: each topic is analysed in its own LLM call. Malformed theme/citation records (non-dict `themes`/`citations` items) are skipped with a logged warning and unknown labels default to `Emphasis`. A transient LLM failure on one topic (caught per-topic) flags that entry as an error (`error: true`) — it never aborts the remaining topics, and the stream always ends with a final `done` event. The UI shows an explicit "snag – please refresh" message for a failed topic, which is distinct from a successfully analysed topic that finds no themes ("No themes identified for this topic.").

##### Expected outcome (from transcript analysis):
- Q6 (purchase timeline): France 6–12 months, Germany 9–18 months, UK 6–9 months → surfaced as `Disagreement` (numeric range) citing all three timestamps.
- Training importance → `Consensus` / `Emphasis` (all three stress training; UK weights training capacity equal to funding).
- ROI/economics → mostly consensus that economics is critical; UK adds clinical strategy balance → `Emphasis`.

##### Acceptance Criteria:
- Theme list grouped by all 6 topics.
- Each theme labelled precisely as one of Consensus / Disagreement / Emphasis.
- Each theme carries citations from the involved experts (name, market, timestamp, quote).
- Numeric disagreements (timeline) surfaced with explicit range and all 3 sources.
- A transient failure on one topic is flagged as an error entry; the remaining topics proceed and the stream always terminates with `done`.

---

##### <u>1.2.5 FR-005: Cross-Transcript Question Answering (RAG Chat)</u>

##### Description:
Single chat endpoint. Every question returns BOTH: (1) a RAG answer — free-form question answered from the most relevant chunks across ALL transcripts with citations; and (2) verified verbatim quotes — hybrid-search chunks returned alongside (see FR-003). No mode selection exists; the response always contains both.

##### Flow (every question):
1. User question embedded (`all-MiniLM-L6-v2`).
2. Top-K (default 5) chunks retrieved across all transcripts via `ORDER BY embedding <=> :query_vec LIMIT :k`.
3. Retrieved chunks become the grounding context for the LLM (temperature ≤ 0.2).
4. LLM returns answer + citations in typed JSON contract.
5. In parallel, hybrid search (semantic + keyword) retrieves verbatim chunks for the quotes section; merged, deduplicated by chunk id.
6. Route returns `{question, mode, answer, citations, quotes}` — frontend renders the answer + Sources + verbatim quotes.

##### System prompt critical rules:
- Use ONLY the provided context.
- Never add information not present in the context.
- If context does not answer the question, reply politely that the answer could not be found in these transcripts and name what the interviews do cover.
- Cite each claim with its source chunk (transcript, expert, timestamp).

##### Empty/relevance guard:
- If all retrieved chunks fall below a similarity threshold, route the question to the LLM scope reply: warm, varied, conversational, naming the covered topics (no guessing). Canned messages are the fallback only if the LLM call fails.
- Greetings, pleasantries, and capability questions (e.g. "hi", "thank you", "what can you do?") short-circuit to the same LLM scope reply (no retrieval), produced from the scope system prompt and cached per question.

##### Statelessness:
- The endpoint is stateless; the frontend owns conversation history display.

##### Acceptance Criteria:
- Any question on adoption/barriers/ROI/training/trends/timeline answered with citations.
- Every response also includes verified verbatim quotes (hybrid search, no LLM) — no mode selection or intent detection required.
- Greetings/pleasantries and off-topic or unanswerable questions receive an LLM-generated conversational scope reply (varied wording, names the covered topics); canned messages are only the fallback if the LLM is unavailable.
- Every citation is verifiable against the source transcript.
- No cross-tenant or cross-user state (stateless).

---

##### <u>1.2.6 FR-006: Citation and Hallucination Control</u>

##### Description:
Cross-cutting mechanism guaranteeing every important answer/quote is traceable to the transcript and nothing is invented.

##### Mechanisms:
1. **Strict typing:** Every LLM task has a typed output contract (Pydantic DTO) validated before returning.
2. **Grounding:** LLM receives only retrieved chunks as context (never the whole corpus unbounded; chunk size capped).
3. **Quote gate:** Programmatic substring verification for all quotes (FR-003).
4. **Prompt rules:** Explicit "never invent, cite sources, say not mentioned" rules with stable rule IDs (per prompt-engineering standards).
5. **Temperature:** 0.0–0.2 for analysis/quotes.
6. **Retrieval cap:** default top_k = 5, configurable, bounding prompt token usage and cost.

##### Acceptance Criteria:
- 100% of returned quotes verified as substrings of source text.
- Answers with no grounding return "Not mentioned..." instead of guessing.
- No raw LLM errors or internal traces leak to the client (fail-closed on parse/validation errors).
- Deterministic results cached (cost + variance reduction).

---

##### <u>1.2.7 FR-007: Streamlit Frontend</u>

##### Description:
A simple single-page Streamlit app exposing three analysis views, calling only the FastAPI backend. Quote retrieval is available inside the chat tab (FR-003/FR-005), so no separate quotes page exists.

##### Tabs:
| Tab | Content |
|-----|---------|
| Interview Guide Answers | 6 questions; per expert answer with expandable citations (timestamp + quote) |
| Themes & Disagreements | Per-topic theme cards labelled Consensus / Disagreement / Emphasis with citations |
| Ask a Question | Chat-style input; assistant reply with LLM answer + citations AND verbatim quotes for every question |

##### Behaviour:
- Spinner/loading states during backend calls.
- Errors surfaced gracefully (stale connection, 5xx, rate-limit) without crashing the app, with an explicit Retry action; a failed/partial stream is cached in session state so reruns do not silently re-stream it.
- Guide/themes render from frontend session state once loaded — tab clicks and widget interactions never retrigger the stream.
- Chat conversation persisted in session state; turns remain visible across reruns.
- Chat layout: message history renders inside a fixed-height scroll container with the chat input pinned at the bottom, so the page never grows and only the chat area scrolls (the input sits below the last message, after every rerun).
- The app launches with `.streamlit/config.toml` (`client.toolbarMode = "viewer"`) which removes developer-only toolbar buttons (deploy/pop-out/rerun) while keeping the running-status indicator.
- No DB or LLM access from the frontend — all data via the HTTP API.

##### Acceptance Criteria:
- All 3 tabs render and load data from the backend.
- Citations displayed under each answer/quote (expandable where relevant).
- App does not crash on backend unavailability; shows a clear error message.

---

##### <u>1.2.8 FR-008: Internal Traceability (Record Keeping)</u>

##### Description:
A durable record of what the backend actually did — Q&A turns, errors, and every Groq call — stored in three tables, so an operator can audit behaviour after the fact without trusting memory or only grepping logs.

##### Tables:
| Table | Rows |
|-------|------|
| `chat_history` | One row per Q&A turn: question, mode (`answer`), answer, citations (JSON), verification status, model, latency, timestamp |
| `error_logs` | One row per recorded failure: level, component (`qa`/`themes`/`guide`/…), message, exception type, endpoint, method, structured detail (JSON), timestamp |
| `llm_usage_log` | One row per Groq call: task (`qa_answer`/`themes`/`guide_batch`/…), model, prompt/completion/total tokens, latency, success, timestamp |

##### Behaviour:
- Recording is **best-effort**: each write opens its own short-lived session; a storage failure is logged and never aborts the primary request or streaming contract.
- The Groq client reports every call (tokens + latency + success) through an injected usage recorder wired in `get_services()`; failed calls are recorded too.
- Service and route error paths record into `error_logs`: theme/guide per-item failures inside the guard clauses, Q&A `LLMError`s in the route.
- Traceability is inspected **directly in the database**; the operator read endpoints (`GET /chat/history`, `/error-logs`, `/llm-usage`) were removed because no client used them.

##### Acceptance Criteria:
- Every Q&A turn, LLM call, and recorded error is persisted to the DB.
- Regardless of DB state, the primary request behaviour (including streaming) is identical — recording can only add a log line.
- The traceability tables are populated correctly (verified via direct SQL).

#### <u>1.3 Project Artifacts</u>

| File | Purpose |
|------|---------|
| `datas/Transcript_1_France.txt` | Source transcript (France) |
| `datas/Transcript_2_Germany.txt` | Source transcript (Germany) |
| `datas/Transcript_3_UK.txt` | Source transcript (UK) |
| `datas/Interview_Guide.txt` | The 6 interview-guide questions |
| `datas/README_CASE.md` | Case study brief |
| `api/openapi.yaml` | Internal API contract |
| `api/external-api.yaml` | External API (Groq) contract |
| `design/er_diagram.mmd` | ER diagram (transcripts + chunks) |
| `template.md` | SD template used to author this document |

#### <u>1.4 Dependencies</u>

| Package | Version (pin) | Purpose |
|---------|---------------|---------|
| Python | >= 3.11 | Runtime |
| `fastapi` | latest stable | Backend framework |
| `uvicorn[standard]` | latest stable | ASGI server |
| `streamlit` | latest stable | Frontend |
| `sqlalchemy[asyncio]` | 2.x | Async ORM |
| `asyncpg` | 0.30.x | Async PostgreSQL driver |
| `pgvector` | 0.3.x | pgvector extension bindings (Python) |
| `psycopg2` / `asyncpg` | — | Driver (asyncpg preferred) |
| `sentence-transformers` | latest stable | Local embeddings (all-MiniLM-L6-v2) |
| `httpx` | latest stable | Groq API client |
| `pydantic` | 2.x | DTOs/validation |
| `pydantic-settings` | latest stable | `.env` config |
| `python-dotenv` | 1.x | Env loading |
| `tenacity` | latest stable | Retry/backoff for Groq |
| `ruff` | latest stable | Lint + format |
| `pytest`, `pytest-asyncio` | latest stable | Tests |

Note: Groq API key from `GROQ_API_KEY` env var (`.env`, never committed). PostgreSQL extension `vector` must exist on the local PostgreSQL 18 instance.

---

### <u>Section 2: Non Functional Requirements</u>

### 2.1 Infrastructure and Deployment

#### <u>2.1.1 Overview</u>

The application runs locally, not deployed. It requires: PostgreSQL 18 with pgvector extension (installed already on the developer machine), Python 3.11+ virtual environment managed with `uv`, a Groq API key, and the sentence-transformers model downloaded on first run. Deployment is `make run` (uvicorn) plus `make run-ui` (streamlit). No cloud resources are used.

#### <u>2.1.2 Requirement Details</u>

##### NFR-001: Local Database Setup

- PostgreSQL 18 with `CREATE EXTENSION vector` (pgvector 0.8.6 installed via precompiled binaries).
- Database name/configurable via `DATABASE_URL` in `.env` (default `postgresql+asyncpg://postgres:Admin123@localhost:5432/hasamex`).
- Tables `transcripts` and `chunks` created idempotently at startup or via a provided init script.
- Vector column type `vector(384)`; cosine distance operator `<=>`.

##### NFR-002: Configuration

- `.env` + `.env.sample`; keys: `GROQ_API_KEY`, `DATABASE_URL`, `LLM_MODEL` (default `openai/gpt-oss-120b`), `EMBEDDING_MODEL` (default `all-MiniLM-L6-v2`), `TOP_K` (default 5), `LOG_LEVEL`.
- Validated at startup via Pydantic Settings; missing `GROQ_API_KEY`/`DATABASE_URL` raises a clear startup error.
- `.env` entries in `.gitignore`.

##### NFR-003: Layer Architecture

- Strict layering: Routes → Services → Repositories → Data Store, per project standards.
- `src/` package layout: `routes/`, `services/`, `repositories/` (+`schema/`), `models/`, `middleware/`, `client/`, `utils/` (+`exceptions/`), `settings.py`, `main.py`.
- DI via `src/services/dependencies.py`.
- Prompt files in `src/prompt/`.

---

### 2.2 Architecture and System Design

#### <u>2.2.1 Security and Compliance</u>

- Groq API key never hardcoded; loaded from environment via Pydantic Settings.
- `GROQ_API_KEY` and `DATABASE_URL` excluded from git through `.gitignore`.
- All SQL via SQLAlchemy ORM / parameterized statements (no SQL injection).
- No secrets, PII leaks, or raw stack traces returned to the client; LLM errors logged server-side, surfaced as generic errors (fail-closed).
- Input validation with Pydantic DTOs on every route.

#### <u>2.2.2 System Performance</u>

- Retrieval bounded: `LIMIT :top_k` (default 5) on vector search → constant-time latency regardless of corpus growth.
- Deterministic LLM results cached keyed by task signature → repeat requests served from memory without LLM cost.
- Local embeddings (sentence-transformers) — no embedding API round-trip; model cached in memory (singleton).
- Chunk size capped before prompting to fit token budgets.
- Hybrid search (semantic + keyword) merges and dedups results; worst-case small (only 3 transcripts ≈ tens of chunks).

#### <u>2.2.3 Availability and Reliability</u>

- Groq client retry: tenacity exponential backoff (5 attempts, 2s→10s) on 5xx only; 429s honor Groq's `Retry-After`/reset headers (sleep-and-retry when <60s, raise `LLMRateLimitError` immediately when ≥60s or unknown — no blind backlog re-fills).
- Graceful degradation: if Groq is down or rate-limited, API returns a structured error, frontend shows retry message.
- Idempotent ingestion → safe restarts.
- Readiness endpoint fails (503) if DB/pgvector/tables unavailable, guiding the demo.

#### <u>2.2.4 Cost Efficiency</u>

- Groq free tier used; open-source models (openai/gpt-oss-120b) — $0 until demo scale.
- Embeddings run locally — zero cost.
- Result caching avoids repeat LLM tokens during demos.
- Total stack cost: $0 (Groq free tier, local PG, local embeddings).

#### <u>2.2.5 Traceability and Observability</u>

- Structured logging (JSON) via `src/utils/logger.py` with fields: timestamp, level, logger, message, `correlation_id`/`task_id`, model, latency, token usage, outcome.
- Log LLM events: request sent (model, task, prompt version), completion (latency, tokens), failure (retry count, error class).
- Log guardrail events: quote `verification_failed`, "not mentioned" decisions, cache hits/misses.
- Logs kept privacy-safe: no raw API keys, no full raw prompt/response bodies by default (configurable debug level).

---

### <u>Section 3: In Scope and Out Scope</u>

#### <u>3.1 In Scope Details</u>

- Parsing of the 3 provided transcripts into timestamped chunks (expert metadata, timestamps, speakers).
- Local embedding generation with sentence-transformers (`all-MiniLM-L6-v2`).
- Idempotent persistence of transcripts + chunks in PostgreSQL/pgvector.
- Per-expert interview-guide answer generation with citations.
- Exact quote extraction with programmatic substring verification (built into chat, no separate endpoint).
- Theme, consensus, disagreement and emphasis analysis per interview-guide topic.
- Free-form cross-transcript Q&A (RAG) with "not mentioned" guard.
- Strict citation + hallucination control (typed contracts, grounding, verified quotes).
- FastAPI backend with versioned routes (`/api/v1`), health/ready endpoints.
- Transcript upload API (`POST /api/v1/transcripts/upload`, `GET /api/v1/transcripts`) with per-file results, soft-replace (`is_active`), and per-filename versioning so replaced files disappear from all retrieval and cached analysis. Corpus population happens automatically via startup auto-seed.
- NDJSON streaming endpoints for interview-guide and themes (`/interview-guide/stream`, `/themes/stream`) so the frontend renders results progressively as batches/topics complete.
- Streamlit frontend with 3 tabs consuming the API.
- Structured logging; rich cache for deterministic LLM outputs.
- `requirements.md`, `er_diagram.mmd`, `openapi.yaml`, `external-api.yaml` artifacts.
- Tests for parser, retrieval, quote verification, services, and routes.
- README with local run instructions.

#### <u>3.2 Out Scope Details</u>

- Authentication / multi-user support (local single-user demo).
- Persistent chat history / session memory on the backend (the visible conversation lives in the frontend; the backend only records Q&A turns into `chat_history` for traceability — see FR-008).
- Traceability recording is best-effort and must never break the primary request or streaming contract.
- Audio / PDF / speech-to-text ingestion (transcripts are plain text only).
- Upload/file-manager *frontend* UI (backend upload endpoints exist; the Streamlit UI is read-only for analysis).
- Operational machinery for storage-layer chunk diffs / cache staleness tracking (soft-delete + versioning covers file replacement; no worker or per-chunk flag system).
- HNSW/IVFFlat vector index creation and tuning (default index/scan order is sufficient at this scale — explain in demo, do not implement).
- Fine-tuning of any model.
- Cloud deployment / Docker images.
- Automatic re-indexing on transcript file changes.

---

### <u>Section 4: Solution Diagrams</u>

#### <u>4.1 UI/UX Design Diagram</u>

**Diagram Location:** Not applicable — diagram sections in the template are skipped per SD generation convention. UI described in FR-007 (3 tabs: Interview Guide Answers, Themes & Disagreements, Ask a Question).

#### <u>4.2 Sequence Diagram</u>

**Flow: Cross-Transcript Q&A (`POST /api/v1/qa/ask`) — combined answer + quotes**

1. Frontend POSTs `{"question": "What slows down adoption in Germany?"}` to `/api/v1/qa/ask`.
2. Route validates request via Pydantic DTO → 422 on invalid input.
3. Service checks `detect_off_topic()`; greetings/capability questions short-circuit to the LLM scope reply (`task="qa_scope"`, no retrieval, cached per question).
4. Service embeds question with sentence-transformers.
5. Repository executes vector search across ALL chunks (`ORDER BY embedding <=> :q LIMIT 5`).
6. If no chunk above similarity threshold → service routes to the same LLM scope reply (warm, conversational, names covered topics) with empty citations; canned messages only if the LLM call fails.
7. Otherwise service assembles prompt (system rules + retrieved chunks + user question).
8. GroqClient calls LLM (tenacity retry on 5xx; 429s drained via reset headers/`Retry-After` or raised as `LLMRateLimitError`).
9. Service parses+validates JSON against typed response contract.
10. For every citation quote, service runs substring verification against chunk content.
11. In parallel, `_collect_quotes()` merges semantic + keyword hits (dedup by chunk id) into the `quotes` section — raw transcript text, no LLM; keyword-hit chunks flagged `verified`.
12. Route returns `{question, mode, answer, citations, quotes}` → frontend renders answer + Sources + verbatim quotes.

**Flow: Ingestion (auto-seed at startup)**

Triggered from the FastAPI lifespan when the database has no active transcripts
(guarded by `Settings.seed_on_startup`, default true); the bulk-ingest
`POST /api/v1/transcripts` endpoint was removed in the API simplification.

1. Service lists `.txt` files in `datas/`.
2. For each file: parse header (expert/role/market), split body by timestamps, assign speaker/speaker_index.
3. Embed each chunk with sentence-transformers.
4. Repository upserts transcripts then chunks (`ON CONFLICT DO NOTHING`).
5. Returns final transcripts_count and chunks_count.
6. Best-effort: any failure is logged, never blocks startup, and the seed is skipped whenever transcripts already exist (restart-safe).

**Flow: Transcript Upload (`POST /api/v1/transcripts/upload`)**

1. Operator posts one or more `.txt` files (multipart) from any client.
2. Route validates each file: `.txt` extension, non-empty, ≤ 5 MB; per-file errors are reported without failing the batch.
3. Service parses the raw content, embeds its expert chunks, and calls `upload_version` in the repository.
4. Repository deactivates any active transcript with the same filename (`is_active = false`), assigns the next `version` (max + 1), inserts the new transcript and its chunks, and commits in one transaction.
5. Service purges the in-memory interview-guide cache prefix for that filename.
6. Route returns per-file results: `uploaded` or `replaced` (with transcript_id, version, chunk_count) or `error` with reason.

#### <u>4.3 Architectural Diagram</u>

```
                          ┌───────────────────────────────┐
                          │   Browser (User / Reviewer)   │
                          └──────────────┬────────────────┘
                                         │
                                         ▼
                          ┌───────────────────────────────┐
                          │  Frontend: Streamlit (app.py) │
                          │  Tabs: Guide | Themes         │
                          │         | Ask a Question      │
                          └──────────────┬────────────────┘
                                         │  HTTP /api/v1
                                         ▼
                          ┌───────────────────────────────┐
                          │  Backend: FastAPI (main.py)   │
                          │  Routes → Services → Repos    │
                          └───────┬───────────────┬────────┘
                                  │               │
                    ┌─────────────▼──────┐  ┌─────▼───────────────┐
                    │ sentence-transform │  │  PostgreSQL (pgvect)│
                    │ ers (Local embeds) │  │  ├─ transcripts     │
                    │ all-MiniLM-L6-v2   │  │  └─ chunks (vec384) │
                    └─────────────┬──────┘  └─────┬───────────────┘
                                  │               │
                    ┌─────────────▼──────┐        │ cosine (<=>)
                    │  GroqClient        │        │
                    │  (LLM gpt-oss-120b)│────────┘
                    └─────────────┬──────┘
                                  │  HTTPS
                    ┌─────────────▼──────┐
                    │  Groq API (cloud)  │
                    │  Open-source model │
                    └────────────────────┘
```

Key decisions:
- **Embeddings local** → zero cost, works offline for retrieval; only LLM calls hit Groq.
- **PG + pgvector** → reuse existing PostgreSQL, free, SQL-native queries.
- **Groq + open-source LLM** → free tier, fast inference, no GPU needed locally.