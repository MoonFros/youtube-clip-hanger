#!/usr/bin/env bash
# FairClip — start the whole app (backend :8000 + frontend :3000).
# Usage: ./run.sh          (Ctrl+C stops both)
#        ./run.sh backend  (backend only)
#        ./run.sh web      (frontend only)
set -euo pipefail
cd "$(dirname "$0")"

WHAT="${1:-all}"
PY="${PYTHON:-python3}"

echo "=== FairClip ==="
echo "repo: $PWD"

# ---------------------------------------------------------------- backend ---
if [ "$WHAT" = "all" ] || [ "$WHAT" = "backend" ]; then
  if [ ! -d backend/.venv ]; then
    echo "[setup] creating backend/.venv ..."
    "$PY" -m venv backend/.venv
  fi
  VENV_PY="backend/.venv/bin/python"
  if [ ! -f backend/.venv/.deps-ok ]; then
    echo "[setup] installing python deps (one time, ~2 min)..."
    "$VENV_PY" -m pip install --upgrade pip >/dev/null
    "$VENV_PY" -m pip install -r backend/requirements.txt \
        --only-binary=av,numpy,pillow,yt-dlp
    touch backend/.venv/.deps-ok
  fi
fi

if [ "$WHAT" = "all" ] || [ "$WHAT" = "web" ]; then
  if [ ! -d frontend/node_modules ]; then
    echo "[setup] installing frontend deps (one time)..."
    npm --prefix frontend install
  fi
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ "$WHAT" = "all" ] || [ "$WHAT" = "backend" ]; then
  echo "[1/2] backend  -> http://localhost:8000/api/health   (docs: /docs)"
  # --timeout-keep-alive: the Next dev proxy reuses connections; uvicorn's 5s
  # default can close one exactly as it is reused -> "socket hang up" in the
  # frontend log. 75s removes that race.
  backend/.venv/bin/python -m uvicorn backend.app.main:app \
      --host 0.0.0.0 --port 8000 --timeout-keep-alive 75 &
fi

if [ "$WHAT" = "all" ] || [ "$WHAT" = "web" ]; then
  echo "[2/2] frontend -> http://localhost:3000"
  npm --prefix frontend run dev &
fi

wait
