#!/bin/bash
# Run from backend folder OR root
cd "$(dirname "$0")/.."
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
