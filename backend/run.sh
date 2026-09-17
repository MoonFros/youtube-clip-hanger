<<<<<<< HEAD
#!/usr/bin/env bash
# FairClip backend dev server
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
=======
#!/bin/bash
# Run from backend folder OR root
cd "$(dirname "$0")/.."
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
>>>>>>> 5363e9344f8e8978c10f2fb43b8cb754986c81f9
