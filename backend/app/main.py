"""FairClip backend — FastAPI entrypoint.

Run:  cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import shutil
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import DATA_DIR, JOB_RETENTION_HOURS
from .store import STORE


async def _cleanup_loop() -> None:
    """Auto-delete processed files after 24h (free-tier retention)."""
    while True:
        await asyncio.sleep(1800)
        try:
            now = time.time()
            for d in DATA_DIR.iterdir():
                if not d.is_dir() or d.name in ("demo",):
                    continue
                job = STORE.get_job(d.name)
                age_ok = (job is None and now - d.stat().st_mtime > JOB_RETENTION_HOURS * 3600)
                if age_ok:
                    shutil.rmtree(d, ignore_errors=True)
                    if job:
                        STORE.jobs.pop(d.name, None)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="FairClip API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api/demo/status")
def demo_status():
    from .api import demo_state
    return demo_state
