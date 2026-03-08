# Project Progress & Context

## Current Status (As of March 8, 2026)

The project is a functional full-stack application with a React frontend, three FastAPI backend services, and a **live AI Debugging Engine powered by local Llama 3.1 via Ollama**.

---

## Architecture

```
Frontend (React/Vite)  :5173
        |
API Layer (FastAPI)    :8001  ──── PostgreSQL :5433 (pipeline_debugger)
        |                               |
Log Ingestion API      :8000  ──────────┘
        |
AI Debugging Engine    :8002
        |
Ollama (llama3.1:8b)   :11434
```

---

## Components

### 1. Frontend (Web Dashboard)
- **Location**: `frontend/web-dashboard`
- **Tech**: React, Vite
- **Status**: Running on `http://localhost:5173`
- **Features**:
  - Displays pipelines and their statuses
  - Displays AI-generated root causes and fixes per error
  - "Add Pipeline" form for dynamic pipeline creation
  - Auto-refresh every 5 seconds for live updates
- **Data Source**: `http://localhost:8001/dashboard`

### 2. API Layer
- **Location**: `services/api-layer`
- **Tech**: FastAPI, SQLAlchemy, PostgreSQL
- **Status**: Running on `http://localhost:8001`
- **Database**: PostgreSQL at `localhost:5433/pipeline_debugger`
- **Endpoints**:
  - `GET /dashboard` — Returns all pipelines and errors
  - `POST /pipelines` — Creates a new pipeline
  - `GET /health`

### 3. Log Ingestion API
- **Location**: `services/log-ingestion-api`
- **Tech**: FastAPI, SQLAlchemy
- **Status**: Running on `http://localhost:8000`
- **Database**: Shares PostgreSQL `pipeline_debugger` with API Layer
- **Endpoints**:
  - `POST /ingest` — Accepts log events, updates pipeline status, triggers AI analysis
  - `GET /health`
- **AI call timeout**: 120 seconds (increased from 5s to give Ollama time to respond)

### 4. AI Debugging Engine
- **Location**: `services/ai-debugging-engine`
- **Tech**: FastAPI, Ollama (requests)
- **Status**: Running on `http://localhost:8002`
- **Model**: `llama3.1:8b` via local Ollama (`http://localhost:11434`)
- **Endpoints**:
  - `POST /analyze` — Returns root cause, suggested fix, confidence score
  - `GET /health`

### 5. Shared Models
- **Location**: `services/shared/models.py`
- **Content**: SQLAlchemy ORM models (`Pipeline`, `Error`)
- **Usage**: Imported by both API Layer and Log Ingestion API

---

## How to Run

### Start all services (separate terminals):

```bash
# 1. API Layer (port 8001)
/bin/zsh frontend/web-dashboard/src/components/start_api_layer.sh

# 2. Log Ingestion API (port 8000)
/bin/zsh frontend/web-dashboard/src/components/start_ingestion.sh

# 3. AI Debugging Engine (port 8002) — requires Ollama running
/bin/zsh frontend/web-dashboard/src/components/start_ai_engine.sh

# 4. Frontend (port 5173)
cd frontend/web-dashboard && npm run dev
```

### Send a test log event:
```bash
./frontend/web-dashboard/new_run.sh
```

### Run tests:
```bash
python3 -m pytest tests/ -v
```

---

## Completed Work

- [x] React dashboard with live auto-refresh (5s polling)
- [x] "Add Pipeline" form persisted to SQLite
- [x] Log ingestion API writing pipeline status + errors to DB
- [x] Migrated from SQLite to PostgreSQL 16 (Homebrew, port 5433)
  - Installed: `postgresql@16` via Homebrew
  - Installed: `psycopg2-binary` in api-layer and log-ingestion-api venvs
  - DB: `postgresql://debugger:debugger@localhost:5433/pipeline_debugger`
  - Both services now read `DATABASE_URL` from env var (falls back to above)
- [x] AI Debugging Engine integrated with real Llama 3.1:8b via Ollama
- [x] Fixed 5-second timeout bug in ingestion → AI call (now 120s)
- [x] Fixed `ollama serve` blocking bug in `new_run.sh` (now runs in background)
- [x] Pipeline detail view — click any pipeline card to open a modal with its full error history
  - New `GET /pipelines/{name}/errors` endpoint in the API layer
  - Modal overlays the dashboard; closes by clicking backdrop or ✕ button
- [x] Dark mode toggle — 🌙/☀️ button, CSS custom properties, persists via localStorage
- [x] **Redis queue (async AI analysis)**
  - Ingestion API now publishes ERROR events to a Redis Stream (`log_events`) and returns 202 immediately — no more blocking on AI
  - New `services/queue-worker/worker.py` — consumer group reads from stream, calls AI engine, writes Error to DB
  - Start script: `frontend/web-dashboard/src/components/start_worker.sh`
  - Redis installed via Homebrew (v8.6.1), running on port 6379
- [x] 76 passing test cases across all services (unit + API + integration)
  - `tests/test_parser.py` — 10 tests
  - `tests/test_root_cause_engine.py` — 7 tests
  - `tests/test_rag_pipeline.py` — 7 tests
  - `tests/test_ai_engine.py` — 10 tests (Ollama mocked)
  - `tests/test_ingestion_api.py` — 12 tests (Redis mocked, verifies queue publish behaviour)
  - `tests/test_api_layer.py` — 17 tests (in-memory SQLite)
  - `tests/test_worker.py` — 18 tests (AI + DB mocked, covers process_event, deduplication, consumer group)

---

## Known Issues / Technical Debt

- ~~**Error deduplication**~~ — fixed; worker now upserts by `(pipeline_name, error_type)`
- **Deprecated SQLAlchemy API**: `declarative_base()` in `shared/models.py` should move to `sqlalchemy.orm.declarative_base()`
- **Deprecated FastAPI event**: `@app.on_event("startup")` in `api-layer/main.py` should be replaced with a `lifespan` context manager
- **Port 5432 conflict**: An older PostgreSQL installation exists at `/Library/PostgreSQL/16`. Homebrew PostgreSQL runs on port **5433** to avoid conflict. The older installation's password is unknown — do not remove it.

---

## Next Steps (To-Do)

1. **Docker Compose**
   - Wrap all services + Ollama in `docker-compose.yml` so the full stack starts with one command

3. **Fix deprecation warnings**
   - Update `shared/models.py` and `api-layer/main.py` as noted above
