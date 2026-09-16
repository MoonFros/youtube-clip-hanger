"""Job pipeline: ingest (upload/direct link/YouTube/demo) -> preview transcode
-> analysis -> stem separation -> transcription. Runs as an asyncio task."""
from __future__ import annotations

import asyncio
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Optional

import httpx
import numpy as np

from . import analysis, transcribe
from .config import MAX_UPLOAD_BYTES, PREVIEW_MAX_HEIGHT, WAVEFORM_BUCKETS, DATA_DIR
from .engine import decode_audio, probe
from .stems import separate_stems, SR
from .store import Job, STORE

STAGES = ["probing", "preview", "scenes", "audio-profile", "stems", "transcript"]


def job_dir(job: Job) -> Path:
    d = DATA_DIR / job.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def set_stage(job: Job, stage: str, progress: float) -> None:
    job.stage = stage
    job.progress = progress


async def run_job(job_id: str) -> None:
    job = STORE.get_job(job_id)
    if job is None:
        return
    job.status = "processing"
    try:
        for i, stage in enumerate(STAGES):
            set_stage(job, stage, i / len(STAGES))
            fn = _stage_fns[stage]
            await asyncio.to_thread(fn, job)
            set_stage(job, stage, (i + 1) / len(STAGES))
        job.status = "ready"
        job.stage = "ready"
        job.progress = 1.0
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()


# ---------------- stages ------------------------------------------------------

def _stage_probe(job: Job) -> None:
    path = job.source_path
    if not path or not os.path.exists(path):
        raise FileNotFoundError("source file missing")
    info = probe(path)
    job.duration = info["duration"]
    job.width, job.height, job.fps = info["width"], info["height"], info["fps"]
    job.has_audio = info["has_audio"]


def _stage_preview(job: Job) -> None:
    """Ensure a browser-playable H.264/AAC mp4 exists."""
    d = job_dir(job)
    src = job.source_path
    preview = d / "preview.mp4"
    info = probe(src)
    fast = (info["vcodec"] == "h264" and info["acodec"] == "aac"
            and info["container"] in ("mp4", "mov") and info["height"] <= PREVIEW_MAX_HEIGHT)
    if fast and not str(src).endswith("preview.mp4"):
        shutil.copyfile(src, preview)
        job.preview_path = str(preview)
        return
    if str(src).endswith("preview.mp4") and preview.exists():
        job.preview_path = str(preview)
        return
    _transcode_preview(src, str(preview))
    job.preview_path = str(preview)


def _transcode_preview(src: str, dst: str) -> None:
    from .engine import frame_to_av, mux_output, iter_frames
    info = probe(src)
    w, h = info["width"], info["height"]
    if h > PREVIEW_MAX_HEIGHT:
        scale = PREVIEW_MAX_HEIGHT / h
        ow, oh = int(w * scale // 2 * 2), int(PREVIEW_MAX_HEIGHT // 2 * 2)
    else:
        ow, oh = w // 2 * 2, h // 2 * 2
    fps = 30 if info["fps"] < 45 else 60

    def gen():
        for t, img in iter_frames(src):
            from PIL import Image
            yield np.asarray(Image.fromarray(img).resize((ow, oh), Image.BILINEAR))

    audio, sr = decode_audio(src, sr=48000, mono=False) if info["has_audio"] else (None, 48000)
    mux_output(dst, ow, oh, fps, gen(), audio=audio, audio_sr=sr, crf=23,
               preset="veryfast")


def _stage_scenes(job: Job) -> None:
    path = job.preview_path or job.source_path
    job.scenes = analysis.detect_scenes(path)
    job.letterbox = analysis.detect_letterbox(path)


def _stage_audio_profile(job: Job) -> None:
    path = job.preview_path or job.source_path
    if job.has_audio:
        job.waveform = analysis.audio_envelope(path)


def _stage_stems(job: Job) -> None:
    path = job.preview_path or job.source_path
    if not job.has_audio:
        job.stems = {"status": "skipped"}
        return
    x, sr = decode_audio(path, sr=SR, mono=True)
    res = separate_stems(x[0])
    d = job_dir(job)
    np.savez_compressed(d / "stems.npz",
                        dialogue=res["dialogue"], music=res["music"], sfx=res["sfx"])
    job.stems = {"status": "ready", "model": "fairclip-stem-1 (on-device STFT HPSS)",
                 "env": res["env"]}
    job.stems_ready = True


def _stage_transcript(job: Job) -> None:
    if job.demo and job.transcript.get("status") == "ready":
        return  # demo ships with ground-truth transcript
    job.transcript = transcribe.transcribe_job(job)
    # suggest clips (works with or without transcript)
    _suggest(job)


def _suggest(job: Job) -> None:
    from .config import TIERS
    tier = TIERS[STORE.settings.get("plan", "free")]
    job.suggested_clips = analysis.suggest_clips(
        {"duration": job.duration},
        job.waveform, job.scenes, job.transcript if job.transcript.get("status") == "ready" else None,
        max_duration=tier["max_clip_seconds"], count=8,
    )


_STAGE_FNS = {
    "probing": _stage_probe,
    "preview": _stage_preview,
    "scenes": _stage_scenes,
    "audio-profile": _stage_audio_profile,
    "stems": _stage_stems,
    "transcript": _stage_transcript,
}


# ---------------- source acquisition ------------------------------------------

def ingest_upload(job: Job, fileobj) -> None:
    d = job_dir(job)
    src = d / "source.mp4"
    with open(src, "wb") as f:
        shutil.copyfileobj(fileobj, f, length=1 << 20)
    if os.path.getsize(src) > MAX_UPLOAD_BYTES:
        os.remove(src)
        raise ValueError("File too large (2GB max)")
    job.source_path = str(src)


async def ingest_link(job: Job, url: str) -> None:
    """Download a direct video URL (works for reachable hosts)."""
    d = job_dir(job)
    src = d / "source.mp4"
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Download failed (HTTP {r.status_code})")
            with open(src, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    f.write(chunk)
    job.source_path = str(src)


async def ingest_youtube(job: Job, url: str) -> None:
    d = job_dir(job)
    src = d / "source.mp4"
    import yt_dlp

    class _Prog:
        pass

    params = {
        "format": "mp4[height<=1080]/mp4/best",
        "outtmpl": str(src),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    def dl():
        with yt_dlp.YoutubeDL(params) as ydl:
            ydl.download([url])

    try:
        await asyncio.to_thread(dl)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Could not download from YouTube in this environment "
            f"({str(e)[:160]}). Upload the file directly or use a reachable "
            "direct video link. On a normal server (internet egress) YouTube "
            "URLs work out of the box."
        )
    job.source_path = str(src)


def finalize_job_source(job: Job) -> None:
    """Rename uploaded source by extension & set name."""
    job.name = Path(job.source or "upload").name or "Untitled video"
