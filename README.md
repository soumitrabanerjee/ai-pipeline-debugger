# AI Pipeline Debugger

AI Pipeline Debugger is a reference implementation for ingesting, processing, and debugging pipeline failures across **Airflow, Spark, and Databricks** workloads.

It turns raw logs into actionable insights through a staged architecture:

1. Collect logs from customer pipeline systems.
2. Ingest and queue events reliably.
3. Store raw logs + metadata.
4. Parse and extract errors.
5. Run AI-powered debugging and root-cause analysis.
6. Expose findings through APIs, dashboard views, and Slack alerts.

---

## Architecture Overview

```text
Customer Pipelines (Airflow / Spark / Databricks)
          │
          ▼
Log Collection Layer (Webhook / Agent / API Pull)
          │
          ▼
Log Ingestion API (FastAPI)
          │
          ▼
Message Queue (Kafka / Redis Streams)
          │
          ▼
Log Storage (S3 + PostgreSQL metadata)
          │
          ▼
Log Processing Layer (Parser + Error Extractor)
          │
          ▼
AI Debugging Engine (RAG + Vector DB)
          │
          ▼
Root Cause Engine
          │
          ▼
API Layer
          │
     ┌────┴─────┐
     ▼          ▼
Web Dashboard   Slack Alerts
```

---

## Project Structure

```text
.
├── README.md
├── docs/
│   └── architecture.md
├── infra/
│   └── docker-compose.yml
├── services/
│   ├── log-collection-layer/
│   │   └── README.md
│   ├── log-ingestion-api/
│   │   ├── README.md
│   │   └── app/
│   │       └── main.py
│   ├── message-queue/
│   │   └── README.md
│   ├── log-storage/
│   │   └── README.md
│   ├── log-processing-layer/
│   │   ├── README.md
│   │   └── parser.py
│   ├── ai-debugging-engine/
│   │   ├── README.md
│   │   └── rag_pipeline.py
│   ├── root-cause-engine/
│   │   ├── README.md
│   │   └── engine.py
│   └── api-layer/
│       ├── README.md
│       └── openapi.yaml
└── frontend/
    └── web-dashboard/
        ├── index.html
        ├── package.json
        ├── vite.config.js
        └── src/
            ├── main.jsx
            ├── App.jsx
            ├── styles.css
            └── components/
                ├── ArchitectureFlow.jsx
                ├── PipelineHealthTable.jsx
                └── IncidentPanel.jsx
```

---

## Service Responsibilities

### 1) Log Collection Layer
- Collects logs via webhook push, agent tailing, or API pull.
- Normalizes source identity (workspace, job, run, task).
- Sends event payloads to the ingestion API.

### 2) Log Ingestion API (FastAPI)
- Authenticates incoming log producers.
- Applies schema validation and idempotency checks.
- Publishes accepted events to Kafka/Redis Streams.

### 3) Message Queue
- Buffers ingestion spikes.
- Decouples producers from consumers.
- Supports retry and dead-letter queue patterns.

### 4) Log Storage
- Raw/large payloads in S3 (or compatible object store).
- Query metadata in PostgreSQL (job id, run id, error code, timestamps).

### 5) Log Processing Layer
- Parses source-specific logs into canonical schema.
- Extracts stack traces, error signatures, and relevant context chunks.
- Stores enriched artifacts for AI retrieval.

### 6) AI Debugging Engine
- Uses RAG against indexed incident history + runbooks.
- Embeds errors and context into vector DB.
- Produces remediation candidates with confidence scores.

### 7) Root Cause Engine
- Correlates errors across pipeline stages and dependencies.
- Generates ranked root-cause hypotheses.
- Adds impact analysis and recurrence risk.

### 8) API Layer
- Serves incidents, summaries, and recommendation endpoints.
- Powers dashboard and Slack alert integrations.

### 9) Web Dashboard + Slack Alerts
- Dashboard: incident timeline, health overview, root-cause details.
- Slack: high-priority failures and suggested remediations.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker + Docker Compose

### 1. Start local infrastructure
```bash
docker compose -f infra/docker-compose.yml up -d
```

### 2. Run ingestion API
```bash
cd services/log-ingestion-api
uvicorn app.main:app --reload --port 8000
```

### 3. Run frontend dashboard
```bash
cd frontend/web-dashboard
npm install
npm run dev
```

---

## Example Event Contract

```json
{
  "source": "airflow",
  "workspace_id": "acme-prod",
  "job_id": "daily-etl",
  "run_id": "run_2026_01_15_001",
  "task_id": "transform_customers",
  "level": "ERROR",
  "timestamp": "2026-01-15T10:24:41Z",
  "message": "Spark executor lost during shuffle stage",
  "raw_log_uri": "s3://pipeline-logs/acme-prod/airflow/..."
}
```

---

## Recommended Next Steps

1. Add authentication and tenant isolation in `log-ingestion-api`.
2. Replace local queue stub with managed Kafka/Redis.
3. Add parser modules per source (`airflow.py`, `spark.py`, `databricks.py`).
4. Integrate vector DB (pgvector, Pinecone, or Weaviate).
5. Implement Slack webhook notifier in `api-layer`.
6. Add CI pipeline for linting, tests, and image builds.

---

## License

MIT
