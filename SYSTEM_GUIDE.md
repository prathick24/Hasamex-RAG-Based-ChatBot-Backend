# Hasamex — The Whole System, Explained End-to-End

A complete, plain-English tour of the Hasamex expert-transcript analysis app: **what** it does, **why** it is built this way, **which** technologies were chosen, and **how** every file and function works. Written so a developer, a non-developer, or an interviewer can understand it.

---

## 1. Executive summary (read this if nothing else)

This is an **AI research assistant that reads expert interview transcripts and answers questions about them — without ever inventing facts**.

Specifically, it ingests three real expert-call transcripts about the **European robotic surgery market**, then provides four features:

1. **Interview Guide Answers** — 6 standard questions answered separately per expert, each with verbatim quotes + timestamps as proof.
2. **Themes & Disagreements** — what all experts *agree* on (Consensus), where facts *conflict* (Disagreement), and where they just *weight things differently* (Emphasis).
3. **Ask a Question** — free-form Q&A across all transcripts; every answer includes the LLM synthesis **plus** verbatim transcript quotes with timestamps.
4. **Traceability** — every Q&A turn, every LLM error, and every LLM call (tokens + latency) is stored and can be inspected.

**The core idea (why the project exists):** sales / market-research analysts cannot re-read hours of expert interviews, but they also cannot trust an AI that might hallucinate. The whole system is designed so that **every claim an AI makes is forced to point back to the exact transcript line it came from** — and if it can't, it must say "not found" instead of guessing.

**Stack in one sentence:** a Python **FastAPI** backend does parsing, embedding and retrieval (PostgreSQL + pgvector), calls the **Groq** free-tier LLM to write grounded answers, and a **Streamlit** web UI shows it all — with an in-memory cache, streaming results, and full logging.

---

## 2. What you see from the outside (user flow)

A user opens the web app (`http://localhost:8501`):

- **Tab 1 — Interview Guide Answers.** Six questions (adoption, barriers, budgets/ROI, training, 3–5y outlook, purchase timeline) each expanded per expert, with a "Sources" panel showing the exact quote, expert, market and timestamp.
- **Tab 2 — Themes & Disagreements.** Six topics, each with themes labelled ✅ Consensus / 🔄 Disagreement / ⚖️ Emphasis, each with citations.
- **Tab 3 — Ask a Question.** A chat box. Every question returns both the LLM's cited synthesis and the verbatim transcript lines (with a verification checkmark) — e.g. *"what did Anna Keller say about barriers?"* shows the answer plus the exact quotes you can check word-for-word.

On a cold system these tabs stream in progressively (questions appear first, answers fill in as they finish) so the page never just hangs.

---

## 3. Overall architecture

```
┌─────────────────────────────┐
│  Streamlit frontend (:8501) │   frontend/app.py
│  3 tabs, streaming, chat    │
└──────────────┬──────────────┘
               │  HTTP / NDJSON streaming
┌──────────────▼──────────────┐
│  FastAPI backend (:8000)    │   main.py
│  routes/ analysis · qa ·    │
│  ingest · audit · system    │
├─────────────────────────────┤
│  Services layer             │
│  qa / themes / interview-   │
│  guide / ingest / citation  │
│  audit / cache              │
├─────────────────────────────┤
│  Repositories + models      │
│  SQLAlchemy async ORM       │
├──────────────┬──────────────┤
│  PostgreSQL  │  Surrounding │
│  (pgvector)  │  services    │
│              │  ├ Groq LLM  │
│              │  ├ local     │
│              │  │ embedder  │
│              │  └ in-memory │
│              │    LRU cache │
└──────────────┴──────────────┘
```

Layers and their responsibilities:

| Layer | Files | Job |
|---|---|---|
| **Api layer** | `main.py`, `src/routes/*` | HTTP endpoints, validation, error wrapping, streaming |
| **Service layer** | `src/services/*` | Business logic: orchestration, prompts, caching, verification |
| **Repository layer** | `src/repositories/*` | All database access (SQLAlchemy), nothing else |
| **Model layer** | `src/models/*` | Table definitions (ORM classes) |
| **Client layer** | `src/client/*` | Talk to the two external dependencies: Groq LLM + local embedder |
| **Utils** | `src/utils/*` | Parser, logger, exceptions |
| **Prompt layer** | `src/prompt/*` | The prompt templates the LLM sees (system + user messages) |
| **Frontend** | `frontend/app.py` | The whole Streamlit UI |

**Data travels like this (simplified):**

```
Transcript .txt ──parser──► turns ──embedder──► vectors(+text) ──► Postgres/pgvector
User question ──embedder──► query vector ──similarity search──► top-k chunks
  ──► build "context" (expert + timestamp + verbatim text)
  ──► LLM prompt (context + question) ──► JSON answer with citations
  ──► verify each citation is a real substring of the chunks ──► send to UI
```

---

## 4. Project layout

```
hasamex-be/
├── main.py                     FastAPI entry point (app, middleware, startup)
├── Makefile                    dev shortcuts (run, test, lint, …)
├── pyproject.toml              dependencies + tool config (ruff, pytest)
├── .env.sample                 config template (DB URL, Groq key)
├── README.md                   project readme
├── SYSTEM_GUIDE.md             this document
├── DEVELOPMENT_CHALLENGES.md   history of every real bug + the fix (interview gold)
├── design/
│   ├── requirements.md          functional requirements & acceptance criteria
│   └── SOLDEF-TRANSCRIPT-ANALYSIS.md   product spec (features/out-of-scope)
├── api/
│   ├── openapi.yaml             auto-exported API spec (visit /docs too)
│   └── external-api.yaml        description of the external services used
├── datas/
│   ├── Transcript_1_France.txt   Dr. Jean Martin, France
│   ├── Transcript_2_Germany.txt  Anna Keller, Germany
│   ├── Transcript_3_UK.txt       Dr. Emily Carter, UK
│   ├── Interview_Guide.txt       the 6 guide questions
│   └── README_CASE.md           the original case requirements
├── src/
│   ├── settings.py              all config values (env-driven)
│   ├── models/                  ORM tables: transcript.py, audit.py, __init__.py
│   ├── repositories/
│   │   ├── database.py          async engine + session + startup migrations
│   │   ├── transcript_repository.py   all transcript/chunk/vector queries
│   │   ├── audit_repository.py        chat/error/usage writes
│   │   └── schema/              Pydantic response models (schemas.py, response.py)
│   ├── services/
│   │   ├── qa_service.py        answer + verbatim quotes (combined)
│   │   ├── theme_service.py     consensus/disagreement/emphasis themes
│   │   ├── interview_guide_service.py  guide answers per expert (batched)
│   │   ├── ingest_service.py    file discovery, parsing, embedding, upload
│   │   ├── citation_utils.py    citation building + verification (anti-hallucination)
│   │   ├── cache.py             in-memory LRU + key hashing
│   │   ├── dependencies.py      shared singletons (embedder, Groq client, settings)
│   │   └── audit_service.py     best-effort traceability recorders
│   ├── routes/                  api.py (router bundle), analysis.py, qa.py,
│   │                            ingest.py, system.py
│   ├── client/                  groq_client.py (LLM + rate limiter),
│   │                            embedder_client.py (local embeddings)
│   ├── prompt/                  qa.py, themes.py, interview_guide.py (templates)
│   ├── middleware/              middleware.py (correlation id + logging)
│   └── utils/
│       ├── parser.py            .txt transcript → structured turns
│       ├── logger.py            structlog JSON logging setup
│       └── exceptions/          exceptions.py, error_codes.py, error_responses.py
├── tests/                       130+ tests (parser, repos, services, clients, routes)
└── frontend/app.py              the entire Streamlit UI
```

---

## 5. Every package, explained (interview-safe answers)

### Core web/db
| Package | What it is | Why we use it |
|---|---|---|
| **fastapi** | A modern Python web framework for building APIs | Async, fast, auto-generates `/docs` (OpenAPI). The HTTP backbone. |
| **uvicorn** | ASGI web server | Runs the FastAPI app (`main:app`). |
| **sqlalchemy[asyncio]** | Object-relational mapper | Lets us write table classes (models) and query them without raw SQL. Async engine means the DB never blocks the event loop. |
| **asyncpg** | Fast PostgreSQL driver for async | The low-level driver SQLAlchemy uses to talk to Postgres. |
| **pgvector** | PostgreSQL extension for embeddings | Stores 384-dimension vectors in the `chunks` table and runs similarity search in the database (`<->` cosine distance). |

### AI / ML
| Package | What it is | Why we use it |
|---|---|---|
| **groq (via httpx)** | The Groq cloud LLM API (OpenAI-compatible `/chat/completions`) | Cheap/fast LLM to generate grounded answers. Model: `openai/gpt-oss-120b`, JSON mode on. Calls made directly with **httpx**, not a Groq SDK — fewer deps, more control. |
| **sentence-transformers** | Library for text embeddings | Runs **locally** (`all-MiniLM-L6-v2`, 384 dims) so embedding costs nothing and never needs the network. |
| **numpy** | Numeric arrays | Underlies embeddings output handling. |

### API / HTTP
| Package | What it is | Why we use it |
|---|---|---|
| **httpx** | Modern HTTP client (sync + async) | Backend calls Groq; frontend calls backend. Streams NDJSON for progressive rendering. |
| **tenacity** | Generic retry library | Retries Groq calls (5 attempts, exponential backoff) on 429/5xx. |
| **pydantic / pydantic-settings** | Data validation + env config | Validates every request/response; `Settings` class reads `.env`. |
| **python-dotenv** | Loads `.env` | Lets pydantic-settings read `DATABASE_URL`, `GROQ_API_KEY` from a file. |

### Observability & logging
| Package | What it is | Why we use it |
|---|---|---|
| **structlog** | Structured (JSON) logging | Logs are machine-readable — every line is `{timestamp, level, module, function, message, ...}`. Enables `message="groq_request", model=...` style context without breaking `logging`. |

### UI
| Package | What it is | Why we use it |
|---|---|---|
| **streamlit** | Builds data web apps from Python | The whole frontend is ~440 lines of Python. Buttons, tabs, chat, expanders — no HTML/JS. |

### Dev / quality
| Package | What it is | Why we use it |
|---|---|---|
| **pytest + pytest-asyncio** | Test framework w/ async support | 130+ async tests cover parser → repos → services → routes. |
| **pytest-cov / coverage / diff-cover** | Coverage tracking | Enforces coverage on changed lines (diff-cover --fail-under=80). |
| **ruff** | Fast Python linter/formatter | `make lint`, `make format`. Selections E,F,I,UP,B,SIM,RUF. |
| **hatchling** | Build backend | Keeps packaging simple (`packages = ["src"]`). |

---

## 6. Data model

Defined in `src/models/transcript.py` and `src/models/audit.py`. Tables are created automatically at startup (`Base.metadata.create_all` + small hand-written "startup migrations") — **there is no Alembic** in this project (a deliberate simplification; see §11).

### `transcripts` — one row per expert interview (with versioning)
| Column | Notes |
|---|---|
| `id` | PK |
| `filename` | e.g. `Transcript_1_France.txt` |
| `expert_name`, `expert_role`, `market` | from the header block |
| `chunk_count` | cached count, refreshed on ingest |
| `is_active` | **soft-delete + versioning**: only `true` rows count |
| `version` | re-uploads bump this (old version auto-deactivated) |
| `ingested_at` | timestamp |
| **partial unique index** | `UNIQUE (filename) WHERE is_active` → only ONE active version per filename |

### `chunks` — the retrieval units (RAG index)
| Column | Notes |
|---|---|
| `id` | PK (bigint) |
| `transcript_id` | FK → transcripts, cascade delete |
| `speaker` | `Interviewer` or `Expert` (check constraint) |
| `speaker_index` | `IN_00`, `EX_00`, … (unique per transcript+speaker) |
| `timestamp` | e.g. `00:18` |
| `content` | **bundled `Q: <question>` + `A: <answer>`** (see #18 in DEVELOPMENT_CHALLENGES) |
| `embedding` | `VECTOR(384)` — the pgvector column used for similarity search (Themes & Q&A) |
| `question_embedding` | `VECTOR(384)` — interviewer-question-only embedding, used by the Interview Guide's question↔question retrieval |

### `chat_history` — every Q&A turn (traceability)
question, mode (`answer`), answer, citations (JSON/JSONB array), verification_status, model, latency_ms, created_at.

### `error_logs` — every caught failure (traceability)
level, component (`qa`/`themes`/`guide`), message, exception_type, endpoint, method, detail (JSON), created_at.

### `llm_usage_log` — every Groq call (traceability + token accounting)
task (`qa_answer`/`themes`/`guide_batch`), model, prompt_tokens, completion_tokens, total_tokens, latency_ms, success, created_at.

> **Note on JSON columns:** `citations`/`detail` are plain `JSON` on SQLite (so tests run without Postgres) and `JSONB` on PostgreSQL — see `JSONTypeMixin` in `src/models/audit.py`.

---

## 7. Transcript format & parsing (`src/utils/parser.py`)

A source file looks like (see `datas/Transcript_1_France.txt`):

```
Expert 1 – Dr. Jean Martin
Role: Head of Urology
Market: France

00:00
Interviewer: Thanks for joining...

00:18
Dr. Martin: Adoption is growing, but...
```

`parse_transcript_text()` turns this into an ordered list of **turns**:
- `_parse_header` reads Expert/Role/Market lines (throws a helpful `ValidationError` with "Expected 'Expert N – Name', 'Role: …', 'Market: …'" if missing).
- A line matching `TIMESTAMP_RE` (`^\d{1,2}:\d{2}$`) closes the previous turn and starts a new one.
- A line matching `^Label: content` sets the speaker and content; following indented lines are appended to that speaker's content.
- Each turn gets `speaker_index` `IN_00/EX_00…` by counting interviewer vs expert turns.
- `load_interview_guide()` extracts the numbered `N. question` lines from `Interview_Guide.txt`, ignoring lines containing "interview guide" / "project objective". The result is the 6 questions used by the guide and themes features.

**Ingestion — `src/services/ingest_service.py`**
- `_discover_files()` finds every `*.txt` in `datas/` except `Interview_Guide.txt`.
- `_build_expert_chunks()` walks the turns and — crucially — **bundles each expert answer with the preceding interviewer question** (`_bundle_expert_answer` → `"Q: …\nA: …"`). Interviewer-only turns are dropped. This is why "what are the expectations for the next 3–5 years?" can now be answered even though the phrase only existed in the interviewer's question (DEV-CHALLENGE #18).
- `_embed_chunks()` embeds each chunk twice, in batches of up to 8 (`MAX_CONCURRENT_EMBEDS`) via `asyncio.to_thread` — `embedding` over the bundled `Q: …\nA: …` text (Themes/Q&A index) and `question_embedding` over only the interviewer question (guide index) — the CPU-bound model call leaves the event loop free.
- `ingest_all()` → `repository.ingest()` (idempotent: existing filenames are not re-created, chunks are inserted only if `(transcript_id, speaker_index)` doesn't already exist; `chunk_count` is refreshed from real counts).

---

## 8. The six core flows, end to end

### Flow A — Data intake (auto-seed on startup + upload)

Primary path — **auto-seed at lifespan** (no manual ingest endpoint):
```
startup → _seed_transcripts(settings)
  → Settings.seed_on_startup default true
  → repository.count_transcripts() > 0?  → skip (idempotent)
  → else IngestService.ingest_all():
      datas/*.txt → parse → build Q/A chunks → embed (local, free)
      → repository.ingest(): ensure transcripts, insert missing chunks, recount
 → {transcripts_count, chunks_count, created_transcripts, created_chunks}
```
The seed is best-effort (`try/except` + log) so startup never blocks on embedder failures,
and it never runs twice on the same data because each file lands a row in `transcripts`.

Upload path (`POST /api/v1/transcripts/upload`): multipart `.txt` ≤ 5 MB → parse → embed → `upload_version()`:
- finds the currently active transcript with that filename,
- sets `is_active = False` on it,
- inserts a new row with `version = old_max + 1`,
- purges cached guide answers for that filename.

### Flow B — Retrieval (the "find the evidence" step)
`src/repositories/transcript_repository.py`:
- `similarity_search(query_embedding, top_k, transcript_id=None, min_cosine_distance=None)`
  - SQL: `ORDER BY embedding <-> query` (cosine distance, ascending → nearest first), `LIMIT top_k`.
  - filters to `is_active = true` transcripts; can scope to one transcript (used by Themes' per-expert retrieval) or all transcripts (Q&A); can threshold on distance.
  - Returns chunks enriched with filename/expert/market/timestamp.
- `question_search(query_embedding, top_k, transcript_id=None)`: guide-only — ranks chunks by `ORDER BY chunks.question_embedding <-> query` (question↔question match against each chunk's interviewer-question embedding), applies no distance cutoff, and filters out rows without a `question_embedding`.
- `keyword_search(query, top_k)`: `ILIKE '%term%'` for every word longer than 2 chars (AND semantics) across all active chunks — merged with vector hits to build the verbatim-quote section of every Q&A answer.

### Flow C — Interview Guide (progressive streaming)
`interview_guide_service.py` — `generate_interview_guide()` yields NDJSON events:
```
meta   → all 6 questions (so the UI can draw them instantly)
batch  → one per (expert, batch of 3 questions)  [3 experts × 2 batches = 6 LLM calls]
done   → always emitted last
```
For each batch (`_answer_expert_batch`):
1. embed the guide question and retrieve top-2 chunks **for that expert only** per question, via question↔question matching on `question_embedding` (no distance cutoff) — the fixed guide questions near-verbatim match the interviewer questions, so the correct chunk always ranks first,
2. build a context block per question,
3. skip questions with no chunks → `"Not mentioned in this transcript"`,
4. one LLM call answers all 3 questions at once (`build_interview_guide_batch_messages`), wrapped in the cache (`interview_guide_batch::{filename}::{hash}`),
5. verify each returned citation against the retrieved chunks, dropping any that don't match verbatim,
6. **per-batch try/except**: a failure logs to `error_logs`, yields friendly fallback answers ("Oops – we hit a snag…"), records an audit error, and the stream **always** ends with `done` (DEV-CHALLENGE #20).

### Flow D — Themes (Consensus / Disagreement / Emphasis)
`theme_service.py` — `generate_themes()` yields:
```
meta   → the 6 topics
topic  → one per topic (6 LLM calls), each = {topic, themes[], error:false}
done
```
Per topic: embed topic → per-expert retrieval (top-6 within each expert's transcript, no distance cutoff, merged by chunk id) → context tagged `[timestamp] [expert (market)] [file]` → one LLM call (`task="themes"`, `max_tokens=4096` to avoid truncating the themes JSON) → validate each theme object (type must be one of the three, non-dict items dropped) → verify citations (metadata now inherited from the matched chunk, never the model — see §9) → per-topic error guard → `entry.error=True` on failure so the UI shows the friendly snag message instead of hanging (DEV-CHALLENGE #20). Per-expert scoping exists because a single global top-K silently dropped one expert's passages when a topic sentence scored low globally (the purchase-timeline chunk ranked as low as 6th).
### Flow E — Q&A (synthesis + verbatim quotes)

`qa_service.py`:

- `ask(question)`: first checks `detect_off_topic()` — greetings/capability questions (**and any question with no retrieved context**) get an **LLM-generated conversational scope reply** (`_scope_answer()`, `task="qa_scope"`, guided by `src/prompt/qa.py` `build_scope_messages`, free-text via `create_completion`, cached per question). The canned `SCOPE_REPLY`/`NO_CONTEXT_FALLBACK` strings survive only as the fallback when that LLM call fails.
- `answer()` (the only mode — there is no separate "quote mode" anymore, the UI always shows both): embed question → top-k + threshold → build context → LLM (`task="qa_answer"`) → verify citations → if nothing retrieved, route to the LLM scope reply instead of a static message.
- **Verbatim quotes:** `_collect_quotes()` merges **semantic** (vector) + **keyword** hits into one dict keyed by chunk id and returns the raw chunk content as `quotes` (status `verified`) — the exact words are guaranteed to be from the transcript because they ARE the transcript, never LLM-written. Quotes are gathered for every question, so the answer panel always has a "Verbatim quotes" section alongside the cited "Sources".
- Answers are cached (`qa_answer`, keyed by task+model+question+context).
- The route (`src/routes/qa.py`) measures latency, records the chat turn on success / an error log on `LLMError`.
### Flow F — Auditing / traceability (see §9)

---

## 9. Anti-hallucination & traceability — the "trust model"

This is the heart of the project and the most interview-worthy part.

1. **Grounding:** the LLM receives *only* retrieved excerpts as context, and strict rules (`RULE-101…205` in `src/prompt/*`) forbid inventing anything. Empty context → "not found" answer.
2. **Verification (char-level check):** `citation_utils.verify_citations()` — for every returned citation, the quote must be an **exact substring** (after whitespace compaction + typographic folding of curly quotes/dashes, `normalize_for_match`) of a retrieved chunk that matches the claimed expert name. Anything else is **dropped** (and logged for diagnosis), not shown. Verified citations **inherit their `transcript_file`/`expert_name`/`market`/`timestamp` from the matched DB chunk**, so the UI can never display a model-hallucinated filename like `interview.txt` (RULE-205 makes the model copy real tag values too).
3. **Chunk bundling (#18):** expert answers carry their framing question, so scope/timeframe information that used to live only in interviewer turns is now searchable.
4. **Trigger-proofing (#20):** every item from the model is schema-validated before use; bad LLM JSON can't crash a stream.
5. **Traceability tables (chat_history / error_logs / llm_usage_log):** every user question, every failure, every token spent is persisted (inspectable directly in Postgres; the operator read endpoints were removed as unused by the UI).
   - `src/services/audit_service.py` records are **best-effort**: each opens its own short DB session and *swallows* failures (`_record`) so traceability can never break the main feature.
   - The `GroqClient` gets the recorder injected (`usage_recorder`) and calls it after every attempt — success or failure — with task/model/tokens/latency (`_record_usage(payload: dict)`).

---

## 10. The Groq client — rate limiting done right (`src/client/groq_client.py`)

This file is a small project in itself and the source of the most instructive bugs (see DEVELOPMENT_CHALLENGES #5, #6, #12).

Key mechanics:
- **Tenacity retry**: 5 attempts, exponential backoff 2→10s, now **only** on transient 5xx (500/502/503/504).
- **429 handling (no blind retries):** `_post_completion` reads `Retry-After` plus `x-ratelimit-reset-tokens|requests`. A reset **< 60s** → sleep until the reset (with a 0.5s grace), then retry once more. A reset **≥ 60s**, an unknown reset, or two 429s in a row → raise **`LLMRateLimitError`** (status 429) immediately, burning zero tenacity retries; streams log it and degrade gracefully (`entry.error=True`, canned scope fallback). The old behaviour blindly retried 429s five times *inside* the still-exhausted minute — every attempt re-filled the window, which is exactly why "the wall never cleared".
- **Provider budget gates:** besides the self-accounted window, Groq's own `x-ratelimit-remaining-requests/-tokens` + their reset values are tracked (`_requests_budget`/`_tokens_budget`); if a budget hits 0 the client sleeps until that reset before sending.
- **Min request interval**: `GROQ_MIN_REQUEST_INTERVAL = 2.0s` — the free tier allows ~30 req/min.
- **Token-aware pacing (2nd-generation limiter):** a **self-accounted rolling 60-second window** (`_token_window` deque).
  - After every successful call we append the response's **actual** `total_tokens` (`_record_token_usage`).
  - Before every call (`_post_completion`) we prune old entries and sleep until `used + estimated(2048) ≤ 8000` fits in the window.
  - That way the limiter meters **real consumption**, not headers (headers were inconsistent — their `reset` values parse-failed silently, DEV-CHALLENGE #6 — and estimates drift when prompts change shape, DEV-CHALLENGE #12).
- **JSON mode**: `parse_json_completion()` requests `response_format={"type":"json_object"}` and parses; Groq requires the literal word "json" in the prompt (DEV-CHALLENGE #11).
- **Usage reporting**: `create_completion()` records latency + tokens to the injected recorder on success AND on every failure type (LLMParseError / HTTPStatusError / HTTPError).

---

## 11. Design decisions & trade-offs (interview table)

| Decision | Why | Trade-off noted |
|---|---|---|
| RAG + pgvector (no fine-tuning) | Grounded, cheap, adjustable corpus | Retrieval quality is the ceiling — but chunk bundling + threshold tuning raise it |
| Local embedder (`all-MiniLM-L6-v2`) | Free, offline, 384-dim fits free Postgres | Semantic nuance < bigger models; keyword search compensates for verbatim quotes |
| `openai/gpt-oss-120b` on Groq free tier | Best comprehension among benchmarks, auto prompt-caching, 1K req/day (DEV-CHALL. #10) | Hard daily **tokens-per-day** cap: 200K/day |
| In-memory LRU cache (128 entries) | Backend answers survive Streamlit reruns; multi-user sharing; NO extra LLM cost | Wiped on restart (cold start ~2.5 min free tier); disk persistence deliberately deferred (#8) |
| NDJSON progressive streaming for guide/themes | User sees questions instantly, answers fill in | More moving parts (handled defensively, #20) |
| No Alembic: `create_all` + startup migrations | Simple; tables auto-appear; `ALTER TABLE ... IF NOT EXISTS` upgrades old DBs | Schema evolution is hand-written |
| Soft-delete + versioning per filename | Re-uploads keep history; partial unique index keeps single active version | Slightly more complex queries (`is_active` filters everywhere) |
| Best-effort audit recorders | Traceability never breaks the main flow | Monitoring must tolerate occasional gaps |
| Q&A bundle = `Q:…\nA:…` chunk | Fixes "data was in the transcript but unretrievable" (#18) | Requires re-ingest to take effect |

---

## 12. The Groq free-tier reality (the 429 story — know this cold)

Three limits apply to the free tier of `openai/gpt-oss-120b`:

| Limit | Value | Effect |
|---|---|---|
| Requests per minute | ~30 | solved by 2s min interval |
| **Tokens per minute (TPM)** | 8,000 | solved by the self-accounting token window (pauses until headroom) |
| **Tokens per day (TPD)** | **200,000** | NOT solvable by waiting minutes — the daily bucket |

**The TPD trap discovered live on 2026-09-20:** after a backend restart wiped the cache, a burst of re-retrieval caused "429 Too Many Requests" — even an **83-token** test request was rejected with `"Used 199981, Requested 83 … try again in 27.648s"`. A direct API call proved it was the **daily** token cap, not per-minute pacing. The daily bucket refills continuously (~139 tokens/min = 200K/86,400s) and fully resets at 00:00 UTC.

**Approximate token cost of each feature** (measured from real runs):

| Feature | LLM calls | Tokens |
|---|---|---|
| Interview guide (3 experts × 2 batches of 3) | 6 | ~11K |
| Themes (6 topics) | 6 | ~6–8K |
| One Q&A turn | 1 | ~1–2K |
| **Full cold demo** | 13+ | **~20K+** |

Free tier → about **8–10 full cold runs per day**. The cache is what makes the demo practical, and the traceability table (`llm_usage_log`) lets you *prove* the token accounting.

---

## 13. Code walkthrough (file-by-file, key functions)

### `main.py` — the entry point
- `setup_logging()` on import → structlog JSON logs to stdout.
- `lifespan` (async context manager): `db.init(settings.database_url)` → `await db.create_tables()` → on shutdown `await db.close()`. `create_tables` also runs the Postgres startup migrations.
- Middleware order (last-added = outermost): `LoggingMiddleware` (structured access logs) → `CORSMiddleware` (allow all, dev-grade) → `CorrelationIdMiddleware`. The correlation middleware sets `X-Request-Id` (from request or generated) and `X-Request-Duration-Ms` on every response.
- Exception handlers: `RequestValidationError` → 422 `INVALID_INPUT`; `ApplicationError` → its own status/error_code/message; anything else → 500 `UNEXPECTED_ERROR`. Every API error therefore has the same shape `{status, status_code, error_code, message, detail}`.

### `src/settings.py`
`Settings(BaseSettings)` reads `.env`; defaults: `top_k=5`, `similarity_threshold=0.5` (cosine **distance** — tuned because MiniLM matches on this data sit ~0.27–0.5, DEV-CHALL. #2), `llm_model=openai/gpt-oss-120b`, `GROQ_TOKEN_LIMIT=8000`, `GROQ_MIN_REQUEST_INTERVAL=2.0`, `GROQ_ESTIMATED_TOKENS_PER_REQUEST=2048`, `LLM_RETRY_MAX_ATTEMPTS=5`, timeout 60s, temperature 0.2, `cache_llm_results=True`, `seed_on_startup=True`.

### `src/repositories/database.py`
`DatabaseSessionManager`: one async engine + sessionmaker; `get_db()` yields a session per request (rollback on error). `_run_startup_migrations()` uses `ADD COLUMN IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` to upgrade pre-versioning databases — this is the "no-Alembic migration strategy".

### `src/repositories/transcript_repository.py` (all DB queries)
- `ingest()` → idempotent bulk insert (see Flow A).
- `upload_version()` → deactivate old, insert new with next version (see Flow A).
- `count_transcripts()` → drives the startup seed guard.
- `similarity_search()` / `keyword_search()` → retrieval (see Flow B).
- `list_transcripts()`, `count_*`, `pgvector_available()`, `tables_available()` (used by `/ready`).

### `src/repositories/audit_repository.py`
`add_chat_turn` / `add_error` / `add_llm_usage` (commit + rollback on failure). No read endpoints anymore — the operator list endpoints were removed as unused by the UI; query the tables directly in Postgres for debugging.

### `src/client/groq_client.py` — see §10.
### `src/client/embedder_client.py`
Lazy-loads the SentenceTransformer once (`_load`), `embed(texts)` batches at 32 with `show_progress_bar=False`.

### `src/services/` — orchestration
- `dependencies.py`: `get_services()` is `@lru_cache`d → singletons for settings, embedder, Groq client. If a Groq key exists, `groq_client.usage_recorder = audit_service.record_llm_usage` is wired here.
- `cache.py`: `LRUCache` (OrderedDict, 128), `make_cache_key(*parts)` = sha256 of sorted JSON (so question text, transcript version, retrieved context all participate), `acached_result` for async producers, `purge_by_prefix` (used on upload for `interview_guide_batch::{filename}::`).
- `citation_utils.py`: `normalize_whitespace`, `normalize_for_match` (adds typographic folding for comparison), `is_quote_in_content` (substring check), `verify_citations` → (verified, dropped) where **verified metadata comes from the matched chunk**, `build_citation_context` → `[timestamp] [expert (market)] [file]\n<content>` blocks, `chunk_to_dict`.
- `qa_service.py` / `theme_service.py` / `interview_guide_service.py` — Flows E / D / C above.
- `ingest_service.py` — Flow A.
- `audit_service.py` — recorders.

### `src/routes/` — thin HTTP wrappers
- `analysis.py`: `GET /api/v1/analysis/interview-guide/stream` and `/themes/stream` (streaming NDJSON, `Cache-Control: no-cache`). The non-stream batch variants were removed in the API simplification — the UI only ever used the streams.
- `qa.py`: `POST /api/v1/qa/ask` + latency + audit.
- `ingest.py`: upload + list transcript endpoints (seed replaced the bulk-ingest POST — see Flow A).
- `system.py`: `/`, `/health`, `/ready` (checks pgvector extension + tables + counts; 503 when not ready).
- `api.py`: bundles routers under `/api/v1`.

### `src/prompt/` — the "contracts" the LLM must obey
Each module has a `system` template with **ROLE / MISSION / CONTEXT / RULES / OUTPUT CONTRACT / ERROR HANDLING** and a `build_*_messages()` function. Notable contracts:
- `qa.py`: answer + citations; must say "could not find it" when context is empty (RULE-302/303).
- `themes.py`: labels each finding Consensus/Disagreement/Emphasis; numeric ranges when numbers conflict.
- `interview_guide.py`: single + **batch** variants; "Not mentioned in this transcript." fallback (RULE-102).

### `src/middleware/middleware.py`
`CorrelationIdMiddleware` and `LoggingMiddleware` (see main.py).

### `src/utils/`
- `parser.py` — §7.
- `logger.py` — structlog JSON pipeline (merged context, timestamps, exc info).
- `exceptions/` — a small hierarchy (`ApplicationError` base; `ValidationError` 422, `TranscriptNotFoundError` 404, `LLMError` 502, `LLMParseError`, `EmbeddingError`, `IngestionError`, `RepositoryError`, `VectorSearchError`, `DatabaseWriteError`) with stable `error_code`s.

### `frontend/app.py` — the whole UI (~440 lines)
- `api_client()` = `httpx.Client(base_url, timeout=600s)` — the read timeout was raised from 120s because rate-limited cold runs legitimately take ~2.5 min (DEV-CHALL. #7).
- `fetch_or_error`/`_render_tab`: session-state machine per tab — `done`/`error` are written on **every** outcome so Streamlit's full-script reruns never silently restart a stream (DEV-CHALL. #19); errors show an explicit Retry button.
- `stream_guide()`/`stream_themes()`: `client.stream(...)` reads NDJSON lines, renders `meta` as expanders with empty placeholders, then fills them per `batch`/`topic` event; `done` ends it.
- Chat tab: pinned input via `pending_question` + `st.rerun()`; messages persisted in `session_state`; rendered in a fixed-height (420px) scroll container; error-type messages render with `st.error`; every answer renders the LLM text + "Sources" expander + a "Verbatim quotes" section with ✅ verified / ⚠️ status icons.
- `render_citations()` and the theme emoji map give every answer its "Sources" expander.

---

## 14. How to run, test, verify

```bash
# one-time
copy .env.sample .env      # set GROQ_API_KEY, DATABASE_URL (a local/remote Postgres)
make setup                 # uv sync --dev

# run
make run                   # uvicorn main:app --reload on :8000   (logs = structlog JSON)
make run-ui                # streamlit frontend/app.py on :8501

# seed data — automatic (default SEED_ON_STARTUP=true)
# On first `make run`, the lifespan auto-ingests datas/*.txt (idempotent:
# skips whenever the DB already has transcripts, so restarts are safe).

# quality
make test                  # pytest tests/ -v        (~125 tests)
make test-cov              # coverage + diff-cover
make lint && make format   # ruff
make check                 # lint + format check

# live checks
GET /health                → {"status":"ok"}
GET /ready                 → dependency + count report (503 until pgvector + tables okay)
GET /docs                  → interactive OpenAPI
GET /api/v1/transcripts    → seeded corpus listing
```

---

## 15. Interview prep — questions they will actually ask

**1. "Walk me through your architecture."**
Layered: FastAPI API → services (business logic, prompts, caching, verification) → repositories (async SQLAlchemy + pgvector) → Postgres; plus a local embedder, the Groq LLM, and an in-memory cache; Streamlit on top calling the API over HTTP/NDJSON. Emphasise data flow: parse → bundle Q/A → embed → store vectors → retrieve by cosine distance → LLM answers from context only → every citation char-verified.

**2. "Why these models?"**
- Embeddings local `all-MiniLM-L6-v2` (free, private, 384-d).
- LLM `openai/gpt-oss-120b` on Groq free tier — chose after benchmarking the app's *real* prompts for valid JSON; it has automatic prompt caching and 1K req/day (dev-log #10). Model lifecycles on free tiers change (we survived a 404 when a model was deprecated, #3) — keep it in config.

**3. "How do you handle citations/timestamps?"**
Every chunk carries its timestamp, expert, transcript file, market. Context blocks embed `[timestamp] [expert (market)] [transcript_file]`; the LLM is contractually forced to return citations; then `verify_citations()` does a **substring proof** against the retrieved text (after typographic folding) and stamps each surviving citation with the **real chunk metadata**, dropping any unverifiable citation before the UI sees it.

**4. "How do you reduce hallucinations?"**
Defense in depth: retrieval-first (LLM never sees the whole corpus, only excerpts), strict prompt rules + JSON output contract, empty-context = honest "not found", citation verification with exact-substring proof, expert-attribution checks (can't misattribute to another expert), schema/type validation on every model item (#20), and the Q/A bundle prime (#18).

**5. "How would you scale from 3 transcripts to 30+?"**
- Retrieval is already per-query and indexed; ingest would be the main cost (embedding is local & parallelised).
- Keep per-expert scoping for the guide (results degrade gracefully).
- Swap the in-memory cache for Redis / disk, or accept recompute.
- The startup-migration pattern grows to real Alembic migrations when schema changes get complex.
- On paid Groq the 8K TPM window becomes 10–50× bigger, so the ~2.5-min cold run pacing cost disappears (documented in #8 / #13).
- Add hybrid retrieval (BM25 + vectors) and chunk re-ranking as corpus grows.

**Bonus one-liners**
- *Why JSON mode?* "Stable contract + Groq requires the word 'json' in the prompt." (#11)
- *Why stream NDJSON?* "Progressive UX; and I made it fail-per-item so `done` always arrives." (#20)
- *What's the traceability?* "Every turn, error and token spent is stored; best-effort so it can't break the app."

---

## 16. Glossary / cheat sheet (cram this)

- **Chunk** — one retrievable unit = expert answer bundled with its framing question.
- **Embedding** — a 384-number vector representing meaning; nearby vectors = related text.
- **pgvector cosine distance** — smaller = more similar; we keep results ≤ 0.5.
- **Top-k** — how many nearest chunks we retrieve (5 default).
- **RAG (retrieval-augmented generation)** — retrieve evidence first, then generate an answer from it.
- **Context block** — the serialised retrieved chunks (`[timestamp] [expert (market)] …`) handed to the LLM.
- **NDJSON** — one JSON object per line; used for streaming.
- **TPM / TPD** — tokens per minute (8K window, limiter-aware) / tokens per day (200K hard cap on free gpt-oss).
- **Citation verification** — substring proof that a quote really exists in a retrieved chunk.
- **Soft delete + version** — `is_active=false` hides an old upload; uploads bump `version`.
- **Startup migrations** — `ALTER TABLE ... IF NOT EXISTS` run at boot (this project has no Alembic).
- **Traceability tables** — `chat_history`, `error_logs`, `llm_usage_log`.

---

*Pair this guide with `DEVELOPMENT_CHALLENGES.md` (20 real bugs + fixes) and `design/requirements.md` (functional requirements FR-001…008) — together they are the full interview script for this project.*