# Project Progress & Context

## Current Status (As of March 9, 2026)

Full-stack application: React frontend, four FastAPI backend services, Redis async queue, PostgreSQL, Slack alerting, and a **live Log Collection Layer** connected to a real running Airflow instance.

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
| Frontend | 5173 | ✅ Running (Docker) | React + Vite |
| API Layer | 8001 | ✅ Running (Docker) | FastAPI + PostgreSQL |
| Log Ingestion API | 8000 | ✅ Running (Docker) | FastAPI + Redis |
| AI Debugging Engine | 8002 | ✅ Running (Docker) | FastAPI + Ollama |
| Queue Worker | — | ✅ Running (Docker) | Python + Redis Streams |
| Webhook Collector | 8003 | ✅ Built, not started | FastAPI |
| Log Agent | — | ✅ Built, not started | watchdog |
| PostgreSQL | 5434 | ✅ Running (Docker) | pg16 |
| Redis | 6380 | ✅ Running (Docker) | Redis 7 |
| Ollama | 11434 | ✅ Running (native host) | llama3.1:8b + gemma3:4b |

> **Docker note:** `docker-compose.override.yml` is in place — `ai-engine` points to native host Ollama (`host.docker.internal:11434`) instead of the Docker Ollama container (which is CPU-only and fails its healthcheck on Mac). All services started via `docker compose up -d`.

---

## How to Run

```bash
# ── Docker Compose (preferred) ─────────────────────────────────────
docker compose up -d --no-deps ai-engine   # starts AI engine pointing to host Ollama
docker compose up -d --no-deps queue-worker
# All other services start automatically via docker compose up -d
# dashboard at http://localhost:5173

# ── Send a test error event ────────────────────────────────────────
./frontend/web-dashboard/new_run.sh

# ── Log Collection (run natively, optional) ────────────────────────
python services/log-collection-layer/agent.py \
  --watch-dir /tmp/pipeline-logs --job-id spark-etl-prod

python services/log-collection-layer/simulator.py \
  --type spark --job-id spark-etl-prod --errors 2

# Webhook push (Airflow-style)
curl -X POST http://localhost:8003/webhook/airflow \
  -H 'Content-Type: application/json' \
  -d '{"dag_id":"my-dag","run_id":"run-001","exception":"OOM error"}'

# ── Tests ──────────────────────────────────────────────────────────
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
- [x] **Live-only data** — removed DB seed data (`customer_etl`, `billing_pipeline`, `analytics_daily` fake pipelines + errors) from `api-layer/main.py` lifespan; database now starts empty and populates only from real pipeline events
- [x] **Real Airflow integration** — `debugger_etl_pipeline` DAG created in Airflow, triggers `on_failure_callback` → webhook collector (port 8003) → ingestion API → AI analysis; end-to-end tested with live `MemoryError` from a real Airflow task execution
- [x] **Airflow log parser fix** — updated `_AIRFLOW_RE` regex and `_normalise_ts` in `log_parser.py` to handle `+0530` timezone offset format used by Airflow 3
- [x] Docker Compose file — all 8 services, healthchecks, named volumes; running via Docker Compose with `docker-compose.override.yml` for host Ollama
- [x] **PySpark integration** — `services/spark-jobs/customer_etl.py` (LTV ETL job with realistic UDF `ZeroDivisionError`); `log4j.properties` routes Spark logs to `/tmp/spark-logs/*.log`; `run_spark_etl.sh` starts log agent then fires the job; dual ingestion path (log agent + webhook); `log_parser.py` extended with `_PYSPARK_RE` for native Log4j format (`26/03/09 22:02:23 ERROR Class: msg`) + `%y/%m/%d %H:%M:%S` timestamp format; tested end-to-end: two live Spark pipelines in DB with AI root causes
- [x] **Log Processing Layer wired into worker** — `extract_error()` from `log-processing-layer/parser.py` now replaces the naive `split(":")` in `worker.py`; structured `severity` + `summary` passed as `pipeline_context` to AI engine; fixed Dockerfile to include `services/alerting` and `services/log-processing-layer`; added `PYTHONUNBUFFERED=1` for visible Docker logs
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
| **Log Processing Layer** | ✅ Done | `extract_error()` wired into worker; `error_type` uses `parsed.signature`; `severity` + `summary` sent as `pipeline_context` to AI engine |
| AI Debugging Engine | ✅ Built | Prompt is basic — no RAG / vector retrieval yet |
| **Root Cause Engine** | ⚠️ Stub | `rank_hypotheses()` sorts by score but is never called; AI result goes straight to DB |
| API Layer | ✅ Built | — |
| Web Dashboard | ✅ Built | Run history tab not shown in modal yet |
| Slack Alerts | ✅ Built | — |
| **RAG / Vector DB** | ❌ Missing | Architecture calls for embedding + similarity search (pgvector/Qdrant). Currently LLM gets raw message only. |

---

## Known Issues / Technical Debt

- **Ollama in Docker** — Docker Ollama container is CPU-only on Mac and fails its healthcheck; workaround in `docker-compose.override.yml` routes `ai-engine` to native host Ollama instead
- **Webhook collector not in Docker Compose** — starts natively (`uvicorn webhook_collector:app --port 8003`); needs its own Compose service for full containerisation
- **Log agent not in Docker** — watchdog-based `agent.py` runs natively; Airflow integration uses `on_failure_callback` webhook instead of file-watching for now

---

## Next Steps (Priority Order)

1. ~~**Wire Log Processing Layer into worker**~~ ✅ Done
2. **⭐ RAG / Vector DB** *(recommended next task)* — install `pgvector`, embed errors on ingest, retrieve top-K similar past failures to ground the LLM prompt (highest AI quality improvement)
3. **Root Cause Engine integration** — call `rank_hypotheses()` to score + rank AI hypotheses before saving to DB; currently it exists but is never called
4. **Run History UI** — the `GET /pipelines/{name}/runs` endpoint exists and is tested; just needs to be surfaced in the pipeline detail modal
5. **Log Storage (raw)** — store raw log text in a `raw_logs` PostgreSQL column on the Error record (skip S3 for MVP)
