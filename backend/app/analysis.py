"""Timeline analysis: scenes, letterbox, engagement scoring, waveform."""
from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from .config import ENVELOPE_DT, ENVELOPE_SR, WAVEFORM_BUCKETS
from .engine import _look_for_ffmpeg, iter_frames, decode_audio


def detect_scenes(path: str, max_dim: int = 128, fps: float = 10.0,
                  cancelled: Optional[Callable[[], bool]] = None) -> List[float]:
    """Frame-difference scene boundary detection (PySceneDetect-style).

    With ffmpeg available the whole video is decoded once, scaled to 128px tall
    and emitted as raw grayscale frames at `fps` — decoding a 1-hour video takes
    seconds instead of minutes, and memory stays flat.
    """
    ff, _ = _look_for_ffmpeg()
    if ff:
        try:
            return _detect_scenes_ffmpeg(ff, path, max_dim, fps, cancelled)
        except Exception:
            pass
    return _detect_scenes_pyav(path, max_dim)


def _boundaries_from_diffs(diffs: List[tuple]) -> List[float]:
    """diffs: [(t, mean_abs_frame_difference), ...] -> scene boundary times."""
    if not diffs:
        return []
    vals = np.array([d for _, d in diffs])
    thr = max(14.0, float(np.mean(vals)) * 2.2)
    boundaries: List[float] = []
    for (t, d) in diffs:
        if d > thr and (not boundaries or t - boundaries[-1] > 0.4):
            boundaries.append(round(float(t), 2))
    return boundaries


def _detect_scenes_ffmpeg(ff: str, path: str, max_dim: int, fps: float,
                          cancelled) -> List[float]:
    vf = f"fps={fps},scale=-2:{max_dim},format=gray"
    # Frame size is only knowable after scaling (aspect ratio is preserved), so
    # grab one frame first; then stream the rest without buffering the video.
    try:
        one = subprocess.run(
            [ff, "-nostdin", "-v", "error", "-i", str(path), "-vf", vf,
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, timeout=300).stdout
    except subprocess.TimeoutExpired:
        return _detect_scenes_pyav(path, max_dim)
    if not one or len(one) % max_dim:
        return _detect_scenes_pyav(path, max_dim)
    h = max_dim
    w = len(one) // h
    fsz = w * h

    cmd = [ff, "-nostdin", "-v", "error", "-i", str(path), "-vf", vf,
           "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert p.stdout is not None
    diffs: List[tuple] = []
    prev: Optional[np.ndarray] = None
    buf = bytearray()
    i = 0
    try:
        while True:
            chunk = p.stdout.read(fsz * 32)
            if not chunk:
                break
            buf += chunk
            n = len(buf) // fsz
            for k in range(n):
                frame = np.frombuffer(bytes(buf[k * fsz:(k + 1) * fsz]),
                                      dtype=np.uint8).reshape(h, w)
                if prev is not None:
                    d = float(np.mean(np.abs(frame.astype(np.int16)
                                             - prev.astype(np.int16))))
                    diffs.append((i / fps, d))
                prev = frame
                i += 1
            del buf[:n * fsz]
            if cancelled and cancelled():
                p.kill()
                raise RuntimeError("cancelled")
    finally:
        p.stdout.close()
        p.wait()
    return _boundaries_from_diffs(diffs)


def _detect_scenes_pyav(path: str, max_dim: int) -> List[float]:
    diffs: List[tuple] = []
    prev: Optional[np.ndarray] = None
    for t, img in iter_frames(path, max_dim=max_dim):
        g = np.mean(img, axis=2)
        if prev is not None:
            diffs.append((t, float(np.mean(np.abs(g.astype(np.int16)
                                               - prev.astype(np.int16))))))
        prev = g
    return _boundaries_from_diffs(diffs)


def detect_letterbox(path: str) -> Dict[str, int]:
    """Find top/bottom black bars (for letterbox removal in templates)."""
    for t, img in iter_frames(path, max_dim=640):
        break
    else:
        return {"top": 0, "bottom": 0}
    g = np.mean(img, axis=2)
    Hf = g.shape[0]
    row_mean = g.mean(axis=1)
    row_std = g.std(axis=1)
    limit = Hf // 3

    top = 0
    for i in range(0, limit):
        if row_mean[i] < 10 and row_std[i] < 12:
            top += 1
        else:
            break
    bottom = 0
    for i in range(1, limit + 1):
        j = Hf - i
        if row_mean[j] < 10 and row_std[j] < 12:
            bottom += 1
        else:
            break
    if top > Hf * 0.30:
        top = 0
    if bottom > Hf * 0.30:
        bottom = 0
    return {"top": int(top), "bottom": int(bottom)}


def audio_envelope(path: str, buckets: int = WAVEFORM_BUCKETS,
                   progress_cb: Optional[Callable[[float], None]] = None
                   ) -> Dict[str, List[float]]:
    """Downsampled audio profile for the timeline UI (RMS + low/mid/high bands).

    Runs in blocks: the old version FFT'd the whole track at once, which for an
    hour-long video meant a ~1.5 GB temporary array (swap thrash / OOM). Block
    size is bounded, so memory is flat no matter how long the video is.
    """
    empty = {"rms": [], "low": [], "mid": [], "high": [], "dt": ENVELOPE_DT}
    x, sr = decode_audio(path, sr=ENVELOPE_SR, mono=True)
    if x.size == 0:
        return empty
    x = x[0]
    n_fft = 2048 if sr > 24000 else 1024
    hop = max(64, int(round(0.02 * sr)))      # ~20 ms analysis window
    win = np.hanning(n_fft).astype(np.float32)
    f = np.fft.rfftfreq(n_fft, 1.0 / sr)
    b_low = f < 300
    b_mid = (f >= 300) & (f < 4500)
    b_high = f >= 6000
    block = max(n_fft * 4, int(sr * 120))     # ~2 min of audio per block
    n_blocks = max(1, (len(x) + block - 1) // block)
    lows, mids, highs, rmss = [], [], [], []
    for b in range(n_blocks):
        seg = x[b * block:(b + 1) * block]
        if seg.size < n_fft:
            seg = np.pad(seg, (0, n_fft - seg.size))
        n = 1 + (len(seg) - n_fft) // hop
        idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
        idx = np.minimum(idx, len(seg) - 1)
        spec = np.fft.rfft(seg[idx] * win[None, :], axis=1)
        mag2 = (spec * spec.conj()).real
        lows.append(mag2[:, b_low].sum(axis=1))
        mids.append(mag2[:, b_mid].sum(axis=1))
        highs.append(mag2[:, b_high].sum(axis=1))
        rmss.append(np.sqrt((seg[: n * hop].reshape(n, -1) ** 2).mean(axis=1)))
        if progress_cb:
            progress_cb((b + 1) / n_blocks)
    ep = lambda e: np.sqrt(np.maximum(np.concatenate(e), 0))  # noqa: E731
    low_r, mid_r, high_r = ep(lows), ep(mids), ep(highs)
    rms = np.concatenate(rmss)
    n = len(rms)
    scale = np.max(rms) + 1e-9
    idx2 = (np.linspace(0, 1, buckets) * (n - 1)).astype(int)
    return {
        "rms": (rms[idx2] / scale).round(4).tolist(),
        "low": (low_r[idx2] / scale).round(4).tolist(),
        "mid": (mid_r[idx2] / scale).round(4).tolist(),
        "high": (high_r[idx2] / scale).round(4).tolist(),
        "dt": round(len(x) / sr / buckets, 4),
    }


def suggest_clips(
    job_info: Dict[str, Any],
    envelope: Dict[str, List[float]],
    scenes: List[float],
    transcript: Optional[Dict[str, Any]] = None,
    max_duration: float = 60.0,
    count: int = 8,
) -> List[Dict[str, Any]]:
    """Find the most engaging 15-60s windows.

    Score = dialogue intensity + loudness peaks + transient density +
    scene-transition proximity.
    """
    dur = job_info.get("duration", 0.0)
    if dur < 10:
        return []
    rms = np.array(envelope.get("rms", [0.0]))
    mid = np.array(envelope.get("mid", [0.0]))
    high = np.array(envelope.get("high", [0.0]))
    n = len(rms)
    if n == 0:
        return []
    dt = envelope.get("dt", 0.02)
    t = np.arange(n) * dt

    # speech proxy: mid-band energy (vocal band) — replaced by word rate if transcript
    words = (transcript or {}).get("words", [])
    if words:
        speech_rate = np.zeros(n)
        for w in words:
            i0 = int(w["t0"] / dt)
            i1 = max(i0 + 1, int(w["t1"] / dt))
            speech_rate[i0:i1] += 1.0 / max(1e-3, w["t1"] - w["t0"])
        speech_rate = speech_rate / max(1.0, np.max(speech_rate))
    else:
        speech_rate = mid / (np.max(mid) + 1e-6)

    trans = np.zeros(n)
    trans[1:] = np.clip(rms[1:] - rms[:-1], 0, None)
    trans = trans / (np.max(trans) + 1e-6)
    # smooth
    k = max(1, int(0.4 / dt))
    kern = np.ones(k) / k
    rms_s = np.convolve(rms, kern, mode="same") / (np.max(rms) + 1e-6)
    sp_s = np.convolve(speech_rate, kern, mode="same")
    tr_s = np.convolve(trans, kern, mode="same")

    base = 0.38 * sp_s + 0.30 * rms_s + 0.32 * tr_s

    candidates = []
    lengths = [15, 20, 25, 30, 40, 45, 55, 60]
    lengths = [L for L in lengths if L <= max(15, min(max_duration, dur - 0.5))]
    step = max(1, int(0.75 / dt))
    for L in lengths:
        w = int(L / dt)
        if w >= n:
            continue
        scores = np.convolve(base, np.ones(w) / w, mode="valid")
        for i in range(0, len(scores), step):
            s0 = i * dt
            s1 = s0 + L
            scene_bonus = 0.0
            for sb in scenes:
                if s0 - 1.0 <= sb <= s1 + 1.0:
                    scene_bonus = 0.08
                    break
            peak = float(np.max(rms_s[i:i + w]))
            score = float(scores[i]) + scene_bonus + 0.05 * peak
            candidates.append((score, s0, s1, L))
    candidates.sort(key=lambda c: -c[0])
    chosen: List[Dict[str, Any]] = []
    for score, s0, s1, L in candidates:
        if all(s1 < c["start"] - 0.5 or s0 > c["end"] + 0.5 for c in chosen):
            label = _label(words, s0, s1, L)
            chosen.append({
                "start": round(float(s0), 2), "end": round(float(s1), 2),
                "score": round(float(score), 3), "label": label,
            })
        if len(chosen) >= count:
            break
    chosen.sort(key=lambda c: c["start"])
    for i, c in enumerate(chosen, 1):
        c["id"] = f"sug{i}"
    return chosen


def _label(words: List[Dict[str, Any]], s0: float, s1: float, L: float) -> str:
    if not words:
        return f"Moment ({L:.0f}s)"
    inside = [w["w"] for w in words if s0 <= w["t0"] < s1]
    if not inside:
        return f"Moment ({L:.0f}s)"
    txt = " ".join(inside[:6]).strip()
    if len(txt) > 42:
        txt = txt[:40].rsplit(" ", 1)[0] + "…"
    return txt.title() if txt else f"Moment ({L:.0f}s)"
