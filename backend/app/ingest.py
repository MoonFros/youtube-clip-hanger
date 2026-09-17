"""Job pipeline: ingest (upload/direct link/YouTube/demo) -> preview transcode
-> analysis -> stem separation -> transcription. Runs as an asyncio task.

Progress model
--------------
Every stage owns a slice of the 0..1 progress bar (STAGE_WEIGHTS) and can
report a fraction *within* its slice, so the UI shows a real percentage +
human-readable detail ("42% · 3.1 MB/s · ETA 1:20") instead of an opaque
spinner. Cancellation is cooperative: whatever checks `job.cancel_requested`
(the download hook, and between stages) aborts with a `CancelledError`.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import numpy as np

from . import analysis, transcribe
from .config import (
    MAX_UPLOAD_BYTES,
    PREVIEW_MAX_HEIGHT,
    DATA_DIR,
    FFMPEG,
    STEMS_SR,
    STEMS_SR_LONG,
    STEMS_LONG_THRESHOLD_S,
    YTDLP_FORMAT,
    YTDLP_MAX_HEIGHT,
    YTDLP_EXTRA_ARGS,
    YTDLP_COOKIES_FROM_BROWSER,
    YTDLP_COOKIES_FILE,
    YTDLP_MAX_SOURCE_MINUTES,
)
from .engine import OperationCancelled, decode_audio, ffmpeg_available, probe
from .stems import separate_stems_chunked
from .store import Job, STORE


# The cancellation signal lives in `engine` because the ffmpeg helpers need to
# raise it themselves; `JobCancelled` stays as the readable alias used here.
JobCancelled = OperationCancelled


# Which share of the total ingest time each stage normally takes. Used both for
# the progress bar and to decide "is this stage taking suspiciously long?".
STAGE_WEIGHTS: Dict[str, float] = {
    "downloading": 0.30,
    "probing": 0.01,
    "preview": 0.22,
    "scenes": 0.08,
    "audio-profile": 0.09,
    "stems": 0.20,
    "transcript": 0.10,
}
STAGE_ORDER = ["downloading", "probing", "preview", "scenes", "audio-profile",
               "stems", "transcript"]

_SPAN: Dict[str, Tuple[float, float]] = {}
_acc = 0.0
for _s in STAGE_ORDER:
    _w = STAGE_WEIGHTS.get(_s, 0.0)
    _SPAN[_s] = (_acc, _acc + _w)
    _acc += _w
# normalise (weights may not sum to exactly 1)
_SPAN = {k: (a / _acc, b / _acc) for k, (a, b) in _SPAN.items()}


def job_dir(job: Job) -> Path:
    d = DATA_DIR / job.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def set_stage(job: Job, stage: str, frac: float = 0.0, detail: str = "") -> None:
    """Set the stage and a 0..1 fraction *within* that stage."""
    lo, hi = _SPAN.get(stage, (job.progress, job.progress))
    inner = lo + (hi - lo) * max(0.0, min(1.0, frac))
    win_lo = getattr(job, "progress_lo", 0.0)
    win_hi = getattr(job, "progress_hi", 1.0)
    job.stage = stage
    job.progress = max(0.0, min(1.0, win_lo + (win_hi - win_lo) * inner))
    job.detail = detail


def check_cancel(job: Job) -> None:
    if job.cancel_requested:
        raise JobCancelled()


async def run_job(job_id: str, base: float = 0.0, span: float = 1.0) -> None:
    """Run every analysis stage. `base`/`span` let a caller reserve part of the
    progress bar for work it already did (the demo build does this)."""
    job = STORE.get_job(job_id)
    if job is None:
        return
    job.progress_lo = base
    job.progress_hi = min(1.0, base + span)
    job.status = "processing"
    job.error = ""
    try:
        for stage in ("probing", "preview", "scenes", "audio-profile",
                      "stems", "transcript"):
            check_cancel(job)
            set_stage(job, stage, 0.0)
            fn = _STAGE_FNS[stage]
            await asyncio.to_thread(fn, job)
            set_stage(job, stage, 1.0)
        job.status = "ready"
        job.stage = "ready"
        job.progress = 1.0
        job.detail = ""
    except JobCancelled:
        job.status = "cancelled"
        job.stage = "cancelled"
        job.detail = ""
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"
        job.detail = ""
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
    if job.duration <= 0:
        raise RuntimeError("could not read the video's duration (file looks corrupt or incomplete)")


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

    def prog(i: int, n: int) -> None:
        check_cancel(job)
        if n:
            set_stage(job, "preview", i / n,
                      f"transcoding preview {100 * i / n:.0f}%"
                      f"{'' if ffmpeg_available() else ' (no ffmpeg: slow path)'}")

    from .engine import transcode_preview
    transcode_preview(src, str(preview), preview_max_height=PREVIEW_MAX_HEIGHT,
                      progress_cb=prog, total_frames_t0=info["duration"],
                      cancelled=lambda: job.cancel_requested)
    job.preview_path = str(preview)


def _stage_scenes(job: Job) -> None:
    path = job.preview_path or job.source_path
    job.scenes = analysis.detect_scenes(
        path, cancelled=lambda: job.cancel_requested)
    job.letterbox = analysis.detect_letterbox(path)


def _stage_audio_profile(job: Job) -> None:
    path = job.preview_path or job.source_path
    if not job.has_audio:
        return
    if job.waveform:
        return
    def _prog(f: float) -> None:
        check_cancel(job)
        set_stage(job, "audio-profile", f, "analysing audio")

    job.waveform = analysis.audio_envelope(path, progress_cb=_prog)


def _stage_stems(job: Job) -> None:
    path = job.preview_path or job.source_path
    if not job.has_audio:
        job.stems = {"status": "skipped"}
        return
    # Long videos are analysed at a lower sample rate: 3x faster and ~4x less
    # memory, at the cost of >8 kHz detail in the separated layers. The renderer
    # reads the rate back from the .npz, so nothing else has to change.
    sr = STEMS_SR_LONG if job.duration >= STEMS_LONG_THRESHOLD_S else STEMS_SR
    x, _ = decode_audio(path, sr=sr, mono=True)
    if x.size == 0:
        job.stems = {"status": "skipped"}
        return

    def prog(f: float) -> None:
        check_cancel(job)
        set_stage(job, "stems", f,
                  f"separating dialogue / music / sfx ({sr // 1000} kHz)")

    res = separate_stems_chunked(x[0], sr=sr, progress_cb=prog)
    d = job_dir(job)
    # 16-bit storage halves the file size (an hour of 48 kHz float32 stems
    # would be ~2 GB); the renderer converts back to float on load.
    def _i16(a: np.ndarray) -> np.ndarray:
        return np.clip(a * 32767.0, -32768, 32767).astype("<i2")

    np.savez(d / "stems.npz", dialogue=_i16(res["dialogue"]),
             music=_i16(res["music"]), sfx=_i16(res["sfx"]),
             sr=np.int32(sr))
    job.stems = {"status": "ready", "sr": sr,
                 "model": "fairclip-stem-1 (on-device STFT HPSS)",
                 "env": res["env"]}
    job.stems_ready = True


def _stage_transcript(job: Job) -> None:
    if job.demo and job.transcript.get("status") == "ready":
        # demo ships with ground-truth transcript; still run suggestion
        _suggest(job)
        return
    if job.transcript.get("status") == "ready" and job.transcript.get("words"):
        _suggest(job)
        return

    def prog(f: float, msg: str = "") -> None:
        check_cancel(job)
        set_stage(job, "transcript", f, msg or "transcribing")

    job.transcript = transcribe.transcribe_job(job, progress_cb=prog)
    _suggest(job)


def _suggest(job: Job) -> None:
    from .config import TIERS
    tier = TIERS[STORE.settings.get("plan", "free")]
    job.suggested_clips = analysis.suggest_clips(
        {"duration": job.duration},
        job.waveform, job.scenes,
        job.transcript if job.transcript.get("status") == "ready" else None,
        max_duration=tier["max_clip_seconds"], count=8,
    )
    # Fallback: short videos (or ones with no detectable structure) still get
    # one usable clip so the editor is never empty.
    if not job.suggested_clips and job.duration >= 5:
        L = min(tier["max_clip_seconds"], max(5.0, job.duration - 0.5))
        job.suggested_clips = [{
            "id": "sug1", "start": 0.0, "end": round(L, 2),
            "score": 0.0, "label": f"Full video ({L:.0f}s)",
        }]


_STAGE_FNS = {
    "probing": _stage_probe,
    "preview": _stage_preview,
    "scenes": _stage_scenes,
    "audio-profile": _stage_audio_profile,
    "stems": _stage_stems,
    "transcript": _stage_transcript,
}


# ---------------- source acquisition ------------------------------------------

_UPLOAD_EXT_OK = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".flv",
                  ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".ogv"}


def ingest_upload(job: Job, fileobj, filename: str = "") -> None:
    """Stream an upload to disk, keeping its real extension.

    The extension matters: the preview fast-path (already-H.264/AAC mp4 -> just
    copy) and PyAV's container detection both key off it, and a WebM renamed to
    .mp4 confuses the muxer.
    """
    d = job_dir(job)
    ext = Path(filename or job.source or "").suffix.lower()
    if ext not in _UPLOAD_EXT_OK:
        ext = ".mp4"
    src = d / f"source{ext}"
    total = 0
    with open(src, "wb") as f:
        while True:
            chunk = fileobj.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(src)
                raise ValueError(
                    f"File too large ({total / 1e9:.1f} GB) — the limit is "
                    f"{MAX_UPLOAD_BYTES / 1e9:.0f} GB.")
            f.write(chunk)
    job.source_path = str(src)
    job.name = Path(filename or job.source or "upload").name or "Untitled video"


async def ingest_link(job: Job, url: str) -> None:
    """Download a direct video URL (works for reachable hosts)."""
    d = job_dir(job)
    src = d / "source.mp4"
    set_stage(job, "downloading", 0.0, "connecting…")
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20),
                                 follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Download failed (HTTP {r.status_code})")
            total_bytes = int(r.headers.get("content-length") or 0)
            got = 0
            with open(src, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    got += len(chunk)
                    check_cancel(job)
                    if got > MAX_UPLOAD_BYTES:
                        raise ValueError("Remote file is larger than the 2 GB limit")
                    f.write(chunk)
                    if total_bytes:
                        set_stage(job, "downloading", got / total_bytes,
                                  f"downloading {got / 1e6:.0f}/{total_bytes / 1e6:.0f} MB")
    job.source_path = str(src)


def _ytdlp_params(job: Job, src_tmpl: str) -> Dict[str, Any]:
    """Slow-but-safe yt-dlp settings.

    Notes on why these specific values:
      * `format`: prefer a *muxed* mp4 at <=720p (single stream, no ffmpeg
        merge, plays everywhere); fall back to DASH video+audio merged to mp4,
        then to whatever is available. Downloading 1080p+ by default is what
        made this feel like it "took years" — 720p halves the bytes and the
        analysis cost.
      * `concurrent_fragment_downloads`: YouTube serves DASH in small
        fragments; downloading 4 at a time is 2-4x faster on a home line.
      * retries/socket_timeout: a flaky connection used to abort the whole job.
      * `progress_hooks`: drives the UI percentage + speed + ETA.
    """
    params: Dict[str, Any] = {
        "format": YTDLP_FORMAT or (
            f"b[ext=mp4][height<={YTDLP_MAX_HEIGHT}]/"
            f"bv*[height<={YTDLP_MAX_HEIGHT}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={YTDLP_MAX_HEIGHT}]+ba/"
            f"b[height<={YTDLP_MAX_HEIGHT}]/b"
        ),
        "outtmpl": src_tmpl,
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "nopart": False,
        "overwrites": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "merge_output_format": "mp4" if ffmpeg_available() else None,
        "progress_hooks": [_progress_hook(job)],
        "postprocessor_hooks": [_pp_hook(job)],
    }
    if not ffmpeg_available():
        # without ffmpeg we cannot merge/remux: only single-file formats work
        params["format"] = (f"b[height<={YTDLP_MAX_HEIGHT}]/b")
        params.pop("merge_output_format", None)
    if YTDLP_COOKIES_FROM_BROWSER:
        params["cookiesfrombrowser"] = (YTDLP_COOKIES_FROM_BROWSER,)
    if YTDLP_COOKIES_FILE:
        params["cookiefile"] = YTDLP_COOKIES_FILE
    if YTDLP_MAX_SOURCE_MINUTES:
        cap = YTDLP_MAX_SOURCE_MINUTES * 60.0
        params["download_ranges"] = lambda info, _ydl, n=cap: [{"start_time": 0,
                                                               "end_time": n}]
        params["force_keyframes_at_cuts"] = False
    if YTDLP_EXTRA_ARGS:
        # "key=value,key=value" escape hatch for power users
        for chunk in YTDLP_EXTRA_ARGS.split(","):
            k, _, v = chunk.partition("=")
            k = k.strip()
            if not k:
                continue
            if v.lower() in ("true", "false"):
                params[k] = v.lower() == "true"
            elif v.replace(".", "", 1).isdigit():
                params[k] = float(v) if "." in v else int(v)
            else:
                params[k] = v
    return params


def _fmt_eta(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _progress_hook(job: Job):
    def hook(d: Dict[str, Any]) -> None:
        if job.cancel_requested:
            raise JobCancelled("cancelled by user")
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            frac = (got / total) if total else 0.0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            parts = []
            if total:
                parts.append(f"{got / 1e6:.0f}/{total / 1e6:.0f} MB")
            if speed:
                parts.append(f"{speed / 1e6:.1f} MB/s")
            if eta:
                parts.append(f"ETA {_fmt_eta(eta)}")
            set_stage(job, "downloading", frac,
                      " · ".join(parts) if parts else "downloading…")
        elif status == "finished":
            set_stage(job, "downloading", 1.0, "download finished — preparing…")
    return hook


def _pp_hook(job: Job):
    def hook(d: Dict[str, Any]) -> None:
        if job.cancel_requested:
            raise JobCancelled("cancelled by user")
        name = (d.get("postprocessor") or "").replace("FFmpeg", "")
        if d.get("status") == "started":
            set_stage(job, "downloading", 0.95, f"{name or 'processing'}…")
    return hook


async def ingest_youtube(job: Job, url: str) -> None:
    """Download a YouTube video (or anything yt-dlp supports) to source.<ext>."""
    d = job_dir(job)
    src_tmpl = str(d / "source.%(ext)s")
    for old in d.glob("source.*"):
        if old.suffix not in (".npz",):
            old.unlink(missing_ok=True)

    try:
        import yt_dlp  # noqa: F401
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "yt-dlp is not installed — run `pip install -r backend/requirements.txt`"
        ) from e

    import yt_dlp

    params = _ytdlp_params(job, src_tmpl)
    set_stage(job, "downloading", 0.0, "resolving video…")
    info: Dict[str, Any] = {}

    def dl() -> None:
        nonlocal info
        with yt_dlp.YoutubeDL(params) as ydl:
            info = ydl.extract_info(url, download=True) or {}

    try:
        await asyncio.to_thread(dl)
    except JobCancelled:
        raise
    except Exception as e:  # noqa: BLE001
        msg = " ".join(str(e).split())
        low = msg.lower()
        hint = ""
        if "sign in" in low or "bot" in low or "cookies" in low or "403" in low:
            hint = (" — YouTube is asking for a signed-in session. Set "
                    "FAIRCLIP_COOKIES_FROM_BROWSER=chrome (or =edge/firefox) so "
                    "yt-dlp can use your browser cookies, then retry.")
        elif "unsupported url" in low or "is not a valid url" in low:
            hint = " — that doesn't look like a video URL."
        elif "private" in low or "unavailable" in low or "removed" in low:
            hint = " — the video is private, removed or region-blocked."
        elif "timed out" in low or "connection" in low or "network" in low:
            hint = " — network problem while downloading."
        # yt-dlp appends a "please report this issue" paragraph + version blurb;
        # keep the first meaningful sentence only.
        short = msg.split(" please report this issue")[0].split("; please report")[0]
        raise RuntimeError(f"YouTube download failed: {short[:240]}{hint}")

    check_cancel(job)

    # Resolve whatever file yt-dlp actually wrote.
    path = ""
    try:
        if info.get("requested_downloads"):
            path = info["requested_downloads"][0].get("filepath") or ""
    except Exception:
        path = ""
    if not path or not os.path.exists(path):
        cands = [p for p in d.glob("source.*") if p.suffix != ".npz"]
        cands.sort(key=lambda p: p.stat().st_size, reverse=True)
        path = str(cands[0]) if cands else ""
    if not path or not os.path.exists(path):
        raise RuntimeError("yt-dlp reported success but no file was written")

    job.source_path = path
    if info.get("title"):
        job.name = str(info["title"])[:120]
        job.source = str(info.get("webpage_url") or url)
    set_stage(job, "downloading", 1.0, "downloaded")


def finalize_job_source(job: Job) -> None:
    """Set a friendly name when the source is a local file."""
    if job.source_path and (not job.name or job.name in ("Untitled video", "upload")):
        job.name = Path(job.source_path).name
