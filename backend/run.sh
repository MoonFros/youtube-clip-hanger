#!/usr/bin/env bash
# FairClip backend only (port 8000). Prefer the root ./run.sh which starts
# backend + frontend together.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "[setup] creating backend/.venv ..."
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.deps-ok ]; then
  echo "[setup] installing python deps ..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.deps-ok
fi

echo "FairClip API -> http://localhost:${PORT:-8000}/api/health"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
