# Project Progress & Context

## Current Status (As of March 8, 2026)

Full-stack application: React frontend, four FastAPI backend services, Redis async queue, PostgreSQL, Slack alerting, and a **live Log Collection Layer** that watches real log files and accepts webhook pushes from Airflow/Spark/Databricks.

**160 tests passing.**

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
(FastAPI :8000 — normalises, writes PipelineRun, publishes to Redis)
          │
          ▼
Message Queue                 ✅ BUILT
(Redis Streams — log_events stream, consumer group)
          │
          ▼
Log Storage                   ⚠️  PARTIAL
(PostgreSQL for metadata ✅ / raw log files = NOT stored)
          │
          ▼
Log Processing Layer          ⚠️  PARTIAL
(parser.py exists ✅ / NOT wired into the live worker pipeline)
          │
          ▼
AI Debugging Engine           ✅ BUILT
(FastAPI :8002 → Ollama llama3.1:8b — RAG prompt stub only)
          │
          ▼
Root Cause Engine             ⚠️  STUB
(rank_hypotheses() sorts by score — not wired to AI output)
          │
          ▼
API Layer                     ✅ BUILT
(FastAPI :8001 — /dashboard, /pipelines/{n}/errors, /pipelines/{n}/runs)
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
| Frontend | 5173 | ✅ Running | React + Vite |
| API Layer | 8001 | ✅ Running | FastAPI + PostgreSQL |
| Log Ingestion API | 8000 | ✅ Running | FastAPI + Redis |
| AI Debugging Engine | 8002 | ✅ Running | FastAPI + Ollama |
| Queue Worker | — | ✅ Running | Python + Redis Streams |
| Webhook Collector | 8003 | ✅ Built, not started | FastAPI |
| Log Agent | — | ✅ Built, not started | watchdog |
| PostgreSQL | 5433 | ✅ Running | Homebrew pg16 |
| Redis | 6379 | ✅ Running | Homebrew |
| Ollama | 11434 | ✅ Running | llama3.1:8b |

---

## How to Run

```bash
# Infrastructure
brew services start postgresql@16
brew services start redis
ollama serve &

# Backend services (separate terminals)
/bin/zsh frontend/web-dashboard/src/components/start_api_layer.sh     # :8001
/bin/zsh frontend/web-dashboard/src/components/start_ingestion.sh     # :8000
/bin/zsh frontend/web-dashboard/src/components/start_ai_engine.sh     # :8002
/bin/zsh frontend/web-dashboard/src/components/start_worker.sh        # queue worker

# Frontend
cd frontend/web-dashboard && npm run dev                               # :5173

# Log Collection (optional — picks up real log files)
python services/log-collection-layer/agent.py \
  --watch-dir /tmp/pipeline-logs --job-id spark-etl-prod

# Generate test logs (drives the agent)
python services/log-collection-layer/simulator.py \
  --type spark --job-id spark-etl-prod --errors 2

# Webhook push (Airflow-style)
curl -X POST http://localhost:8003/webhook/airflow \
  -H 'Content-Type: application/json' \
  -d '{"dag_id":"my-dag","run_id":"run-001","exception":"OOM error"}'

# Run all tests
python3 -m pytest tests/ -v
```

---

## Completed Work

- [x] React dashboard — live auto-refresh, "Add Pipeline" form, dark mode toggle, pipeline detail modal
- [x] PostgreSQL migration (port 5433, shared across api-layer + ingestion-api)
- [x] AI Debugging Engine — Llama 3.1:8b via Ollama, structured JSON output
- [x] **Redis Queue** — ingestion returns 202 immediately; worker processes async
  - Redis Streams (`log_events`), consumer group `debugger_workers`
  - Error deduplication — upsert by `(pipeline_name, error_type)`
- [x] **Pipeline Run History** — `PipelineRun` table, `GET /pipelines/{name}/runs` (newest-first)
- [x] **Slack Alerting** — Block Kit messages after AI analysis; silent no-op if no webhook URL set
- [x] **Log Collection Layer** — three ingestion paths:
  - `agent.py` — watchdog file-watcher; tails `.log`/`.txt` files; only forwards ERROR lines; position-aware (no re-reads)
  - `webhook_collector.py` — FastAPI :8003; `/webhook/airflow` + `/webhook/generic`
  - `simulator.py` — generates realistic Spark/Airflow/dbt logs for local dev/demo
  - `log_parser.py` — parses Airflow `[ts] {module} LEVEL - msg` and Spark `ts LEVEL msg` formats; normalises timestamps to ISO-8601 UTC
- [x] Fixed all deprecation warnings (`declarative_base`, `on_event`)
- [x] Docker Compose file — all 8 services, healthchecks, named volumes (needs Docker Desktop to run)
- [x] **160 passing tests**
  - `test_log_collection.py` — 46 tests (parser, agent, file tailer, webhook endpoints)
  - `test_alerter.py` — 16 tests
  - `test_pipeline_runs_api.py` — 10 tests
  - `test_ingestion_api.py` — 19 tests
  - `test_api_layer.py` — 17 tests
  - `test_worker.py` — 17 tests
  - `test_ai_engine.py` — 10 tests
  - `test_parser.py` — 10 tests
  - `test_root_cause_engine.py` — 7 tests
  - `test_rag_pipeline.py` — 7 tests

---

## Architecture Gaps (What's Missing vs Plan)

| Architecture Layer | Status | Gap |
|---|---|---|
| Customer Platforms | — | Out of scope (customer-side) |
| Log Collection Layer | ✅ Built | — |
| Log Ingestion API | ✅ Built | — |
| Message Queue | ✅ Built | — |
| **Log Storage (raw logs)** | ❌ Missing | Raw log text not stored anywhere; only metadata in PostgreSQL. Architecture calls for S3/MinIO. |
| **Log Processing Layer** | ⚠️ Partial | `parser.py` exists and is tested but **not wired into the worker**. Worker still does a naive `message.split(":")` instead of using `extract_error()`. |
| AI Debugging Engine | ✅ Built | Prompt is basic — no RAG / vector retrieval yet |
| **Root Cause Engine** | ⚠️ Stub | `rank_hypotheses()` sorts by score but is never called; AI result goes straight to DB |
| API Layer | ✅ Built | — |
| Web Dashboard | ✅ Built | Run history tab not shown in modal yet |
| Slack Alerts | ✅ Built | — |
| **RAG / Vector DB** | ❌ Missing | Architecture calls for embedding + similarity search (pgvector/Qdrant). Currently LLM gets raw message only. |

---

## Known Issues / Technical Debt

- **Port 5432 conflict** — older PostgreSQL at `/Library/PostgreSQL/16`; Homebrew pg on 5433
- **Docker Desktop not installed** — compose file is written but cannot be built/run yet
- **Webhook collector not auto-started** — needs a start script like the other services

---

## Next Steps (Priority Order)

1. **Wire Log Processing Layer into worker** — replace naive `split(":")` with `extract_error()` from `log-processing-layer/parser.py`; pass `severity` + `summary` to AI prompt for richer analysis
2. **RAG / Vector DB** — install `pgvector`, store error embeddings, retrieve similar past failures to ground the LLM prompt (highest AI quality improvement)
3. **Run History UI** — show `GET /pipelines/{name}/runs` in the pipeline detail modal
4. **Log Storage (raw)** — store raw log text to PostgreSQL `logs_metadata` table (skip S3 for MVP; add later)
5. **Root Cause Engine integration** — use `rank_hypotheses()` to score + rank AI output before saving
