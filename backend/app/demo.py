"""Demo scene generator.

Produces a 100-second synthetic "cinematic scene" (1280x720, letterboxed)
entirely inside the sandbox: procedural frames (numpy + Pillow), real speech
via the vendored meSpeak TTS bridge, synthesized score + SFX. Ships with a
ground-truth transcript so captions/demo work with zero external services.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import DATA_DIR
from .engine import mux_output
from .tts import synthesize

W, H = 1280, 720
FPS = 30
DUR = 100.0
BAR = 54                      # letterbox bars
CW, CH = W, H - 2 * BAR       # content area


LINES = [
    # (t_start, voice, variant, text)
    (0.8, "story", "m3", "I told them the reactor was stable. I was wrong."),
    (5.4, "energetic", "f2", "Wrong isn't even close, Daniel. It was a countdown."),
    (11.0, "story", "m3", "We had ninety seconds. Maybe less."),
    (27.0, "energetic", "f2", "So why did you lock the doors?"),
    (37.0, "story", "m3", "Because what's inside isn't supposed to come out."),
    (55.0, "energetic", "f2", "Then let's hope it's still in there."),
]

SHOTS = [
    (0, 10, "two"), (10, 18, "closeA"), (18, 26, "flash"), (26, 36, "closeB"),
    (36, 46, "two"), (46, 54, "action"), (54, 64, "closeA"), (64, 74, "two"),
    (74, 84, "reveal"), (84, 100, "wide"),
]


# ---------------- audio synth -------------------------------------------------

def _chord_pad(sr: int, dur: float, chords: List[Tuple[float, float, float]],
               intensity_curve) -> np.ndarray:
    """Warm pad: root + 5th + octave, slow attack, LFO movement."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    out = np.zeros(n, dtype=np.float32)
    for root, fifth, octv in chords:
        for f, amp in ((root, 0.30), (root * 1.5, 0.16), (root * 2.0, 0.10),
                       (root / 2.0, 0.12)):
            vib = 1.0 + 0.003 * np.sin(2 * np.pi * 0.13 * t + f)
            out += amp * np.sin(2 * np.pi * f * vib * t)
    # slow swell
    out *= 0.65 + 0.35 * np.sin(2 * np.pi * t / 17 + 1.0)
    # intensity envelope per second
    env = np.array([intensity_curve(s) for s in np.arange(0, dur, 1.0 / sr)],
                   dtype=np.float32)
    k = int(0.4 * sr)
    env = np.convolve(env, np.hanning(k) / k, mode="same")[:n]
    out *= env
    return out


def _whoosh(sr: int, dur: float = 0.5) -> np.ndarray:
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.default_rng(11)
    noise = rng.normal(0, 1, n).astype(np.float32)
    # band sweep 300 -> 3000 Hz (crude: amplitude-weighted high-freq noise)
    hp = np.zeros(n, dtype=np.float32)
    x = noise.copy()
    for _ in range(6):
        hp += np.diff(x, prepend=0)
        x = np.diff(x, prepend=0)
    hp = hp / (np.max(np.abs(hp)) + 1e-9)
    g = np.hanning(n)
    sweep = np.linspace(0.3, 1.0, n) ** 2
    return (hp * g * sweep * 0.5).astype(np.float32)


def _boom(sr: int, dur: float = 1.4) -> np.ndarray:
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = 55 * np.exp(-t * 1.2) + 32
    sig = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 2.2)
    return (sig * 0.7).astype(np.float32)


def _hit(sr: int, dur: float = 0.18) -> np.ndarray:
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.default_rng(23)
    return (rng.normal(0, 1, n).astype(np.float32)
            * np.exp(-t * 40) * 0.6).astype(np.float32)


# ---------------- frame synth --------------------------------------------------

def _grad(w: int, h: int, c_top, c_bot, glow_xy=(0.5, 0.42), glow_c=(0.5, 0.3, 0.15),
          glow_r=0.55) -> np.ndarray:
    yy = np.linspace(0, 1, h)[:, None]
    xx = np.linspace(0, 1, w)[None, :]
    base = np.stack([
        c_top[0] + (c_bot[0] - c_top[0]) * yy,
        c_top[1] + (c_bot[1] - c_top[1]) * yy,
        c_top[2] + (c_bot[2] - c_top[2]) * yy,
    ], axis=2)
    d = np.sqrt((xx - glow_xy[0]) ** 2 + ((yy - glow_xy[1]) * h / w) ** 2)
    glow = np.exp(-(d / glow_r) ** 2 * 2.2)[:, :, None] * np.array(glow_c)[None, None, :]
    out = np.clip(base + glow * 0.5, 0, 1)
    return (out * 255).astype(np.uint8)


def _person(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float,
            bob: float, color) -> None:
    # simple cinematic silhouette: head + shoulders
    r = s * 0.16
    draw.ellipse([cx - r, cy - r - s * 0.42 + bob, cx + r, cy + r - s * 0.42 + bob],
                 fill=color)
    draw.pieslice([cx - s * 0.42, cy - s * 0.16 + bob, cx + s * 0.42, cy + s * 0.72 + bob],
                  start=180, end=360, fill=color)
    draw.rectangle([cx - s * 0.42, cy + s * 0.28 + bob, cx + s * 0.42, cy + s * 1.4],
                   fill=color)


def _shot_frame(kind: str, t: float, ts: float, rng) -> np.ndarray:
    """ts = time within shot. Returns (CW, CH, 3) RGB."""
    if kind == "two":
        g = _grad(CW, CH, (0.16, 0.09, 0.14), (0.05, 0.03, 0.07),
                  glow_c=(0.45, 0.22, 0.10))
        img = Image.fromarray(g)
        d = ImageDraw.Draw(img)
        bob = math.sin(ts * 1.4) * 4
        _person(d, CW * 0.36, CH * 0.42, CH * 0.40, bob, (14, 10, 16))
        _person(d, CW * 0.64, CH * 0.44, CH * 0.36, -bob, (18, 12, 20))
        img = img.filter(ImageFilter.GaussianBlur(1.1))
        return np.asarray(img)
    if kind in ("closeA", "closeB"):
        warm = kind == "closeA"
        g = _grad(CW, CH, (0.20 if warm else 0.07, 0.10 if warm else 0.10,
                           0.10 if warm else 0.16), (0.05, 0.03, 0.05),
                  glow_c=(0.5, 0.25, 0.1) if warm else (0.1, 0.2, 0.45),
                  glow_r=0.7)
        img = Image.fromarray(g)
        d = ImageDraw.Draw(img)
        bob = math.sin(ts * 1.1) * 3
        x = CW * (0.46 if warm else 0.54)
        _person(d, x, CH * 0.30, CH * 0.62, bob, (12, 9, 14))
        img = img.filter(ImageFilter.GaussianBlur(1.4))
        return np.asarray(img)
    if kind == "flash":
        g = _grad(CW, CH, (0.30, 0.14, 0.20), (0.10, 0.04, 0.10),
                  glow_c=(0.8, 0.3, 0.2), glow_r=0.8)
        img = Image.fromarray(g)
        d = ImageDraw.Draw(img)
        for k in range(7):
            px = ((ts * (0.3 + 0.08 * k) + 0.13 * k) % 1.1 - 0.05) * CW
            py = CH * (0.2 + 0.1 * k)
            alpha = int(120 * (1 - abs((px % CW) - CW * 0.5) / (CW * 0.6)))
            d.line([px - 90, py, px + 90, py + 8], fill=(255, 180, 120, 0), width=3)
            d.line([px - 90, py, px + 90, py + 8],
                   fill=(min(255, 120 + alpha), 90, 60), width=3)
        img = img.filter(ImageFilter.GaussianBlur(2.0))
        return np.asarray(img)
    if kind == "action":
        g = _grad(CW, CH, (0.10, 0.05, 0.08), (0.03, 0.02, 0.05),
                  glow_c=(0.5, 0.12, 0.1), glow_r=0.6)
        img = Image.fromarray(g)
        d = ImageDraw.Draw(img)
        shx = math.sin(ts * 23) * 6
        shy = math.cos(ts * 19) * 5
        for k in range(5):
            px = ((ts * (0.5 + 0.1 * k) + 0.2 * k) % 1.2 - 0.1) * CW + shx
            py = CH * (0.25 + 0.12 * k) + shy
            d.polygon([(px, py), (px + 130, py + 26), (px + 40, py + 60)],
                      fill=(200 + 40 * (k % 2), 60, 40))
            d.line([px - 160, py + 30, px, py + 30], fill=(255, 120, 60), width=4)
        img = img.filter(ImageFilter.GaussianBlur(1.2))
        return np.asarray(img)
    if kind == "reveal":
        g = _grad(CW, CH, (0.22, 0.10, 0.22), (0.05, 0.02, 0.08),
                  glow_c=(0.9, 0.5, 0.2), glow_r=0.5 + ts * 0.08)
        img = Image.fromarray(g)
        d = ImageDraw.Draw(img)
        r = 30 + ts * 160
        for k, rr in enumerate((r, r * 0.7, r * 0.45)):
            d.ellipse([CW / 2 - rr, CH / 2 - rr * 0.6, CW / 2 + rr, CH / 2 + rr * 0.6],
                      outline=(255, 200 - 40 * k, 120), width=max(2, 8 - k * 2))
        img = img.filter(ImageFilter.GaussianBlur(1.6))
        return np.asarray(img)
    # wide (pull-back, calm)
    g = _grad(CW, CH, (0.12, 0.08, 0.13), (0.03, 0.02, 0.05),
              glow_c=(0.3, 0.2, 0.25), glow_r=0.9)
    img = Image.fromarray(g)
    d = ImageDraw.Draw(img)
    bob = math.sin(ts * 0.9) * 3
    _person(d, CW * 0.40, CH * 0.50, CH * 0.26, bob, (10, 8, 12))
    _person(d, CW * 0.60, CH * 0.52, CH * 0.24, -bob, (12, 9, 14))
    img = img.filter(ImageFilter.GaussianBlur(1.3))
    return np.asarray(img)


# ---------------- generation ----------------------------------------------------

def ensure_demo(path: str = "") -> Tuple[str, dict]:
    """Generate (or load) the demo video. Returns (path, transcript_dict)."""
    d = DATA_DIR / "demo"
    d.mkdir(parents=True, exist_ok=True)
    out = path or str(d / "demo.mp4")
    meta_path = d / "demo_meta.json"
    if os.path.exists(out) and os.path.exists(meta_path):
        import json
        return out, json.loads(meta_path.read_text())
    import json
    sr = 48000
    rng = np.random.default_rng(42)
    n_frames = int(DUR * FPS)
    tmp = str(d / "demo_build.mp4")

    # 1) synthesize dialogue lines
    line_audios = []
    transcript_words = []
    print("[demo] synthesizing dialogue...", flush=True)
    for t0, voice, variant, text in LINES:
        wav = str(d / f"line_{t0:.1f}.wav")
        if not os.path.exists(wav):
            r = synthesize(text, voice_id=voice, out_path=wav)
            if not r.get("path"):
                raise RuntimeError(f"demo TTS failed: {r.get('error')}")
        from .engine import decode_wav
        x, line_sr = decode_wav(wav)
        x = x.mean(axis=0)
        # resample 22050 -> 48000
        n = int(x.size * sr / line_sr)
        xi = np.arange(n) * (line_sr / sr)
        i = np.clip(np.floor(xi).astype(int), 0, x.size - 2)
        f = (xi - i).astype(np.float32)
        y = x[i] * (1 - f) + x[i + 1] * f
        line_audios.append((t0, y))
        words = [w for w in text.replace("?", " ?").replace(".", " .").split() if w]
        per = (y.size / sr) / max(1, len(words))
        for k, wtxt in enumerate(words):
            wclean = wtxt.strip(".,?")
            if not wclean:
                continue
            transcript_words.append({
                "w": wclean,
                "t0": round(t0 + k * per, 3),
                "t1": round(t0 + (k + 1) * per - 0.03, 3),
            })
    transcript_words.sort(key=lambda w: w["t0"])

    # 2) score + sfx
    print("[demo] synthesizing score + sfx...", flush=True)
    music_n = int(sr * DUR)
    chords = [(110.0, 165.0, 220.0), (87.31, 130.8, 174.6), (130.8, 196.0, 261.6),
              (98.0, 147.0, 196.0), (110.0, 165.0, 220.0)]
    def intensity(t):
        if 18 <= t < 26:
            return 0.85
        if 46 <= t < 54:
            return 0.9
        if 74 <= t < 84:
            return 0.8
        return 0.45
    music = _chord_pad(sr, DUR, chords, intensity)
    music *= 0.55
    audio = np.zeros(music_n, dtype=np.float32)
    audio += music
    for t0, y in line_audios:
        i0 = int(t0 * sr)
        i1 = min(music_n, i0 + y.size)
        audio[i0:i1] += y[: i1 - i0] * 1.15
    for (a, b, kind) in SHOTS:
        if a > 0 and kind in ("closeA", "closeB", "flash", "action", "reveal", "wide"):
            wh = _whoosh(sr, 0.5)
            i0 = int((a - 0.25) * sr)
            audio[i0:i0 + wh.size] += wh
    boom = _boom(sr)
    i0 = int(46.2 * sr)
    audio[i0:i0 + boom.size] += boom
    for th in (60.0, 78.5):
        h = _hit(sr)
        i0 = int(th * sr)
        audio[i0:i0 + h.size] += h
    amb = rng.normal(0, 1, music_n).astype(np.float32)
    k = int(0.2 * sr)
    amb = np.convolve(amb, np.hanning(k) / k, mode="same")[:music_n] * 0.012
    audio += amb
    peak = np.max(np.abs(audio))
    audio = audio / max(1.0, peak) * 0.9
    stereo = np.stack([audio, audio * 0.98], axis=0)

    # 3) frames
    print("[demo] rendering frames...", flush=True)
    # render into a slightly larger virtual canvas for the slow push/pull
    VW, VH = 1408, 792
    grain_cache = [None] * 8

    def gen():
        frame = 0
        for fi in range(n_frames):
            t = fi / FPS
            # find shot
            kind = "two"
            ts = t
            for (a, b, k) in SHOTS:
                if a <= t < b:
                    kind, ts = k, t - a
                    break
            shot = _shot_frame(kind, t, ts, rng)
            # slow zoom: crop from virtual canvas
            if kind in ("two", "wide"):
                z = 1.0 + 0.10 * (ts / 10.0)
            elif kind in ("closeA", "closeB"):
                z = 1.06 + 0.05 * (ts / 9.0)
            elif kind == "reveal":
                z = 1.15
            elif kind == "action":
                z = 1.05
            else:
                z = 1.08
            vw = int(VW / z)
            vh = int(VH / z)
            # shot content -> virtual canvas (centered, top-aligned to content area)
            canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
            x0 = (VW - CW) // 2
            y0 = (VH - CH) // 2
            canvas[y0:y0 + CH, x0:x0 + CW] = shot
            # film grain (temporal, from cached tiles)
            tile_i = fi % 8
            if grain_cache[tile_i] is None:
                n = rng.normal(0, 2.2, (160, 90, 3))
                grain_cache[tile_i] = np.asarray(Image.fromarray(
                    np.clip(n + 128, 0, 255).astype(np.uint8)).resize((VW, VH)))
            canvas = np.clip(canvas.astype(np.int16)
                             + (grain_cache[tile_i].astype(np.int16) - 128), 0, 255)
            canvas = canvas.astype(np.uint8)
            # zoom crop to 16:9 content
            cx = (VW - vw) * (0.5 + 0.05 * math.sin(t * 0.17 + kind_hash(kind)))
            cy = (VH - vh) * 0.5
            x0i = int(np.clip(cx, 0, VW - vw))
            y0i = int(np.clip(cy, 0, VH - vh))
            crop = canvas[y0i:y0i + vh, x0i:x0i + vw]
            from PIL import Image as I
            crop = np.asarray(I.fromarray(crop).resize((CW, CH), I.BILINEAR))
            # letterbox
            out_frame = np.zeros((H, W, 3), dtype=np.uint8)
            out_frame[BAR:BAR + CH] = crop
            yield out_frame
    print("[demo] encoding...", flush=True)
    mux_output(tmp, W, H, FPS, gen(), audio=stereo, audio_sr=sr, crf=21,
               preset="veryfast")
    os.replace(tmp, out)
    meta = {"transcript": {"status": "ready", "engine": "demo-ground-truth",
                           "text": " ".join(l[3] for l in LINES),
                           "words": transcript_words}}
    meta_path.write_text(json.dumps(meta))
    print("[demo] done:", out, flush=True)
    return out, json.loads(meta_path.read_text())


def kind_hash(kind: str) -> float:
    return {"two": 0.0, "closeA": 1.3, "closeB": 2.1, "flash": 3.0,
            "action": 4.2, "reveal": 5.1, "wide": 6.0}.get(kind, 0.0)
