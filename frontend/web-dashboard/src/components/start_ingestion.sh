#!/bin/bash

# Navigate to the Ingestion API directory
cd /Users/soumitrabanerjee/Desktop/ai-pipeline-debugger/services/log-ingestion-api

# Check if venv exists, if not create it
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate the virtual environment
source venv/bin/activate

# Install dependencies if not already installed
echo "Installing dependencies..."
pip install fastapi uvicorn sqlalchemy psycopg2-binary requests redis

# Run the server on port 8000
echo "Starting Ingestion API server..."
uvicorn app.main:app --reload --port 8000
