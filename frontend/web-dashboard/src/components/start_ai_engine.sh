#!/bin/bash

# Navigate to the AI Debugging Engine directory
cd /Users/soumitrabanerjee/Desktop/ai-pipeline-debugger/services/ai-debugging-engine

# Check if venv exists, if not create it
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate the virtual environment
source venv/bin/activate

# Install dependencies if not already installed
echo "Installing dependencies..."
pip install fastapi uvicorn openai

# Run the server on port 8002
echo "Starting AI Debugging Engine..."
uvicorn main:app --reload --port 8002
