#!/bin/bash
# YouTube Clip Hanger - Run backend (port 8000)
# Usage: ./run.sh  OR  bash run.sh

set -e
cd "$(dirname "$0")"

echo "=== YouTube Clip Hanger Backend ==="
echo "Installing requirements..."
pip install -r backend/requirements.txt

echo ""
echo "Starting backend on http://0.0.0.0:8000 ..."
echo "Check health: http://localhost:8000/api/health"
echo "Docs: http://localhost:8000/docs"
echo ""

python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
