"""Render engine — all 6 Fair Use templates, audio plan, micro-cut enforcement.

Per-frame pipeline (streaming, low memory):
  source frame → geometry (cover-crop/zoom/pan, letterbox strip) →
  template layout (split screen / reaction frame / bookend cards) →
  grade + grain → Pillow overlays (captions, cards, progress, watermark) →
  libx264 encode.  Audio is mixed in numpy from the separated stems and the
  per-template gain plan, so every Fair Use audio rule is exact and auditable.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import numpy as np

from . import captions as CAP
from . import geometry as G
from .config import (
    DISCLAIMER_TEXT,
    MUSIC_DUCK_GAIN,
    RULE1_MAX_UNMODIFIED_VIDEO_S,
    SILENCE_GAP_EVERY_S,
    SILENCE_GAP_LEN_S,
)
from .engine import iter_frames, mux_output
from .stems import SR as STEM_SR   # default rate; files may store their own
from .store import Clip, Job, Render

FPS_AUDIO = 48000


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _audio_at(stem: np.ndarray, t_local: np.ndarray,
              sr: int = STEM_SR) -> np.ndarray:
    """Sample a clip-local stem (mono) at arbitrary local times."""
    if stem is None or stem.size == 0:
        return np.zeros_like(t_local)
    n = stem.size
    t = np.clip(t_local, 0, max(0.0, (n - 1) / sr))
    x = t * sr
    i = np.floor(x).astype(np.int64)
    i = np.clip(i, 0, n - 2)
    f = (x - i).astype(np.float32)
    return stem[i] * (1 - f) + stem[i + 1] * f


def _music_gain_env(music_env: np.ndarray, mode: str, gain: float,
                    replace: bool = False) -> Tuple[np.ndarray, np.ndarray]:
    """Return (gain per 50ms sample, runs) for the music layer."""
    n = len(music_env)
    dt = 0.05
    t = np.arange(n) * dt
    gain_env = np.full(n, gain, dtype=np.float32)
    runs: List[Tuple[float, float]] = []
    if mode == "mute":
        gain_env[:] = 0.0
        return gain_env, runs
    if mode == "duck":
        gain_env[:] = MUSIC_DUCK_GAIN * (gain / max(0.01, 0.5))
        runs = [(0.0, float(n * dt))]
        return gain_env, runs
    if mode == "silence_gaps":
        for s in np.arange(0, n * dt, SILENCE_GAP_EVERY_S):
            i0 = int(s / dt)
            i1 = min(n, int((s + SILENCE_GAP_LEN_S) / dt))
            gain_env[i0:i1] = 0.0
        runs = [(0.0, float(n * dt))]
        return gain_env, runs
    if mode == "replace":
        gain_env[:] = 0.45
        return gain_env, [(0.0, float(n * dt))]
    # auto: duck stretches of continuous music (>5s above threshold) to 18%
    thr = 0.02
    active = np.asarray(music_env) > thr
    if not active.any():
        return gain_env, runs
    i = 0
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            if (j - i) * dt > 5.0:
                runs.append((round(i * dt, 2), round(j * dt, 2)))
                gain_env[i:j] = MUSIC_DUCK_GAIN
            i = j
        else:
            i += 1
    # 100ms smoothing
    k = max(1, int(0.1 / dt))
    kern = np.ones(k) / k
    gain_env = np.convolve(gain_env, kern, mode="same").astype(np.float32)
    return gain_env, runs


def hook_pick_times(t0: float, D: float) -> List[float]:
    return [t0 + 0.4, t0 + D * 0.30, t0 + D * 0.62, t0 + D - 0.6]


def _build_time_map(plan: Dict[str, Any]) -> np.ndarray:
    """Absolute source time for each output frame (identity + T5 speed ramp
    + T6 bookend fast-cut intro)."""
    D = plan["D"]
    fps = plan["fps"]
    n = int(D * fps)
    tm = np.arange(n) / fps + plan["t0"]
    if plan.get("bookend_on"):
        intro_len = min(3.0, D / 3)
        plan["intro_len"] = intro_len
        picks = hook_pick_times(plan["t0"], D)
        ni = int(intro_len * fps)
        seg = ni // max(1, len(picks))
        for k in range(len(picks)):
            a = k * seg
            b = ni if k == len(picks) - 1 else (k + 1) * seg
            tm[a:b] = picks[k]
    ramp = plan.get("speed_ramp_segments")
    if ramp:
        # ramp: list of (t0_local, t1_local) sped up by 1.04x
        out = np.empty(n)
        si = 0
        acc = 0.0
        boundaries = [0.0] + [a for a, b in ramp] + [b for a, b in ramp] + [D]
        # build mapping piecewise: walk local time, compress ramp regions
        pieces = []
        t = 0.0
        for (a, b) in sorted(ramp):
            pieces.append((t, t + (a - t), a, b, 1.0))          # normal
            t = t + (a - t)
            t_end = t + (b - a) / 1.04
            pieces.append((t, t_end, a, b, 1.04))               # ramp
            t = t_end
        pieces.append((t, D, t, D, 1.0))
        for k in range(n):
            t_out = k / fps
            for (ta, tb, sa, sb, rate) in pieces:
                if ta <= t_out <= tb and tb > ta:
                    out[k] = plan["t0"] + sa + (t_out - ta) * rate
                    break
            else:
                out[k] = plan["t0"] + min(t_out, D)
        tm = out
    plan["time_map"] = tm
    return tm


def _non_speech_segments(words: List[Dict[str, float]], D: float,
                         min_gap: float = 0.9) -> List[Tuple[float, float]]:
    """Local time segments with no dialogue (for speed ramps)."""
    if not words:
        return []
    segs = []
    cursor = 0.0
    for w in words:
        s0 = max(0.0, w["t0"] - 0.12)
        s1 = min(D, w["t1"] + 0.12)
        if s0 - cursor >= min_gap:
            segs.append((round(cursor, 2), round(s0, 2)))
        cursor = max(cursor, s1)
    if D - cursor >= min_gap:
        segs.append((round(cursor, 2), round(D, 2)))
    return [(a, b) for a, b in segs if b - a > 0.5]


def _microcut_plan(D: float, fps: int, every: float) -> Tuple[List[int], List[int]]:
    """Frame indices of zoom-pops and flashes so no unmodified run > 7s."""
    pops, flashes = [], []
    t = every
    seed_shift = 0.4
    while t < D - 1.0:
        i = int(t * fps)
        pops.append(i)
        flashes.append(i - 1)
        t += every + seed_shift  # slightly irregular (still < 7s apart)
    return pops, flashes


def _hook_stills(plan: Dict[str, Any]) -> List[Tuple[float, np.ndarray]]:
    """Pre-decode dramatic stills for the bookend intro fast-cuts."""
    D = plan["D"]
    t0 = plan["t0"]
    picks = [t0 + 0.4, t0 + D * 0.30, t0 + D * 0.62, t0 + D - 0.6]
    stills = []
    for pt in picks:
        img = None
        for t, f in iter_frames(plan["source"], start=max(0, pt - 0.3),
                                end=pt + 0.05, max_dim=None):
            img = f
            break
        if img is not None:
            stills.append((pt, img))
    return stills


# ---------------------------------------------------------------------------
# ambient track library (built-in, CC0, procedurally generated & cached)
# ---------------------------------------------------------------------------

_AMBIENT_CACHE: Dict[str, np.ndarray] = {}


def ambient_track(idx: int = 0) -> np.ndarray:
    """Royalty-free ambient bed (procedural, CC0). Returns (n,) mono @48k."""
    if idx in _AMBIENT_CACHE:
        return _AMBIENT_CACHE[idx]
    rng = np.random.default_rng(7 + idx)
    n = int(20 * FPS_AUDIO)
    t = np.arange(n) / FPS_AUDIO
    base = [110.0, 130.8, 146.83][idx % 3]
    out = np.zeros(n, dtype=np.float32)
    for partial, amp in [(1, 0.30), (2, 0.14), (3, 0.07)]:
        f = base * partial
        vib = 1 + 0.004 * np.sin(2 * np.pi * (0.1 + 0.03 * idx) * t + rng.uniform(0, 6))
        out += amp * np.sin(2 * np.pi * f * vib * t)
    # slow movement
    out *= 0.75 + 0.25 * np.sin(2 * np.pi * t / 11 + idx)
    # airy noise wash
    noise = rng.normal(0, 1, n).astype(np.float32)
    k = int(0.08 * FPS_AUDIO)
    kern = np.hanning(k)
    wash = np.convolve(noise, kern / kern.sum(), mode="same")[:n] * 0.015
    out += wash
    out = out / (np.max(np.abs(out)) + 1e-9) * 0.5
    _AMBIENT_CACHE[idx] = out
    return out


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def build_plan(job: Job, clip: Clip, template: str, options: Dict[str, Any],
               store=None) -> Dict[str, Any]:
    from .config import TIERS
    plan: Dict[str, Any] = {
        "template": template,
        "source": job.preview_path or job.source_path,
        "t0": clip.start,
        "D": max(2.0, clip.end - clip.start),
        "fps": int(options.get("fps", 30)),
        "W": int(options.get("width", 720)),
        "H": int(options.get("height", 1280)),
        "mov": bool(options.get("format") == "mov"),
        "crf": int(options.get("crf", 20)),
        "preset": options.get("preset", "veryfast"),
        "bars": (job.letterbox.get("top", 0), job.letterbox.get("bottom", 0)),
        "words": [dict(w) for w in (job.transcript.get("words") or [])],
        "watermark": bool(options.get("watermark", True)),
        "disclaimer": bool(options.get("disclaimer", False)),
        "grade": options.get("grade", "auto"),
        "music_replace": bool(options.get("music_replace", False)),
        "extra_grain": float(options.get("extra_grain", 0.0)),
        "audio_opts": clip.audio,
        "bookend": dict(clip.bookend),
        "tts": {},
        "transform_log": [],
    }
    plan["t1"] = plan["t0"] + plan["D"]
    # local words
    lw = []
    for w in plan["words"]:
        l0 = w["t0"] - plan["t0"]
        l1 = w["t1"] - plan["t0"]
        if l1 > 0 and l0 < plan["D"]:
            lw.append({"w": w["w"], "t0": max(0.0, l0), "t1": min(plan["D"], l1)})
    plan["words"] = lw
    plan["keywords"] = CAP.compute_keywords(lw) if lw else set()

    # stems
    job_dir = os.path.dirname(job.preview_path or job.source_path)
    stems_path = os.path.join(job_dir, "stems.npz")
    if os.path.exists(stems_path):
        data = np.load(stems_path)
        try:                       # separation rate is stored with the file
            stem_sr = int(data["sr"]) if "sr" in data.files else STEM_SR
        except Exception:
            stem_sr = STEM_SR
        t0s = int(plan["t0"] * stem_sr)
        t1s = int(plan["t1"] * stem_sr)
        def _f32(a: np.ndarray) -> np.ndarray:
            return (a.astype(np.float32) / 32767.0) if a.dtype == np.int16 else a

        plan["stems"] = {
            "sr": stem_sr,
            "dialogue": _f32(data["dialogue"][t0s:t1s]),
            "music": _f32(data["music"][t0s:t1s]),
            "sfx": _f32(data["sfx"][t0s:t1s]),
        }
        env = job.stems.get("env", {})
        i0 = int(plan["t0"] / 0.05)
        i1 = int(plan["t1"] / 0.05)
        plan["env"] = {k: (env.get(k) or [])[i0:i1] for k in
                       ("dialogue", "music", "sfx", "rms")}
    else:
        plan["stems"] = None
        plan["env"] = {"dialogue": [], "music": [], "sfx": [], "rms": []}

    # T5 speed ramp
    plan["speed_ramp_segments"] = []
    if template == "minimal_clean" and plan["words"]:
        plan["speed_ramp_segments"] = _non_speech_segments(lw, plan["D"])

    # bookend TTS (only for breakdown_bookend with voice != off)
    be = plan["bookend"]
    plan["bookend_on"] = (
        template == "breakdown_bookend"
        and be.get("enabled")
        and be.get("voice", "off") not in ("off", None, "")
        and plan["D"] >= 12
        and (be.get("intro_text") or be.get("outro_text"))
    )
    if plan["bookend_on"]:
        _load_tts(plan, clip, store)

    _build_time_map(plan)
    from .templates import TEMPLATES
    every = TEMPLATES.get(template, {}).get("microcut_every", 6.0)
    forced = options.get("force_microcut_every")
    if forced:
        every = float(forced)
    pops, flashes = _microcut_plan(plan["D"], plan["fps"], every)
    plan["pop_frames"] = set(pops)
    plan["flash_frames"] = set(flashes)
    for p in pops:
        plan["transform_log"].append([round(p / plan["fps"], 2), "microcut"])
    if plan["bookend_on"]:
        plan["transform_log"].append([0.0, "bookend_intro_card"])
        plan["transform_log"].append([round(plan["D"] - 3.0, 2), "bookend_outro_card"])
    if template == "caption_storm":
        plan["transform_log"].append([0.0, "grade+grain (continuous)"])
    if plan["speed_ramp_segments"]:
        for a, b in plan["speed_ramp_segments"]:
            plan["transform_log"].append([round(a, 2), "speed_ramp"])
    return plan


def _load_tts(plan: Dict[str, Any], clip: Clip, store=None) -> None:
    from .tts import synthesize
    job_dir = os.path.dirname(plan["source"])
    be = plan["bookend"]
    for key, field_name in (("intro", "intro_text"), ("outro", "outro_text")):
        text = (be.get(field_name) or "").strip()
        if not text:
            continue
        out = os.path.join(job_dir, f"tts_{clip.id}_{key}.wav")
        if not os.path.exists(out):
            r = synthesize(text, voice_id=be.get("voice", "deep"), out_path=out,
                           max_seconds=3.0)
            if not r.get("path"):
                plan["bookend_on"] = False
                return
        else:
            r = {"path": out}
        plan["tts"][key] = r
    if not plan["tts"]:
        plan["bookend_on"] = False


def _tts_samples(plan: Dict[str, Any], key: str) -> Optional[np.ndarray]:
    from .engine import decode_wav
    info = plan["tts"].get(key)
    if not info or not info.get("path") or not os.path.exists(info["path"]):
        return None
    x, sr = decode_wav(info["path"])
    x = x.mean(axis=0) if x.shape[0] > 1 else x[0]
    # resample to 48k
    n = int(x.size * FPS_AUDIO / sr)
    xi = np.arange(n) * (sr / FPS_AUDIO)
    i = np.clip(np.floor(xi).astype(int), 0, x.size - 2)
    f = (xi - i).astype(np.float32)
    y = x[i] * (1 - f) + x[i + 1] * f
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.95
    return y.astype(np.float32)


# ---------------------------------------------------------------------------
# audio mix
# ---------------------------------------------------------------------------

def build_audio(plan: Dict[str, Any]) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """Mix the clip audio per template + Fair Use rules.
    Returns (stereo float32 @48k | None, plan_json for preflight)."""
    D = plan["D"]
    N = int(D * FPS_AUDIO)
    t_local = np.arange(N) / FPS_AUDIO
    fps = plan["fps"]
    n_frames = int(D * fps)
    # local source time per audio sample (inverse of the frame time map)
    frame_times = np.arange(n_frames) / fps
    t_map = plan["time_map"] - plan["t0"]
    t_src_local = np.interp(t_local, frame_times, t_map)

    stems = plan["stems"]
    dlg = mus = sfx = None
    if stems is not None:
        ssr = int(stems.get("sr", STEM_SR))
        dlg = _audio_at(stems["dialogue"], t_src_local, ssr)
        mus = _audio_at(stems["music"], t_src_local, ssr)
        sfx = _audio_at(stems["sfx"], t_src_local, ssr)
    else:
        # no separation available: treat the whole track as dialogue, music unknown
        raw = plan.get("raw_mix")
        if raw is not None:
            dlg = _audio_at(raw, t_src_local)

    ao = plan["audio_opts"]
    d_gain = float(ao.get("dialogue", {}).get("gain", 1.0))
    s_gain = float(ao.get("sfx", {}).get("gain", 1.0))
    m_mode = ao.get("music", {}).get("mode", "auto")
    m_gain = float(ao.get("music", {}).get("gain", 0.5))
    if plan.get("music_replace"):
        m_mode = "replace"

    env_m = np.asarray(plan["env"].get("music") or [], dtype=np.float32)
    n_env = max(2, int(D / 0.05))
    env_t = np.arange(len(env_m)) * 0.05 if env_m.size else np.array([0.0, D])
    env_at = (np.interp(np.arange(n_env) * 0.05, env_t, env_m)
              if env_m.size else np.zeros(n_env, dtype=np.float32))
    gain_env, runs = _music_gain_env(env_at, m_mode, m_gain,
                                     replace=plan.get("music_replace", False))
    g_at = np.interp(t_local, np.arange(len(gain_env)) * 0.05, gain_env)

    out = np.zeros(N, dtype=np.float32)
    if dlg is not None:
        out += dlg * d_gain
    if stems is not None and sfx is not None:
        out += sfx * s_gain
    amb = None
    if mus is not None:
        if m_mode == "replace":
            amb = ambient_track(0)
            amb_ext = np.interp(t_local, np.linspace(0, 20, amb.size), amb)
            out += amb_ext * g_at * 1.6
        else:
            out += mus * g_at

    # effective music level (for preflight) at 50ms resolution
    if m_mode == "replace" and amb is not None:
        amb_env = np.interp(np.arange(n_env) * 0.05, np.linspace(0, 20, amb.size), amb)
        eff = np.abs(amb_env) * gain_env * 1.6
    else:
        eff = env_at * gain_env

    # ---- bookend ducking / voice ------------------------------------------
    if plan.get("bookend_on"):
        intro_len = plan.get("intro_len", 3.0)
        outro_len = min(3.0, D / 3)
        i0 = int(intro_len * FPS_AUDIO)
        o0 = int((D - outro_len) * FPS_AUDIO)
        fade = int(0.1 * FPS_AUDIO)
        duck_full = np.ones(N, dtype=np.float32)
        if i0 > 0:
            f0 = min(fade, i0)
            duck_full[0:f0] = np.linspace(1.0, 0.15, f0)
            duck_full[f0:i0] = 0.15
        if o0 < N and o0 > 0:
            of = min(fade, N - o0)
            duck_full[o0:o0 + of] = np.linspace(1.0, 0.2, of)
            duck_full[o0 + of:] = 0.2
        out = out * duck_full
        intro_v = _tts_samples(plan, "intro")
        if intro_v is not None:
            iN = min(intro_v.size, i0)
            out[:iN] += intro_v[:iN] * 1.0
        outro_v = _tts_samples(plan, "outro")
        if outro_v is not None:
            oN = min(outro_v.size, N - o0)
            out[o0:o0 + oN] += outro_v[:oN] * 0.95

    # normalize headroom
    peak = np.max(np.abs(out)) if out.size else 0
    if peak > 0.98:
        out = out * (0.98 / peak)
    stereo = np.stack([out, out], axis=0)
    plan_json = {
        "music_mode": m_mode,
        "music_gain_runs": runs,
        "music_eff_env": [round(float(v), 4) for v in eff],
        "bookend": bool(plan.get("bookend_on")),
        "tts": {k: v.get("duration") for k, v in plan.get("tts", {}).items()},
        "speed_ramp_segments": plan.get("speed_ramp_segments", []),
    }
    return stereo, plan_json


# ---------------------------------------------------------------------------
# frame templates
# ---------------------------------------------------------------------------

def _tpl_plate(plan: Dict[str, Any], img: np.ndarray, t: float, i: int,
               z: float, pan: Tuple[float, float], W: int, H: int) -> np.ndarray:
    pop = 0.035 if i in plan["pop_frames"] else 0.0
    return G.cover_crop_zoom(img, W, H, z + pop, pan,
                             plan["bars"][0], plan["bars"][1])


def _flash(plan: Dict[str, Any], rgb: np.ndarray, i: int) -> np.ndarray:
    if i in plan["flash_frames"]:
        rgb = rgb.astype(np.float32)
        rgb = rgb * 0.92 + np.float32(20)
        return np.clip(rgb, 0, 255).astype(np.uint8)
    return rgb


def _overlays_base(plan: Dict[str, Any], t: float) -> Dict[str, Any]:
    return {
        "t": t,
        "dur": plan["D"],
        "caption_words": plan["words"],
        "keywords": plan["keywords"],
        "watermark": plan["watermark"],
        "disclaimer": plan["disclaimer"],
    }


def frames_cinematic_zoom(plan, img, t, i, W, H):
    z = 1.0 + 0.14 * (t / plan["D"])
    pan = (0.5 + 0.07 * math.sin(2 * math.pi * t / max(1.0, plan["D"])),
           0.5 + 0.05 * math.cos(2 * math.pi * t / max(1.0, plan["D"]) * 0.8))
    plate = _tpl_plate(plan, img, t, i, z, pan, W, H)
    plate = _flash(plan, plate, i)
    ov = _overlays_base(plan, t)
    ov["caption_style"] = "center"
    return CAP.composite_frame(plate, ov)


def frames_split_screen(plan, img, t, i, W, H):
    H_top = int(H * 0.60)
    top = G.cover_crop_zoom(img, W, H_top, 1.10 + (0.04 if i in plan["pop_frames"] else 0.0),
                            top_bar=plan["bars"][0], bottom_bar=plan["bars"][1])
    top = _flash(plan, top, i)
    bottom = G.gradient_bg(W, H - H_top, t)
    # waveform visualizer: 1.2s window centered on t, 28 bars
    env_rms = np.asarray(plan["env"].get("rms") or [], dtype=np.float32)
    bars = []
    if env_rms.size:
        n_bars = 28
        for b in range(n_bars):
            bt = max(0.0, min(plan["D"], t - 0.6 + 1.2 * b / n_bars))
            idx = min(env_rms.size - 1, int(bt / 0.05))
            bars.append(float(env_rms[idx]))
        peak = max(max(bars), 0.02)
        bars = [min(1.0, b / peak) for b in bars]
    out = np.vstack([top, bottom])
    ov = _overlays_base(plan, t)
    ov["caption_style"] = "bottom"
    ov["waveform"] = bars
    ov["waveform_y"] = 0.60 + 0.40 * 0.42
    return CAP.composite_frame(out, ov)


def frames_caption_storm(plan, img, t, i, W, H):
    z = 1.18 + 0.02 * math.sin(t * 0.9)
    plate = _tpl_plate(plan, img, t, i, z, (0.5, 0.5), W, H)
    if plan["grade"] in ("auto", "warm"):
        plate = G.grade_warm(plate, 0.8)
    else:
        plate = G.grade_cool(plate, 0.8)
    plate = G.add_grain(plate, sigma=2.5, seed=i)
    plate = _flash(plan, plate, i)
    ov = _overlays_base(plan, t)
    ov["caption_style"] = "storm"
    return CAP.composite_frame(plate, ov)


def frames_reaction_frame(plan, img, t, i, W, H):
    bg = G.blur_dark(G.cover_crop_zoom(img, W, H, 1.05, top_bar=plan["bars"][0],
                                       bottom_bar=plan["bars"][1]), dark=0.5)
    ww = int(W * 0.70)
    wh = int(ww * 16 / 9)
    z = 1.08 + (0.04 if i in plan["pop_frames"] else 0.0)
    win = G.cover_crop_zoom(img, ww, wh, z, top_bar=plan["bars"][0],
                            bottom_bar=plan["bars"][1])
    out = bg.copy()
    x = (W - ww) // 2
    y = int(H * 0.155)
    mask = G.rounded_mask(ww, wh, int(ww * 0.06))
    G.paste_box(out, win, x, y, mask=mask)
    plate = _flash(plan, out, i)
    ov = _overlays_base(plan, t)
    ov["caption_style"] = "small"
    fact = (plan["bookend"].get("fact") or "").strip()
    if fact:
        ov["card"] = {"kind": "fact", "text": fact}
    ov["progress"] = t / plan["D"]
    return CAP.composite_frame(plate, ov)


def frames_minimal_clean(plan, img, t, i, W, H):
    pan = (0.5 + 0.03 * math.sin(t * 0.25), 0.5)
    plate = _tpl_plate(plan, img, t, i, 1.03, pan, W, H)
    plate = _flash(plan, plate, i)
    ov = _overlays_base(plan, t)
    ov["caption_style"] = "clean"
    return CAP.composite_frame(plate, ov)


def frames_breakdown_bookend(plan, img, t, i, W, H):
    D = plan["D"]
    fps = plan["fps"]
    be = plan["bookend"]
    intro_len = min(3.0, D / 3)
    outro_start = D - min(3.0, D / 3)
    stills: List[Tuple[float, np.ndarray]] = plan.get("hook_stills") or []
    if t < intro_len and stills:
        k = min(len(stills) - 1, int(t / (intro_len / len(stills))))
        s_t, s_img = stills[k]
        z = 1.28 + 0.12 * (k % 2)
        plate = G.cover_crop_zoom(s_img, W, H, z, top_bar=plan["bars"][0],
                                  bottom_bar=plan["bars"][1])
        plate = G.darken_overlay(plate, 0.52)
        hook = (be.get("intro_text") or "").strip()
        lines_txt, fkey, fsize = hook[:64], CAP.F_BOLD, 0.046
        # wrap hook into up to 3 short lines
        words = hook.split()
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if len(trial) > 22 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            lines.append(cur)
        lines = lines[:3]
        card_lines = []
        for ln in lines:
            card_lines.append((ln, CAP.F_BOLD, 0.046, CAP.WHITE))
        card_lines.append(("FAIRCLIP BREAKDOWN", CAP.F_MED, 0.02, CAP.ACCENT))
        ov = _overlays_base(plan, t)
        ov["card"] = {"kind": "intro", "lines": card_lines}
        return CAP.composite_frame(plate, ov)
    if t >= outro_start:
        z = 1.12
        plate = G.cover_crop_zoom(img, W, H, z, top_bar=plan["bars"][0],
                                  bottom_bar=plan["bars"][1])
        plate = G.darken_overlay(plate, 0.6)
        q = (be.get("outro_text") or "What did you think of that scene?").strip()
        words = q.split()
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if len(trial) > 20 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            lines.append(cur)
        lines = lines[:2]
        card_lines = []
        for ln in lines:
            card_lines.append((ln, CAP.F_BOLD, 0.05, CAP.WHITE))
        ov = _overlays_base(plan, t)
        ov["card"] = {"kind": "outro", "lines": card_lines, "handle": "@fairclip"}
        return CAP.composite_frame(plate, ov)
    # middle: raw scene, zoom 10%, dynamic subtitles, dialogue at 100%
    z = 1.10
    plate = _tpl_plate(plan, img, t, i, z, (0.5, 0.5), W, H)
    plate = _flash(plan, plate, i)
    ov = _overlays_base(plan, t)
    ov["caption_style"] = "center"
    return CAP.composite_frame(plate, ov)


TPL_FRAME_FN = {
    "cinematic_zoom": frames_cinematic_zoom,
    "split_screen": frames_split_screen,
    "caption_storm": frames_caption_storm,
    "reaction_frame": frames_reaction_frame,
    "minimal_clean": frames_minimal_clean,
    "breakdown_bookend": frames_breakdown_bookend,
}


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def run_render(plan: Dict[str, Any], out_path: str,
               progress_cb: Optional[Callable[[float, str], None]] = None) -> Tuple[int, float]:
    W, H, fps = plan["W"], plan["H"], plan["fps"]
    n_frames = int(plan["D"] * fps)
    fn = TPL_FRAME_FN[plan["template"]]
    if plan.get("bookend_on"):
        plan["hook_stills"] = _hook_stills(plan)

    DUMMY = np.zeros((2, 2, 3), dtype=np.uint8)
    intro_len = plan.get("intro_len", 0.0)

    def gen():
        hold_img = None
        hold_t = -1e9
        start = max(0.0, plan["t0"] - 0.6)
        if plan.get("bookend_on"):
            # scene stream starts after the intro (intro uses pre-decoded stills)
            start = max(start, plan["t0"] + intro_len - 0.6)
        src = iter_frames(plan["source"], start=start, end=plan["t1"] + 0.6)
        it = iter(src)
        for i in range(n_frames):
            t_out = i / fps
            t_need = float(plan["time_map"][i])
            if plan.get("bookend_on") and t_out < intro_len:
                rgb = fn(plan, DUMMY, t_out, i, W, H)
                yield rgb
                continue
            need_img = True
            while need_img:
                if hold_img is None or hold_t < t_need - 1e-6:
                    try:
                        hold_t, hold_img = next(it)
                    except StopIteration:
                        need_img = False
                        break
                    if hold_t > t_need + 0.4 and hold_t > t_need:
                        need_img = False
                else:
                    need_img = False
            img = hold_img
            if img is None:
                continue
            rgb = fn(plan, img, t_out, i, W, H)
            yield rgb

    audio, plan_json = build_audio(plan)
    plan["audio_plan"] = plan_json

    def vp(n, total):
        if progress_cb:
            progress_cb(min(0.95, n / total * 0.9), "compositing")

    extra_grain = float(plan.get("extra_grain", 0.0))

    def gen_grain():
        if extra_grain <= 0:
            yield from gen()
            return
        gi = 0
        for rgb in gen():
            yield G.add_grain(rgb, sigma=extra_grain, seed=gi)
            gi += 1

    n, dur = mux_output(
        out_path, W, H, fps, gen_grain(), audio=audio, audio_sr=FPS_AUDIO,
        crf=plan["crf"], preset=plan["preset"], mov=plan["mov"],
        progress_cb=vp, total_frames=n_frames,
    )
    if progress_cb:
        progress_cb(1.0, "muxing")
    return n, dur
