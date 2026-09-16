"""Per-frame geometry & compositing helpers (numpy + Pillow).

The renderer streams source frames and, for each output frame, applies:
  - cover-crop to 9:16 with zoom + pan (reframing / Ken Burns / micro-cuts)
  - optional letterbox removal
  - color grade / grain (LUT + noise)
  - layouts: split-screen (T2), reaction frame (T4), bookend cards (T6)
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter, ImageDraw

FONT = __import__("pathlib").Path(__file__).resolve().parent / "assets" / "fonts"


def strip_letterbox(img: np.ndarray, top: int, bottom: int) -> np.ndarray:
    h = img.shape[0]
    t = min(top, h // 3)
    b = min(bottom, h // 3)
    if t or b:
        return img[t:h - b if b else h]
    return img


def cover_crop_zoom(img: np.ndarray, out_w: int, out_h: int, z: float,
                    pan: Tuple[float, float] = (0.5, 0.5),
                    top_bar: int = 0, bottom_bar: int = 0) -> np.ndarray:
    """Center(pan) crop to the output aspect, zoomed by z, resized to out."""
    img = strip_letterbox(img, top_bar, bottom_bar)
    H, W = img.shape[:2]
    target_ratio = out_w / out_h          # 9/16
    h = H / z
    w = h * target_ratio
    if w > W / 1.0:
        w = W
        h = w / target_ratio
    h = min(h, H)
    w = min(w, W)
    cx = pan[0] * (W - w)
    cy = pan[1] * (H - h)
    x0 = int(np.clip(cx, 0, W - w))
    y0 = int(np.clip(cy, 0, H - h))
    crop = img[y0:y0 + int(h), x0:x0 + int(w)]
    pil = Image.fromarray(crop)
    return np.asarray(pil.resize((out_w, out_h), Image.BICUBIC))


def cover_crop_box(img: np.ndarray, box_w: int, box_h: int, z: float = 1.0,
                   top_bar: int = 0, bottom_bar: int = 0) -> np.ndarray:
    """Cover-crop into an arbitrary box (for split-screen top panel)."""
    return cover_crop_zoom(img, box_w, box_h, z, top_bar=top_bar, bottom_bar=bottom_bar)


def grade_warm(rgb: np.ndarray, strength: float = 1.0) -> np.ndarray:
    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)
    r = np.clip(r * (1 + 0.07 * strength) + 4 * strength, 0, 255)
    g = np.clip(g * (1 + 0.01 * strength), 0, 255)
    b = np.clip(b * (1 - 0.09 * strength), 0, 255)
    # slight contrast lift
    out = np.stack([r, g, b], axis=2)
    out = (out - 128) * (1 + 0.04 * strength) + 128
    return np.clip(out, 0, 255).astype(np.uint8)


def grade_cool(rgb: np.ndarray, strength: float = 1.0) -> np.ndarray:
    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)
    r = np.clip(r * (1 - 0.07 * strength), 0, 255)
    g = np.clip(g * (1 + 0.02 * strength), 0, 255)
    b = np.clip(b * (1 + 0.09 * strength) + 3 * strength, 0, 255)
    out = np.stack([r, g, b], axis=2)
    out = (out - 128) * (1 + 0.04 * strength) + 128
    return np.clip(out, 0, 255).astype(np.uint8)


def add_grain(rgb: np.ndarray, sigma: float = 2.5, seed: Optional[int] = None) -> np.ndarray:
    if sigma <= 0:
        return rgb
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma, size=(rgb.shape[0], rgb.shape[1], 3))
    out = rgb.astype(np.float32) + noise
    return np.clip(out, 0, 255).astype(np.uint8)


@lru_cache(maxsize=8)
def rounded_mask(w: int, h: int, radius: int) -> np.ndarray:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return np.asarray(m)


def blur_dark(rgb: np.ndarray, radius: int = 22, dark: float = 0.55,
              half: bool = True) -> np.ndarray:
    """Background blur for reaction-frame template (done at half res for speed)."""
    pil = Image.fromarray(rgb)
    if half:
        pil = pil.resize((pil.width // 2, pil.height // 2), Image.BILINEAR)
        pil = pil.filter(ImageFilter.GaussianBlur(radius // 2))
        pil = pil.resize((rgb.shape[1], rgb.shape[0]), Image.BILINEAR)
    else:
        pil = pil.filter(ImageFilter.GaussianBlur(radius))
    out = np.asarray(pil).astype(np.float32) * dark
    return np.clip(out, 0, 255).astype(np.uint8)


def gradient_bg(w: int, h: int, t: float, phase: float = 0.0) -> np.ndarray:
    """Animated vertical gradient with slow hue drift (T2 bottom panel)."""
    yy = np.linspace(0, 1, h)[:, None]
    drift = 0.5 + 0.5 * np.sin(t * 0.4 + phase)
    c1 = np.array([0.10 + 0.05 * drift, 0.05, 0.22 + 0.10 * (1 - drift)])
    c2 = np.array([0.02, 0.02, 0.06 + 0.04 * drift])
    col = (c1 * (1 - yy) + c2 * yy)  # (h,3)
    out = np.tile(col[None, :, :], (w, 1, 1)).transpose(1, 0, 2)  # (h,w,3)
    xx = np.linspace(0, 1, w)
    sheen = np.exp(-((xx - ((t * 0.07 + phase) % 1.3) - 0.5) ** 2) * 30) * 0.05
    out = out + np.tile(sheen[None, :, None], (h, 1, 1)) * 0.6
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def paste_box(dst: np.ndarray, src: np.ndarray, x: int, y: int,
              mask: Optional[np.ndarray] = None) -> None:
    H, W = dst.shape[:2]
    sh, sw = src.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + sw), min(H, y + sh)
    sx0, sy0 = x0 - x, y0 - y
    sx1, sy1 = sx0 + (x1 - x0), sy0 + (y1 - y0)
    if x1 <= x0 or y1 <= y0:
        return
    if mask is not None:
        m = mask[sy0:sy1, sx0:sx1].astype(np.float32) / 255.0
        region = dst[y0:y1, x0:x1].astype(np.float32)
        dst[y0:y1, x0:x1] = (src[sy0:sy1, sx0:sx1].astype(np.float32) * m[..., None]
                             + region * (1 - m[..., None])).astype(np.uint8)
    else:
        dst[y0:y1, x0:x1] = src[sy0:sy1, sx0:sx1]


def darken_overlay(rgb: np.ndarray, alpha: float) -> np.ndarray:
    out = rgb.astype(np.float32) * (1 - alpha)
    return np.clip(out, 0, 255).astype(np.uint8)
