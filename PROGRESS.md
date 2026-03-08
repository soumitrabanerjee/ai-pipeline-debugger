# Project Progress & Context

## Current Status (As of March 7, 2026)

The project is a functional full-stack application with a React frontend, a FastAPI backend, a Log Ingestion service, and an **AI Debugging Engine**.

### Components
1.  **Frontend (Web Dashboard)**
    *   **Location**: `frontend/web-dashboard`
    *   **Tech**: React, Vite
    *   **Status**: Running on `http://localhost:5173`.
    *   **Features**:
        *   Displays a list of pipelines and their status.
        *   Displays error analysis with AI-generated root causes and fixes.
        *   **New**: "Add Pipeline" form to dynamically create pipelines.
        *   **New**: Auto-refresh every 5 seconds to show live updates.
    *   **Data Source**: Fetches data from the Backend API (`http://localhost:8001/dashboard`).

2.  **Backend API (API Layer)**
    *   **Location**: `services/api-layer`
    *   **Tech**: FastAPI, SQLAlchemy, SQLite
    *   **Status**: Running on `http://localhost:8001`.
    *   **Database**: Uses a local SQLite file (`pipeline_debugger.db`) in the `services/api-layer` directory.
    *   **Endpoints**:
        *   `GET /dashboard`: Returns pipeline status and errors.
        *   `POST /pipelines`: Creates a new pipeline.
        *   `GET /health`: Health check.

3.  **Log Ingestion API**
    *   **Location**: `services/log-ingestion-api`
    *   **Tech**: FastAPI, SQLAlchemy
    *   **Status**: Running on `http://localhost:8000`.
    *   **Database**: Connected to the same SQLite database (`pipeline_debugger.db`) as the API Layer.
    *   **AI Integration**: Calls the AI Debugging Engine (`http://localhost:8002/analyze`) when an error log is received.
    *   **Endpoints**:
        *   `POST /ingest`: Accepts log events, updates the database, and triggers AI analysis.

4.  **AI Debugging Engine**
    *   **Location**: `services/ai-debugging-engine`
    *   **Tech**: FastAPI
    *   **Status**: Running on `http://localhost:8002`.
    *   **Functionality**: Analyzes error messages and returns a root cause and suggested fix.
    *   **Current State**: Uses **Mock Logic** (heuristics) because valid API keys for OpenAI/Gemini were not available during testing.
    *   **Endpoints**:
        *   `POST /analyze`: Analyzes an error message.

5.  **Shared Services**
    *   **Location**: `services/shared`
    *   **Content**: `models.py` containing SQLAlchemy models (`Pipeline`, `Error`).
    *   **Usage**: Imported by both API Layer and Log Ingestion API to ensure schema consistency.

### Recent Changes
*   **Auto-Refresh**: Added polling to the dashboard to refresh data every 5 seconds.
*   **AI Integration**: Created `services/ai-debugging-engine` and connected it to the Log Ingestion API.
*   **Refactoring**: Moved database models to `services/shared/models.py` and updated both services to import from there.
*   **Database Switch**: Switched from PostgreSQL (Docker) to SQLite for easier local development without Docker dependencies.
*   **Dynamic Data**: The dashboard now fetches real data from the SQLite database instead of using hardcoded mock data.
*   **Pipeline Creation**: Added a UI form to create new pipelines, which persists them to the database.
*   **Ingestion Connected**: The Log Ingestion API now writes to the database, allowing real-time updates from log events.
*   **Startup Scripts**: Created scripts to easily start the services.

## How to Run the Project

### 1. Start the Backend API (Port 8001)
```bash
/bin/zsh /Users/soumitrabanerjee/Desktop/ai-pipeline-debugger/frontend/web-dashboard/src/components/start_api_layer.sh
```

### 2. Start the Log Ingestion API (Port 8000)
```bash
/bin/zsh /Users/soumitrabanerjee/Desktop/ai-pipeline-debugger/frontend/web-dashboard/src/components/start_ingestion.sh
```

### 3. Start the AI Debugging Engine (Port 8002)
```bash
/bin/zsh /Users/soumitrabanerjee/Desktop/ai-pipeline-debugger/frontend/web-dashboard/src/components/start_ai_engine.sh
```

### 4. Start the Frontend Dashboard (Port 5173)
```bash
cd frontend/web-dashboard
npm run dev
```
*   Access the dashboard at `http://localhost:5173`.

## Next Steps (To-Do)

1.  **Enable Real AI**:
    *   **Task**: Replace the mock logic in `services/ai-debugging-engine/main.py` with a real call to OpenAI or Gemini API.
    *   **Prerequisite**: Obtain a valid API key with sufficient quota.
    *   **Code**: Uncomment the API call logic and set the `OPENAI_API_KEY` or `GEMINI_API_KEY` environment variable.

2.  **Improve UI**:
    *   Add a detailed view for each pipeline to show historical runs and errors.

3.  **Docker Support (Optional)**:
    *   Re-enable Docker support for PostgreSQL if production deployment is needed later.
