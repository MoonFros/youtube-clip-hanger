"""Timeline analysis: scenes, letterbox, engagement scoring, waveform."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from .config import ENVELOPE_DT, WAVEFORM_BUCKETS
from .engine import iter_frames


def detect_scenes(path: str, max_dim: int = 128) -> List[float]:
    """Frame-difference scene boundary detection (PySceneDetect-style)."""
    diffs: List[tuple] = []
    last = None
    for t, img in iter_frames(path, max_dim=max_dim):
        g = np.mean(img, axis=2)
        if last is not None:
            d = float(np.mean(np.abs(g.astype(np.int16) - last.astype(np.int16))))
            diffs.append((t, d))
        last = g
    if not diffs:
        return []
    vals = np.array([d for _, d in diffs])
    thr = max(14.0, float(np.mean(vals)) * 2.2)
    boundaries: List[float] = []
    for (t, d) in diffs:
        if d > thr and (not boundaries or t - boundaries[-1] > 0.4):
            boundaries.append(round(float(t), 2))
    return boundaries


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


def audio_envelope(path: str, buckets: int = WAVEFORM_BUCKETS) -> Dict[str, List[float]]:
    """Downsampled audio profile for the timeline UI (RMS + low/mid/high bands)."""
    from .engine import decode_audio
    x, sr = decode_audio(path, sr=48000, mono=True)
    if x.size == 0:
        return {"rms": [], "low": [], "mid": [], "high": [], "dt": ENVELOPE_DT}
    x = x[0]
    # short STFT band energies (vectorized)
    n_fft, hop = 1024, 960  # ~20ms
    n = 1 + (len(x) - n_fft) // hop
    if n <= 0:
        n = 1
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    idx = np.minimum(idx, len(x) - 1)
    win = np.hanning(n_fft).astype(np.float32)
    spec = np.fft.rfft(x[idx] * win[None, :], axis=1)
    mag2 = (spec * spec.conj()).real
    f = np.fft.rfftfreq(n_fft, 1.0 / sr)
    low = mag2[:, f < 300].sum(axis=1)
    mid = mag2[:, (f >= 300) & (f < 4500)].sum(axis=1)
    high = mag2[:, f >= 6000].sum(axis=1)
    rms = np.sqrt((x[: n * hop].reshape(n, -1) ** 2).mean(axis=1))
    rms = np.sqrt(rms**2)
    band_rms = lambda e: np.sqrt(np.maximum(e, 0))  # noqa: E731
    low_r, mid_r, high_r = band_rms(low), band_rms(mid), band_rms(high)
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
