# Hasamex Transcript Analysis — Access Guide

This document explains how to set up, run, and use the Hasamex Expert-Call
Transcript Analysis system. It analyses the three expert-call transcripts
(European Robotic Surgery Market) from the Hasamex technical case study.

---

## 1. What the system delivers

A single-page web app with three tabs:

| Tab | What it shows |
|-----|---------------|
| **Interview Guide** | The six interview-guide questions, answered for each of the three experts, grounded in that expert's transcript only, with timestamped citations |
| **Themes & Disagreements** | Per interview-guide topic: consensus points, disagreements, and differences in emphasis across the three experts, with citations |
| **Ask a Question** | Free-form cross-transcript Q&A — an LLM synthesis answer with verified citations **plus** verbatim transcript quotes (raw text, no LLM rewriting) |

Every answer is grounded in retrieved transcript chunks and every citation is
verified character-by-character against the source text (hallucination prevention).

---

## 2. Prerequisites

- **Windows** with **PostgreSQL 18** running on `localhost:5432`
- **pgvector** extension installed (verified automatically via `/ready`)
- **Python 3.12+** and **uv** (<https://docs.astral.sh/uv/>)
- A **Groq API key** from <https://console.groq.com/keys> (free tier)

---

## 3. One-time setup

**Step 1 — create the database (once):**

```bash
psql -U postgres -c "CREATE DATABASE hasamex;"
```

**Step 2 — install dependencies:**

```bash
make setup
```

**Step 3 — configure secrets:**

```bash
copy .env.sample .env
```

Edit `.env` and set your Groq key (and adjust `DATABASE_URL` if your Postgres
username/password differ from `postgres`/`Admin123`):

```ini
GROQ_API_KEY=your_key_here
```

`.env` is git-ignored and never committed — use the template, never the real file.

---

## 4. Run

Open two terminals:

```bash
make run        # backend  → http://localhost:8000  (interactive API docs at /docs)
make run-ui     # frontend → http://localhost:8501
```

On first startup the backend automatically ingests `datas/*.txt` and embeds the
chunks — no manual ingest step. The app is ready to use immediately.

**Access points:**

| What | URL |
|------|-----|
| Web UI | <http://localhost:8501> |
| Backend health/readiness | <http://localhost:8000/ready> |
| Interactive API docs | <http://localhost:8000/docs> |

---

## 5. Using the system

1. Open <http://localhost:8501> in a browser.
2. **Interview Guide tab** — pick an expert; read the cited answers to all six
   questions. Sources link each claim to a timestamped transcript excerpt.
3. **Themes & Disagreements tab** — explore consensus / disagreement / emphasis
   for each interview-guide topic across all three experts.
4. **Ask a Question tab** — type e.g. *"What slows down adoption in Germany?"*.
   You get an LLM-written answer with citations plus a verbatim-quotes section
   you can check word-for-word against the transcripts.

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/ready` returns 503 | PostgreSQL not running, `hasamex` DB missing, or pgvector not installed (`CREATE EXTENSION IF NOT EXISTS vector`) |
| `ModuleNotFoundError` | Run `make setup` first |
| Groq 429 errors / slow responses | Free-tier rate limits; the app paces requests automatically — wait a minute or add your own key quota |
| Port already in use | Stop the other process, or change the port in the `make run`/`make run-ui` commands |

---

## 7. Notes

- Adding more `.txt` transcripts to `datas/` grows the analysis automatically
  (retrieval is capped; the app is scale-ready for 30+ transcripts).
- LLM results are cached in memory, so repeat views cost zero Groq tokens.
- Every Q&A turn, error, and Groq call is logged to the database
  (`chat_history`, `error_logs`, `llm_usage_log`).