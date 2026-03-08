#!/bin/bash

# Navigate to the API layer directory
cd /Users/soumitrabanerjee/Desktop/ai-pipeline-debugger/services/api-layer

# Check if venv exists, if not create it
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate the virtual environment
source venv/bin/activate

# Install dependencies if not already installed
echo "Installing dependencies..."
pip install fastapi uvicorn sqlalchemy

# Run the server
echo "Starting API Layer server..."
uvicorn main:app --reload --port 8001
