# Project Progress & Context

## Current Status (As of March 14, 2026)

Full-stack SaaS application: React frontend, five FastAPI backend services, Redis async queue, PostgreSQL + pgvector, Slack alerting, **multi-tenant isolation**, and **RAG-powered AI analysis** using sentence-transformers + pgvector KNN retrieval.

**Live data only — no seed/test data. All services running via Docker Compose. 160 tests passing.**

---

## Architecture — Built vs Planned

```
Customer Pipelines (Airflow / Spark / Databricks)
          │
          ▼
Log Collection Layer          ✅ BUILT
(agent.py + webhook_collector.py + simulator.py)
          │
          ▼
Log Ingestion API             ✅ BUILT
(FastAPI :8000 — normalises, writes PipelineRun scoped to workspace_id, publishes to Redis)
          │
          ▼
Message Queue                 ✅ BUILT
(Redis Streams — log_events stream, consumer group, workspace_id in every message)
          │
          ▼
Log Storage                   ⚠️  PARTIAL
(PostgreSQL for metadata ✅ / raw log files = NOT stored)
          │
          ▼
Log Processing Layer          ✅ BUILT  [Feature #2]
(advanced_parser.py — ExceptionBlock, SparkJavaParser, AirflowPythonParser,
 Caused-by chain walking, JVM frame filtering, 16-entry exception catalogue)
          │
          ▼
Runbook RAG Ingestion         ✅ BUILT  [Feature #3]
(runbook_ingester.py → header-aware chunking → embed → runbook_chunks table)
          │
          ▼
RAG / Vector DB               ✅ BUILT
(pgvector HNSW index on errors.embedding + runbook_chunks.embedding /
 sentence-transformers all-MiniLM-L6-v2 / dual-source KNN retrieval)
          │
          ▼
AI Debugging Engine           ✅ BUILT
(FastAPI :8002 → Claude claude-haiku-4-5 — dual-source RAG: past incidents + runbook sections)
          │
          ▼
Root Cause Engine             ⚠️  STUB
(rank_hypotheses() sorts by score — not wired to AI output)
          │
          ▼
API Layer                     ✅ BUILT
(FastAPI :8001 — /dashboard, /pipelines/{n}/errors, /pipelines/{n}/runs — all auth-gated + workspace-scoped)
          │
     ┌────┴──────┐
     ▼            ▼
Web Dashboard    Slack Alerts
✅ BUILT         ✅ BUILT
(React/Vite      (alerter.py —
 dark mode,       Slack webhook,
 modal,           fires after
 run history)     AI analysis)
```

---

## Service Map

| Service | Port | Status | Tech |
|---|---|---|---|
| Frontend | 5173 | ✅ Running (Docker) | React + Vite |
| API Layer | 8001 | ✅ Running (Docker) | FastAPI + PostgreSQL + pgvector |
| Log Ingestion API | 8000 | ✅ Running (Docker) | FastAPI + Redis |
| AI Debugging Engine | 8002 | ✅ Running (Docker) | FastAPI + Claude + sentence-transformers |
| Queue Worker | — | ✅ Running (Docker) | Python + Redis Streams + pgvector |
| Webhook Collector | 8003 | ✅ Running (Docker) | FastAPI |
| Log Agent | — | ✅ Built, runs natively | watchdog |
| PostgreSQL | 5434 | ✅ Running (Docker) | pgvector/pgvector:pg16 |
| Redis | 6380 | ✅ Running (Docker) | Redis 7 |

---

## How to Run

```bash
# ── First-time setup (pgvector image requires fresh volume) ────────
docker compose down -v          # wipes old postgres volume
docker compose build            # rebuild all images (sentence-transformers ~500MB)
docker compose up -d

# ── Send a test error event ────────────────────────────────────────
curl -X POST http://localhost:8003/webhook/generic \
  -H 'Content-Type: application/json' \
  -d '{"pipeline":"my-pipeline","level":"ERROR","message":"OOM error in stage 5"}'

# ── Log Collection (run natively, optional) ────────────────────────
python services/log-collection-layer/agent.py \
  --watch-dir /tmp/pipeline-logs --job-id spark-etl-prod

# ── Tests ──────────────────────────────────────────────────────────
python3 -m pytest tests/ -v
```

---

## Completed Work

- [x] React dashboard — live auto-refresh, "Connect Pipeline" form, dark/light mode, pipeline detail modal, home page, landing page, login, payment flow
- [x] **Multi-tenant isolation** — `workspace_id` column added to `pipelines`, `pipeline_runs`, `errors`; all dashboard API endpoints require `x-session-token` and filter by `str(user.id)`; workspace indexes added; composite unique constraints scoped per tenant
- [x] **RAG with pgvector** — `errors.embedding vector(384)` column; HNSW index for cosine KNN; `ai-engine /embed` endpoint generates embeddings via `sentence-transformers all-MiniLM-L6-v2`; `ai-engine /retrieve` endpoint does workspace-scoped KNN retrieval; worker orchestrates embed → retrieve → analyze pipeline; Claude receives retrieved similar incidents in a structured RAG prompt; falls back to standard prompt when no similar incidents above 0.75 cosine threshold
- [x] PostgreSQL image upgraded to `pgvector/pgvector:pg16`
- [x] **Redis stream carries `workspace_id`** — ingestion API now includes workspace in every Redis message; worker reads it and scopes all DB writes
- [x] Frontend sends `x-session-token` on all `/dashboard` and `/pipelines/*` requests
- [x] AI engine `/analyze` accepts `similar_incidents` and uses `rag_pipeline.build_debug_prompt()` for enriched prompts
- [x] `rag_pipeline.py` fully implemented — structured RAG prompt with JSON output instruction
- [x] `embedder.py` — local sentence-transformers model, cached, ~10ms per embedding
- [x] PostgreSQL migration (port 5433, shared across api-layer + ingestion-api)
- [x] **Redis Queue** — ingestion returns 202 immediately; worker processes async
- [x] **Pipeline Run History** — `PipelineRun` table, `GET /pipelines/{name}/runs` (newest-first)
- [x] **Slack Alerting** — Block Kit messages after AI analysis; silent no-op if no webhook URL set
- [x] **Log Collection Layer** — three ingestion paths: agent.py, webhook_collector.py, simulator.py
- [x] **Log Processing Layer wired into worker** — `extract_error()` → structured severity + summary → pipeline_context for Claude
- [x] **Feature #2 — Advanced Deterministic Log Parsing** — `advanced_parser.py` replaces naive `split(":")` with full exception block assembly; handles Java stack traces (Caused-by chain walking, JVM frame filtering), Python tracebacks (user frame extraction), PySpark `PythonException` wrappers, Airflow task context; `ExceptionBlock.signature()` produces stable deduplication keys like `"EXECUTOR_FAILURE:PythonException"`; `to_debug_context()` emits signal-dense 1000-char context string for LLM; 16-entry exception catalogue maps classes to categories (OOM, DATA_TYPE, EXECUTOR_FAILURE, etc.) and severities (CRITICAL/ERROR/WARNING)
- [x] **Feature #3 — RAG for Internal Runbooks** — `runbook_ingester.py` chunks Markdown runbooks on `##`/`###` headers with paragraph overflow splitting and 50-char overlap; `RunbookChunk` model in `shared/models.py`; `POST /runbooks/ingest` in api-layer embeds each chunk via ai-engine and upserts to `runbook_chunks` table; `ai-engine /retrieve` does dual-source KNN: past error incidents + runbook chunks; worker passes both to Claude; `rag_pipeline.build_debug_prompt()` surfaces both sources with runbook citation instruction; runbook sections take priority over generic incident history
- [x] **Real Airflow integration** — `debugger_etl_pipeline` DAG triggers `on_failure_callback` → webhook → AI analysis
- [x] **PySpark integration** — customer_etl.py with ZeroDivisionError; log agent + webhook dual ingestion
- [x] **160 passing tests**

---

## Architecture Gaps (What's Missing vs Plan)

| Architecture Layer | Status | Gap |
|---|---|---|
| Customer Platforms | — | Out of scope (customer-side) |
| Log Collection Layer | ✅ Built | — |
| Log Ingestion API | ✅ Built | — |
| Message Queue | ✅ Built | — |
| **Log Storage (raw logs)** | ❌ Missing | Raw log text not stored; only metadata in PostgreSQL |
| Log Processing Layer | ✅ Built | Feature #2: advanced_parser.py with full exception block assembly |
| Runbook RAG Ingestion | ✅ Built | Feature #3: runbook_ingester.py → runbook_chunks → pgvector |
| **RAG / Vector DB** | ✅ Built | Dual-source: past incidents + runbook sections; HNSW cosine KNN |
| **Multi-Tenant Isolation** | ✅ Built | workspace_id on all tables; auth-gated API endpoints |
| AI Debugging Engine | ✅ Built | Dual-source RAG prompt: incidents + runbook citations |
| **Root Cause Engine** | ⚠️ Stub | `rank_hypotheses()` never called; AI result goes straight to DB |
| API Layer | ✅ Built | — |
| Web Dashboard | ✅ Built | Run history tab not shown in modal yet |
| Slack Alerts | ✅ Built | — |

---

## Next Steps (Priority Order)

1. **Feature #1 — Data Privacy & Log Obfuscation** — PII scrubbing (emails, IPs, credit card patterns) and secret redaction before logs are stored or sent to Claude
2. **Feature #4 — API Key lifecycle + PostgreSQL RLS** — per-workspace API keys for webhook endpoints; PostgreSQL Row-Level Security policies to enforce tenant isolation at DB level
3. **Run History UI** — `GET /pipelines/{name}/runs` endpoint exists and is tested; needs to be surfaced in the pipeline detail modal
4. **Root Cause Engine integration** — call `rank_hypotheses()` to score + rank AI hypotheses before saving to DB
5. **Log Storage (raw)** — store raw log text in a `raw_logs` TEXT column on the Error record
6. **Rate limiting** — `slowapi` on the API layer to prevent abuse
7. **Teams / Email / PagerDuty alerts** — expand beyond Slack

---

## Feature Implementation Log

### Feature #2 — Advanced Deterministic Log Parsing (March 14, 2026)

**Files changed:**
- `services/log-processing-layer/advanced_parser.py` *(new)* — core parsing engine
- `services/log-processing-layer/parser.py` *(rewritten)* — now delegates to `advanced_parser`

**What it does:**

The previous parser used `message.split(":")[0]` to extract error type — useless for multi-line Java stack traces that arrive from Spark. The new parser assembles multi-line log blocks and extracts structured `ExceptionBlock` objects.

Key components:
- `LogBlockAssembler` — groups continuous log lines into discrete error blocks (handles stack trace continuation lines starting with `\t at`)
- `SparkJavaParser` — walks the full Caused-by chain in Java traces, extracts the root-cause exception class, filters JVM/framework internal frames (org.apache.spark, py4j, scala, akka, sun.reflect) to surface only user code frames, handles `PythonException` wrappers from PySpark
- `AirflowPythonParser` — extracts Python tracebacks, identifies the user's code frame (not Airflow internals), captures task context from Airflow log prefixes
- `ExceptionBlock` dataclass — fields: `exception_class`, `root_cause_class`, `causal_chain` (list), `user_frames` (list), `task_context` (dict), `severity`, `category`, `source_format`
- `_EXCEPTION_CATALOGUE` — 16 regex patterns → `(category, severity)` mappings:
  - OOM: `OutOfMemoryError`, `GCOverheadLimitExceeded`
  - DATA_TYPE: `AnalysisException`, `SparkUpgradeException`
  - EXECUTOR_FAILURE: `PythonException`, `SparkException`
  - CONNECTIVITY: `ConnectionError`, `TimeoutError`
  - etc.
- `signature()` → `"CATEGORY:ExceptionClass"` — stable deduplication key for pgvector upsert
- `to_debug_context(max_chars=1000)` → compact string for LLM: exception class, causal chain, first 3 user frames, task context, severity
- `parse_single_message(message)` — entry point used by worker; handles single-line messages gracefully

**Why it matters:** Claude's analysis quality depends on signal-dense context. Previously the worker was sending raw multi-line log dumps. Now it sends: `"Severity: CRITICAL\nError summary: [EXECUTOR_FAILURE:PythonException] causal_chain=[ZeroDivisionError] user_frames=[customer_etl.py:42 in transform]"` — which is exactly what the LLM needs.

---

### Feature #3 — RAG for Internal Runbooks (March 14, 2026)

**Files changed:**
- `services/log-processing-layer/runbook_ingester.py` *(new)* — Markdown chunker
- `services/shared/models.py` — added `RunbookChunk` model
- `services/api-layer/main.py` — added `runbook_chunks` DDL + 3 runbook endpoints
- `services/api-layer/Dockerfile` — added `requests`, `pgvector`, `log-processing-layer` copy
- `services/ai-debugging-engine/main.py` — `/retrieve` now queries both `errors` and `runbook_chunks`; `/analyze` passes runbook sections to prompt
- `services/ai-debugging-engine/rag_pipeline.py` *(rewritten)* — dual-source prompt builder with runbook citation
- `services/queue-worker/worker.py` — `retrieve_similar()` returns `(incidents, runbooks)` tuple; both passed to `analyze_with_ai()`

**What it does:**

Runbooks are internal Markdown documents describing how to handle known failure classes (e.g., "Handling GC Overhead Errors", "Schema Migration Rollback Procedure"). Feature #3 makes these retrievable at analysis time so Claude cites the team's own documented fix rather than a generic answer.

Ingestion pipeline:
1. `POST /runbooks/ingest` receives `{markdown_text, source_file}` from the dashboard
2. `runbook_ingester.ingest_runbook_text()` splits on `##`/`###` headers → sections
3. Sections longer than 600 chars are split on paragraph boundaries with 50-char overlap
4. Each chunk is embedded via `ai-engine /embed` (sentence-transformers, 384-dim)
5. Old chunks for the same `source_file` are deleted first (idempotent re-ingestion)
6. Chunks inserted into `runbook_chunks` table with HNSW index

Retrieval pipeline (at analysis time):
1. Worker embeds the error message via `ai-engine /embed`
2. `ai-engine /retrieve` runs two KNN queries: `errors` table (past incidents) + `runbook_chunks` table
3. Both result sets are filtered to cosine similarity ≥ 0.75
4. Worker passes both lists to `analyze_with_ai()`
5. `build_debug_prompt()` builds a structured prompt with separate sections for incidents and runbook chunks
6. Runbooks get priority instruction: *"Prioritise the runbook sections above all other context — they represent this team's documented resolution procedures. Cite the runbook section title when the fix comes from it."*

**Database schema:**
```sql
CREATE TABLE runbook_chunks (
    id           SERIAL PRIMARY KEY,
    workspace_id VARCHAR NOT NULL,
    source_file  VARCHAR NOT NULL,
    chunk_index  INT NOT NULL,
    section_title VARCHAR,
    chunk_text   TEXT NOT NULL,
    created_at   VARCHAR,
    embedding    vector(384)
);
CREATE INDEX ON runbook_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```
