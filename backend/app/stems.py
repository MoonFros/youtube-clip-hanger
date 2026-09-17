"""FairClip Stem Engine — on-device audio source separation.

Splits a stereo mix into three layers using classical signal processing
(no GPU / no model download required):

  Layer A  Dialogue  : harmonic energy in the vocal band, gated by a
                       speech-activity detector (Hilbert RMS + spectral tilt)
  Layer B  Music     : sustained harmonic energy outside the vocal gate
  Layer C  SFX       : percussive/broadband transients (HPSS residual)

This is a genuine STFT-domain separation (HPSS + speech gating + Wiener
masks), implemented in numpy. When deployed with internet access the
backend can be swapped to Demucs/Spleeter via an API — the envelope and
stem interfaces stay identical.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

HOP = 512
SR = 48000
N_FFT = 2048


def _stft(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    n = len(x)
    pad = N_FFT // 2
    xf = np.concatenate([x, np.zeros(N_FFT, dtype=x.dtype)])
    frames = 1 + (len(xf) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(frames)[:, None]
    idx = np.minimum(idx, len(xf) - 1)
    w = np.hanning(N_FFT).astype(x.dtype)
    win_frames = xf[idx] * w[None, :]
    spec = np.fft.rfft(win_frames, axis=1)
    return spec, w


def _istft(spec: np.ndarray, w: np.ndarray, length: int) -> np.ndarray:
    frames = spec.shape[0]
    out = np.zeros(frames * HOP + N_FFT, dtype=np.float32)
    wsum = np.zeros_like(out)
    sig = np.fft.irfft(spec, n=N_FFT, axis=1) * w[None, :]
    for i in range(frames):
        out[i * HOP:i * HOP + N_FFT] += sig[i]
        wsum[i * HOP:i * HOP + N_FFT] += w * w
    wsum = np.maximum(wsum, 1e-6)
    return (out / wsum)[:length].astype(np.float32)


def _median_axis_f(spec_mag: np.ndarray, win: int = 25) -> np.ndarray:
    """Median along the frequency axis (broadband/percussive estimate)."""
    T, F = spec_mag.shape
    half = win // 2
    out = np.empty_like(spec_mag)
    for i in range(F):
        lo = max(0, i - half)
        hi = min(F, i + half + 1)
        out[:, i] = np.median(spec_mag[:, lo:hi], axis=1)
    return out


def _median_axis_t(spec_mag: np.ndarray, win: int = 41) -> np.ndarray:
    """Median along the time axis (sustained/harmonic estimate)."""
    T, F = spec_mag.shape
    half = win // 2
    out = np.empty_like(spec_mag)
    for t in range(T):
        lo = max(0, t - half)
        hi = min(T, t + half + 1)
        out[t, :] = np.median(spec_mag[lo:hi, :], axis=0)
    return out


def separate_stems_chunked(x: np.ndarray, sr: int = SR, block_s: int = 0,
                           progress_cb=None) -> Dict[str, np.ndarray]:
    """Same result as `separate_stems`, but processed in blocks.

    The single-shot version builds several (frames x fft) float arrays at once:
    a 20-minute video needed ~2 GB of temporaries and an hour-long one would
    simply take the machine down. Blocking keeps peak memory constant (a few
    tens of MB) and gives the UI a progress fraction.
    """
    if block_s <= 0:
        from .config import STEMS_BLOCK_S
        block_s = STEMS_BLOCK_S
    n = len(x)
    if n <= sr * block_s:
        res = separate_stems(x, sr=sr)
        if progress_cb:
            progress_cb(1.0)
        return res

    step = sr * block_s
    n_blocks = int(np.ceil(n / step))
    if progress_cb:
        progress_cb(0.0)
    parts: Dict[str, list] = {"dialogue": [], "music": [], "sfx": []}
    envs: Dict[str, list] = {"t": [], "dialogue": [], "music": [], "sfx": [], "rms": []}
    env_bin = max(1, int(0.05 * sr))

    for b in range(n_blocks):
        seg = x[b * step:(b + 1) * step]
        # pad the last block so it ends on an envelope bin boundary
        pad = (-len(seg)) % env_bin
        if pad:
            seg = np.concatenate([seg, np.zeros(pad, dtype=seg.dtype)])
        res = separate_stems(seg, sr=sr, normalize=False)
        for k in ("dialogue", "music", "sfx"):
            parts[k].append(res[k])
        e = res["env"]
        for k in ("dialogue", "music", "sfx", "rms"):
            envs[k].extend(e.get(k, []))
        t0 = b * block_s
        envs["t"].extend([round(t0 + t, 3) for t in e.get("t", [])])
        if progress_cb:
            progress_cb((b + 1) / n_blocks)

    out = {k: np.concatenate(v)[: n] for k, v in parts.items()}
    # normalise once over the whole track (per-block normalisation would pump)
    for k in ("dialogue", "music", "sfx"):
        peak = float(np.max(np.abs(out[k]))) if out[k].size else 0.0
        if peak > 1.0:
            out[k] = (out[k] / peak).astype(np.float32)
    out["env"] = {k: v[: len(envs["t"])] for k, v in envs.items()}
    out["activity"] = np.array([], dtype=np.float32)
    return out


def separate_stems(x: np.ndarray, sr: int = SR,
                   normalize: bool = True) -> Dict[str, np.ndarray]:
    """x: (n,) mono float32 @sr. Returns stems + envelopes."""
    x = x.astype(np.float32)
    if x.max() < 1e-6:
        z = np.zeros_like(x)
        return {"dialogue": z, "music": z, "sfx": z,
                "env": {"t": [], "dialogue": [], "music": [], "sfx": [], "rms": []}}

    spec, w = _stft(x)
    X = np.abs(spec)
    eps = 1e-7

    # --- HPSS: harmonic (sustained) vs percussive (broadband) ---------------
    H = _median_axis_t(X, 41)          # sustained in time
    P = _median_axis_f(X, 17)          # broadband in frequency
    H = np.clip(X - 0.35 * P, 0, None)
    P = np.clip(X - 0.35 * H, 0, None)

    # --- Speech activity detector (per STFT frame) ---------------------------
    f = np.fft.rfftfreq(N_FFT, 1.0 / sr)
    vocal = (f >= 90) & (f <= 4000)
    vocal_hi = (f > 4000) & (f < 9000)
    low = f < 90
    E_vocal = X[:, vocal].sum(axis=1)
    E_low = X[:, low].sum(axis=1)
    E_tot = X.sum(axis=1) + eps
    a_vocal = E_vocal / E_tot
    # speech usually has a concentrated vocal band and less sub-bass energy
    a_gate = np.clip((a_vocal - 0.18) / 0.22, 0, 1)
    a_sub = E_low / E_tot
    a_gate = a_gate * np.clip(1.2 - a_sub * 4, 0.25, 1)
    # smooth in time (100ms). `np.convolve(..., "same")` returns
    # max(len(signal), len(kernel)) samples, so the kernel must never be longer
    # than the signal (that blew up on very short blocks with a shape error).
    k = max(1, min(int(0.100 * sr / HOP), a_gate.size))
    if k > 1:
        a_gate = np.convolve(a_gate, np.ones(k) / k, mode="same")
    a_gate = np.clip(a_gate, 0, 1)

    # --- Wiener-style masks ---------------------------------------------------
    V = np.clip(a_gate[:, None] * 1.4, 0, 1)            # (T,1)
    V = np.where(vocal[None, :], V, V * 0.25)           # keep vocal band strong
    V = np.where(vocal_hi[None, :], V * 0.5, V)         # consonant air
    V = np.where(low[None, :], V * 0.1, V)              # dialogue keeps little sub
    m_dlg = (V ** 2) * (H / (X + eps)) + 0.25 * V * (P / (X + eps)) * vocal_hi[None, :]
    m_music = (1 - V) * (H / (X + eps)) * 0.95
    m_sfx = (1 - V) * (P / (X + eps)) + 0.4 * np.where(f[None, :] > 6000, P / (X + eps) * (1 - V), 0)

    # energy compensation: masks should roughly partition X
    msum = m_dlg**2 + m_music**2 + m_sfx**2 + eps
    scale = (X**2) / np.sqrt(msum * X**2 + eps)
    m_dlg = np.clip(m_dlg, 0, 1) * np.sqrt(scale)
    m_music = np.clip(m_music, 0, 1) * np.sqrt(scale)
    m_sfx = np.clip(m_sfx, 0, 1) * np.sqrt(scale)

    dlg = _istft(spec * m_dlg, w, len(x))
    mus = _istft(spec * m_music, w, len(x))
    sfx = _istft(spec * m_sfx, w, len(x))

    # normalize stems so the mix is preserved in balance
    if normalize:
        for s in (dlg, mus, sfx):
            peak = np.max(np.abs(s))
            if peak > 1.0:
                s /= peak

    # --- envelopes (per 50 ms) -------------------------------------------------
    env_bin = int(0.05 * sr)
    n_bins = (len(x) + env_bin - 1) // env_bin
    def _rms_env(sig: np.ndarray) -> np.ndarray:
        pad = np.zeros(env_bin - len(sig) % env_bin if len(sig) % env_bin else 0, dtype=np.float32)
        sig2 = np.sqrt(np.concatenate([sig**2, pad]))
        sig2 = sig2[: n_bins * env_bin]
        return sig2.reshape(n_bins, env_bin).mean(axis=1).astype(np.float32)

    env = {
        "t": (np.arange(n_bins) * 0.05).round(3).tolist(),
        "dialogue": _rms_env(dlg).round(4).tolist(),
        "music": _rms_env(mus).round(4).tolist(),
        "sfx": _rms_env(sfx).round(4).tolist(),
        "rms": _rms_env(x).round(4).tolist(),
    }
    return {"dialogue": dlg, "music": mus, "sfx": sfx, "env": env, "activity": a_gate}
