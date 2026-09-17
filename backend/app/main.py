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

from .api import media_router, router
from .config import DATA_DIR, JOB_RETENTION_HOURS
from .engine import av_version, ffmpeg_version
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


def _print_banner() -> None:
    """One line per dependency at startup - the first thing to check when a
    download or a render misbehaves."""
    import sys
    try:
        from importlib.metadata import version
        ytdlp = version("yt-dlp")
    except Exception:
        ytdlp = "missing"
    print(
        "[fairclip] "
        f"python {sys.version.split()[0]} ({'64' if sys.maxsize > 2**32 else '32'}-bit) | "
        f"pyav {av_version()} | yt-dlp {ytdlp} | "
        f"ffmpeg {ffmpeg_version() or 'not found (slower pure-PyAV paths)'} | "
        f"data {DATA_DIR}",
        flush=True,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    _print_banner()
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
app.include_router(media_router)


@app.get("/api/demo/status")
def demo_status():
    from .api import demo_state
    return demo_state
