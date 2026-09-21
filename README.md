# Hasamex Expert-Call Transcript Analysis

Analyse three expert-call transcripts (European Robotic Surgery Market) from the Hasamex technical case study: answer the interview guide per expert with citations, extract verified exact quotes, identify themes and disagreements, and run free-form cross-transcript Q&A — all grounded in source text with hallucination prevention.

## Architecture

```
Browser
   │
   ▼
Streamlit frontend (frontend/app.py) ── HTTP /api/v1 ──► FastAPI backend (main.py)
                                                          │
                                       Routes → Services → Repositories
                                                          │
                                       ┌──────────────────┴───────────────────┐
                                       │                                      │
                              PostgreSQL (pgvector)              Groq API (openai/gpt-oss-120b)
                              transcripts + chunks(vector 384)   (cloud, free tier)
                                       │
                              sentence-transformers (all-MiniLM-L6-v2, local)
```

Layers (per project standards): Routes → Services → Repositories → Data Store. Clients wrap Groq (`src/client/groq_client.py`) and local embeddings (`src/client/embedder_client.py`).

## Tech stack

| Component | Choice |
|-----------|--------|
| Backend | FastAPI + uvicorn (Python 3.12) |
| Frontend | Streamlit |
| LLM | Groq API — `openai/gpt-oss-120b` |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local) |
| Store | PostgreSQL 18 + pgvector (`vector(384)`, cosine) |
| DI / ORM | SQLAlchemy 2.x async + asyncpg |
| Config | Pydantic Settings + `.env` |
| Logging | structlog (JSON) |
| Retry | tenacity (5xx only, 5 attempts, 2s→10s); 429 handled via Groq reset headers / `Retry-After` — sleep-and-retry when <60s, `LLMRateLimitError` otherwise |

## Prerequisites

- Windows with **PostgreSQL 18** running on `localhost:5432`
- **pgvector extension** installed (verified via `/ready`)
- A **Groq API key** from <https://console.groq.com/keys>
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)

Create a database (once):

```
psql -U postgres -c "CREATE DATABASE hasamex;"
```

The `vector` extension is created automatically on first `make run` via `CREATE EXTENSION IF NOT EXISTS vector`; if it fails, install pgvector binaries manually.

## Setup

```bash
make setup          # installs deps via uv sync --dev
```

Then configure secrets:

```bash
copy .env.sample .env   # then edit GROQ_API_KEY / DATABASE_URL
```

`.env` is git-ignored and never committed.

## Run

```bash
make run            # backend  → http://localhost:8000  (OpenAPI at /docs)
make run-ui         # frontend → http://localhost:8501
```

`make run` starts the API; on startup (lifespan) it auto-ingests
`datas/*.txt` whenever the database holds no active transcripts
(`SEED_ON_STARTUP=true`, default) — so the app is ready to use right away,
no manual ingest endpoint needed.

In another terminal, start the Streamlit UI.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | App metadata |
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (DB + pgvector + tables + counts) |
| POST | `/api/v1/transcripts/upload` | Upload one or more `.txt` transcripts (multipart, per-file result, versioned) |
| GET | `/api/v1/transcripts` | List active transcripts |
| GET | `/api/v1/analysis/interview-guide/stream` | 6 questions × per-expert answers as streaming NDJSON (`meta` → batches → `done`) |
| GET | `/api/v1/analysis/themes/stream` | Consensus / Disagreement / Emphasis themes as streaming NDJSON (`meta` → topics → `done`) |
| POST | `/api/v1/qa/ask` | Q&A: LLM synthesis with verified citations **plus** verbatim transcript quotes |

`POST /api/v1/qa/ask` body:

```json
{"question": "What slows down adoption in Germany?", "top_k": 5}
```

Every response contains the LLM answer, its char-verified citations, **and**
verbatim transcript excerpts (semantic + keyword retrieval, no LLM) so claims
can be checked word-for-word. No `mode` selection needed.

## Data

- `datas/Interview_Guide.txt` — the six interview-guide questions
- `datas/Transcript_1_France.txt`, `Transcript_2_Germany.txt`, `Transcript_3_UK.txt` — source transcripts

## Design docs

- `design/SOLDEF-TRANSCRIPT-ANALYSIS.md` — solution definition
- `design/er_diagram.mmd` — ER diagram (`transcripts` + `chunks`)
- `api/openapi.yaml` — internal API contract
- `api/external-api.yaml` — Groq API contract

## Development

```bash
make lint           # ruff check
make format         # ruff format
make check          # lint + format check
make test           # pytest
make test-cov       # pytest + coverage (target >80%)
```

## Key behaviours

- **Hallucination prevention** — every LLM task has a typed JSON output contract
  validated before returning; LLM answers are grounded only in retrieved chunks;
  all returned quotes are verified programmatically as substrings of source text.
  Questions that can't be answered from the transcripts get a warm, varied,
  LLM-generated reply (driven by a dedicated scope system prompt) that points at
  what the interviews cover; greetings/off-topic chit-chat get the same
  conversational scope handling instead of a robotic canned line.
- **Idempotent ingestion** — the startup auto-seed never duplicates rows.
- **Versioned uploads** — `POST /transcripts/upload` replaces any file with the same
  name: the previous version is soft-deleted (`is_active=false`), a new row is stored
  with an incremented `version`, only active versions are retrieved, and the interview
  guide cache for that file is purged.
- **Caching** — deterministic LLM outputs are cached in memory (repeat requests
  cost zero Groq tokens).
- **Traceability** — every Q&A turn, error, and Groq call is recorded
  (`chat_history`, `error_logs`, `llm_usage_log` tables) via best-effort writes
  that never break the primary request; inspect the tables directly in Postgres.
- **Scale story** — retrieval is capped (`LIMIT :top_k`). Code reads every `.txt`
  in `datas/`, so moving from 3 to 30 transcripts is just adding files; vector
  indexes (HNSW/IVFFlat) and background ingestion workers are intentionally out
  of scope for this demo.