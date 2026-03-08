#!/bin/bash

cd /Users/soumitrabanerjee/Desktop/ai-pipeline-debugger

# Check if venv exists, create if not
if [ ! -d "services/queue-worker/venv" ]; then
    echo "Creating virtual environment for worker..."
    python3 -m venv services/queue-worker/venv
fi

source services/queue-worker/venv/bin/activate

echo "Installing dependencies..."
pip install redis sqlalchemy psycopg2-binary requests

echo "Starting Queue Worker..."
python3 services/queue-worker/worker.py
