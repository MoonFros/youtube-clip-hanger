"""Smoke test for the ingest pipeline (the code path that used to hang).

Runs every stage of `app.ingest.run_job` against a local file through the same
functions the API uses, printing timings and the progress it reports.

    cd backend && python tests/ingest_smoke.py /path/to/video.mp4

With no argument it builds a synthetic 60s 720p clip first (needs numpy + av).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from app import ingest  # noqa: E402
from app.config import STEMS_BLOCK_S, STEMS_LONG_THRESHOLD_S, STEMS_SR  # noqa: E402
from app.engine import ffmpeg_available, ffmpeg_version, probe  # noqa: E402
from app.store import STORE  # noqa: E402


def make_video(path: str, seconds: float = 60.0, w: int = 1280, h: int = 720,
               fps: int = 30) -> str:
    """Synthetic clip with moving colour patches + a two-tone audio bed."""
    from app.engine import mux_output
    n = int(seconds * fps)

    def gen():
        for i in range(n):
            t = i / fps
            yy, xx = np.mgrid[0:h, 0:w]
            frame = np.stack([
                (128 + 100 * np.sin(0.7 * t + xx * 0.01)).astype(np.uint8),
                (100 + 90 * np.cos(0.4 * t + yy * 0.013)).astype(np.uint8),
                ((150 + 80 * np.sin(1.3 * t)) * np.ones((h, w))).astype(np.uint8),
            ], axis=2)
            yield np.ascontiguousarray(frame)

    sr = 48000
    t = np.arange(int(seconds * sr)) / sr
    voice = 0.25 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 2.5 * t) > 0)
    music = 0.18 * np.sin(2 * np.pi * 220 * t)
    audio = np.stack([voice + music, voice + music], axis=0).astype(np.float32)
    mux_output(path, w, h, fps, gen(), audio=audio, audio_sr=sr, crf=23,
               preset="veryfast")
    return path


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ingest_smoke.mp4"
    if len(sys.argv) == 1:
        print("[setup] building a 60s 720p synthetic clip ...")
        t0 = time.time()
        make_video(src)
        print(f"[setup] done in {time.time() - t0:.1f}s -> {src}")

    print(f"ffmpeg available: {ffmpeg_available()} {ffmpeg_version()}")
    print(f"probe: {probe(src)}")

    job = STORE.create_job("upload", source=src, name="ingest smoke")
    job.source_path = src
    job.status = "processing"

    last = {"stage": "", "detail": ""}
    t_all = time.time()
    for stage in ("probing", "preview", "scenes", "audio-profile", "stems",
                  "transcript"):
        ingest.set_stage(job, stage, 0.0)
        fn = ingest._STAGE_FNS[stage]
        t0 = time.time()
        fn(job)
        print(f"  {stage:<14} {time.time() - t0:7.2f}s  progress="
              f"{job.progress:.2f}  {job.detail}")
        last["stage"] = stage
    print(f"TOTAL {time.time() - t_all:.2f}s")
    print(f"  duration={job.duration:.1f}s  scenes={len(job.scenes)}  "
          f"waveform={len(job.waveform.get('rms', []))} buckets")
    print(f"  stems: {job.stems.get('status')} @ {job.stems.get('sr', '-')} Hz, "
          f"env bins={len((job.stems.get('env') or {}).get('rms', []))} "
          f"(block={STEMS_BLOCK_S}s, long-mode>={STEMS_LONG_THRESHOLD_S}s, hd={STEMS_SR}Hz)")
    print(f"  transcript: {job.transcript.get('status')} "
          f"({job.transcript.get('reason') or job.transcript.get('engine', '')})")
    print(f"  suggested clips: {len(job.suggested_clips)}")

    stems_npz = Path(job.preview_path).parent / "stems.npz"
    if stems_npz.exists():
        with np.load(stems_npz) as d:
            print(f"  stems.npz keys={list(d.files)} "
                  f"sr={int(d['sr']) if 'sr' in d.files else 'n/a'} "
                  f"({stems_npz.stat().st_size / 1e6:.1f} MB)")

    # cancellation must be cooperative and fast
    job2 = STORE.create_job("upload", source=src)
    job2.cancel_requested = True
    t0 = time.time()
    try:
        ingest.check_cancel(job2)
        print("cancel: NOT honoured (bug)")
    except ingest.JobCancelled:
        print(f"cancel: honoured in {time.time() - t0:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
