"""Content ID pre-flight check (spec §5).

Simulated matching before export:
  * per-second frame-hash similarity of the render vs the original
    (dHash on center-cropped luma)  -> flags unmodified video runs > 7s
  * effective music-level timeline from the audio plan
                                    -> flags unmodified music runs > 5s
  * overall visual similarity score
  * Rule 3 check: at least one transformative element must be applied
  * Fair Use Score 0-100 + one-click fix suggestions
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .config import (
    RULE1_MAX_UNMODIFIED_VIDEO_S,
    RULE2_MAX_MUSIC_S,
    RULE2_MAX_MUSIC_VOLUME,
)
from .engine import iter_frames
from .templates import TEMPLATES


def _dhash(gray8: np.ndarray) -> np.ndarray:
    g = gray8.astype(np.int32)
    diff = g[:, 1:] > g[:, :-1]
    return diff.flatten().astype(np.uint8)


def _hash_similar(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    return 1.0 - float(np.count_nonzero(a != b)) / a.size


def _center_crop_916(gray: np.ndarray, size: int = 32) -> np.ndarray:
    H, W = gray.shape
    h = H
    w = int(h * 9 / 16)
    if w > W:
        w = W
        h = int(w * 16 / 9)
    x0 = (W - w) // 2
    y0 = (H - h) // 2
    crop = gray[y0:y0 + h, x0:x0 + w]
    from PIL import Image
    return np.asarray(Image.fromarray(crop).resize((size, size), Image.BILINEAR))


def frame_similarity_timeline(
    out_path: str, src_path: str, t0: float, t1: float, fps_sample: float = 1.5
) -> List[float]:
    """Per-second similarity between the rendered output and the original."""
    D = t1 - t0
    n = max(1, int(D * fps_sample))
    # pre-scan source frames into a small cache at the needed times
    target_times = [t0 + k / fps_sample for k in range(n)]
    src_hashes: Dict[int, np.ndarray] = {}
    for idx, tt in enumerate(target_times):
        for t, img in iter_frames(src_path, start=max(0, tt - 0.4),
                                  end=tt + 0.1, max_dim=256):
            g = np.mean(img, axis=2).astype(np.uint8)
            src_hashes[idx] = _dhash(_center_crop_916(g))
            break
    out_hashes: List[Optional[np.ndarray]] = [None] * n
    # stream the output once
    for t, img in iter_frames(out_path, start=0.0, end=D, max_dim=256):
        k = min(n - 1, int(t * fps_sample))
        if out_hashes[k] is None:
            g = np.mean(img, axis=2).astype(np.uint8)
            out_hashes[k] = _dhash(_center_crop_916(g))
    sims: List[float] = []
    for idx in range(n):
        oh, sh = out_hashes[idx], src_hashes.get(idx)
        sims.append(_hash_similar(oh, sh) if oh is not None and sh is not None else 0.0)
    # bucket to 1s
    per_s: List[float] = []
    for s in range(int(np.ceil(D))):
        a = sims[s * int(fps_sample):(s + 1) * int(fps_sample)]
        per_s.append(float(np.mean(a)) if a else 0.0)
    return per_s


def _flag_runs(values: List[float], thr: float, min_len_s: float,
               dt: float = 1.0) -> List[Tuple[float, float]]:
    runs = []
    i = 0
    n = len(values)
    while i < n:
        if values[i] > thr:
            j = i
            while j < n and values[j] > thr:
                j += 1
            if (j - i) * dt >= min_len_s:
                runs.append((round(i * dt, 1), round(j * dt, 1)))
            i = j
        else:
            i += 1
    return runs


def check_render(
    render,  # Render object
    per_second_sim: List[float],
) -> Dict[str, Any]:
    """Build the preflight result for a finished render."""
    pf: Dict[str, Any] = {
        "score": 100,
        "avg_similarity": 0.0,
        "warnings": [],
        "rules": {},
        "fixes": [],
    }
    D = render.duration
    sim = per_second_sim[:max(1, int(np.ceil(D)))]
    pf["avg_similarity"] = round(float(np.mean(sim)) if sim else 0.0, 3)
    pf["similarity_timeline"] = [round(v, 3) for v in sim]

    # RULE 1: unmodified video runs > 7s (similarity > 0.82 ~ untransformed)
    video_runs = _flag_runs(sim, 0.82, RULE1_MAX_UNMODIFIED_VIDEO_S)
    pf["rules"]["rule1_unmodified_video"] = {
        "violations": video_runs,
        "pass": not video_runs,
    }
    for (a, b) in video_runs:
        pf["warnings"].append({
            "id": f"vid-{a:.0f}-{b:.0f}",
            "type": "video_stretch",
            "msg": f"⚠️ Seconds {a:.0f}–{b:.0f}: unmodified visual segment > {RULE1_MAX_UNMODIFIED_VIDEO_S:.0f}s",
            "fix": {"action": "microcut", "label": "Insert extra micro-cuts"},
        })
        pf["fixes"].append({"warning": f"vid-{a:.0f}-{b:.0f}",
                            "options": {"force_microcut_every": 4.0}})

    # RULE 2: unmodified music > 5s at >25% volume
    plan = render.audio_plan or {}
    eff = np.asarray(plan.get("music_eff_env") or [], dtype=np.float32)
    music_runs: List[Tuple[float, float]] = []
    if eff.size > 10:
        # resample eff (50ms) to 1s
        n_s = int(np.ceil(D))
        sim2 = np.interp(np.arange(n_s) + 0.5,
                         np.arange(eff.size) * 0.05, eff)
        music_runs = _flag_runs(list(sim2), RULE2_MAX_MUSIC_VOLUME, RULE2_MAX_MUSIC_S)
    pf["rules"]["rule2_unmodified_music"] = {
        "violations": music_runs,
        "pass": not music_runs,
        "music_mode": plan.get("music_mode", "unknown"),
    }
    for (a, b) in music_runs:
        pf["warnings"].append({
            "id": f"mus-{a:.0f}-{b:.0f}",
            "type": "music_stretch",
            "msg": f"⚠️ Seconds {a:.0f}–{b:.0f}: music above 25% for > {RULE2_MAX_MUSIC_S:.0f}s",
            "fix": {"action": "duck", "label": "Duck music to 18%"},
        })
        pf["fixes"].append({"warning": f"mus-{a:.0f}-{b:.0f}",
                            "options": {"audio": {"music": {"mode": "duck", "gain": 0.5}}}})

    # overall similarity
    if pf["avg_similarity"] > 0.7:
        pf["warnings"].append({
            "id": "sim-high",
            "type": "similarity",
            "msg": f"⚠️ Overall visual similarity {pf['avg_similarity']:.0%} — higher than ideal",
            "fix": {"action": "grade", "label": "Add color grade + grain"},
        })
        pf["fixes"].append({"warning": "sim-high",
                            "options": {"grade": "warm", "extra_grain": 3.0}})

    # RULE 3: at least one transformative element
    tpl = TEMPLATES.get(render.template, {})
    elements = tpl.get("elements", [])
    has_captions = bool(elements and "captions" in elements)
    pf["rules"]["rule3_transformative"] = {"elements": elements, "pass": len(elements) > 0}
    if not elements:
        pf["warnings"].append({
            "id": "no-transform", "type": "transform",
            "msg": "⚠️ No transformative elements applied — Rule 3 not met",
            "fix": {"action": "template", "label": "Switch to Caption Storm"},
        })

    # RULE 4: aspect transform (always true in FairClip — output is 9:16)
    pf["rules"]["rule4_aspect_9_16"] = {"pass": True}
    # RULE 5: watermark option present
    pf["rules"]["rule5_watermark_option"] = {
        "watermark_on": bool(render.options.get("watermark", True)),
        "disclaimer_on": bool(render.options.get("disclaimer", False)),
    }

    # score
    score = 100
    score -= 18 * min(3, len(video_runs))
    score -= 15 * min(3, len(music_runs))
    if pf["avg_similarity"] > 0.7:
        score -= 10
    if not elements:
        score -= 20
    pf["score"] = int(max(0, min(100, score)))
    pf["verdict"] = (
        "Strong Fair Use posture" if score >= 80 else
        "Moderate — apply the suggested fixes" if score >= 55 else
        "Weak — apply the fixes before exporting"
    )
    return pf
