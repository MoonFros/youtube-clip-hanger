"""Pillow-based caption + overlay renderer.

No drawtext in the PyAV wheel, so ALL text overlays (word-by-word captions,
hook cards, progress bars, watermarks, disclaimers) are rendered per-frame in
Pillow and composited onto the frame. This gives full control over
Hormozi-style bounce/scale pop-ins, keyword highlighting, drop shadows etc.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import DISCLAIMER_TEXT, FONTS

ACCENT = (139, 92, 246)      # violet
ACCENT2 = (34, 211, 238)     # cyan
YELLOW = (250, 204, 21)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


@lru_cache(maxsize=64)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = str(FONTS / name)
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


F_DISPLAY = "ArchivoBlack_400Regular.ttf"
F_BOLD = "Inter_900Black.ttf"
F_SEMI = "Inter_800ExtraBold.ttf"
F_MED = "Inter_600SemiBold.ttf"
F_ROBO = "Roboto_700Bold.ttf"
F_ROBO_M = "Roboto_500Medium.ttf"


def _ease_out_back(x: float) -> float:
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _ease_out_cubic(x: float) -> float:
    return 1 - (1 - x) ** 3


def find_active_words(words: List[Dict[str, float]], t: float,
                      window_after: float = 0.0) -> List[Tuple[int, float, float, float]]:
    """[(index, t0, t1, progress)] for words active at time t."""
    out = []
    for i, w in enumerate(words):
        if w["t0"] <= t < w["t1"] + window_after:
            p = min(1.0, max(0.0, (t - w["t0"]) / max(0.05, w["t1"] - w["t0"])))
            out.append((i, w["t0"], w["t1"], p))
    return out


def compute_keywords(words: List[Dict[str, float]]) -> set:
    """Pick words to highlight (punctuation words, long words, top frequency)."""
    if not words:
        return set()
    text_words = [w["w"].strip(" .,!?;:'\"()") for w in words]
    punct = {w for w in text_words if any(c in w for c in "!?")}
    freq: Dict[str, int] = {}
    for w in text_words:
        if len(w) > 3:
            freq[w.lower()] = freq.get(w.lower(), 0) + 1
    top = sorted(freq.items(), key=lambda kv: -kv[1])[:6]
    kws = {w.lower() for w, c in top if c >= 2} | {w.lower() for w in punct}
    long_words = {w.lower() for w in text_words if len(w) >= 8}
    return kws | set(list(long_words)[:10])


_BBOX_CACHE: Dict[Tuple[str, int], Tuple[int, int, int, int]] = {}


def _bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    key = (font.path, font.size, text)
    bb = _BBOX_CACHE.get(key)
    if bb is None:
        bb = draw.textbbox((0, 0), text, font=font)
        if len(_BBOX_CACHE) > 8000:
            _BBOX_CACHE.clear()
        _BBOX_CACHE[key] = bb
    return bb


def _dim(c: tuple, alpha: int) -> tuple:
    """Approximate alpha by dimming toward black (drawn on RGB canvas)."""
    if alpha >= 250:
        return c
    a = alpha / 255.0
    return (int(c[0] * a), int(c[1] * a), int(c[2] * a))


def _draw_word(draw: ImageDraw.ImageDraw, cx: int, cy: int, text: str,
               font: ImageFont.FreeTypeFont, fill: tuple,
               shadow: bool = True, scale: float = 1.0, alpha: int = 255) -> None:
    if scale != 1.0:
        font = _font(font.path.split("/")[-1], max(8, int(font.size * scale)))
    bbox = _bbox(draw, text, font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]
    if shadow:
        draw.text((x + max(2, tw // 28), y + max(2, th // 28)), text, font=font,
                  fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=_dim(fill, alpha))


def render_word_block(draw: ImageDraw.ImageDraw, W: int, H: int,
                      words: List[Dict[str, float]], t: float,
                      style: str, keywords: set,
                      font_key: str = F_BOLD, base_size: int = 54) -> int:
    """Draw up to 3 active words for the given style. Returns n_drawn."""
    active = find_active_words(words, t)
    if not active:
        return 0
    # group into words currently visible (keep last 3)
    shown = active[-3:]
    txts = [words[i]["w"] for i, *_ in shown]
    t_first = shown[0][1]
    p_in = _ease_out_cubic(min(1.0, (t - t_first) / 0.18))

    n = len(txts)
    if n == 1:
        size = base_size * (1.35 - 0.35 * p_in) if style == "storm" else base_size
    else:
        size = base_size
    font = _font(font_key, int(size))
    gap = int(size * 0.32)
    widths = []
    for i, txt in enumerate(txts):
        f = _font(font_key, int(size))
        bb = _bbox(draw, txt, f)
        widths.append(bb[2] - bb[0])
    total = sum(widths) + gap * (n - 1)
    if total > W * 0.92:
        size = int(size * (W * 0.92) / total)
        font = _font(font_key, size)
        gap = int(size * 0.32)
        widths = []
        for i, txt in enumerate(txts):
            f = _font(font_key, size)
            bb = _bbox(draw, txt, f)
            widths.append(bb[2] - bb[0])
        total = sum(widths) + gap * (n - 1)

    if style == "center":
        cy = H * 0.78
    elif style == "bottom":
        cy = H * 0.885
    elif style == "small":
        cy = H * 0.905
    elif style == "clean":
        cy = H * 0.82
    else:  # storm
        cy = H * 0.52

    x = W / 2 - total / 2
    for i, txt in enumerate(txts):
        wtxt = txt.strip(" .,!?;:'\"")
        is_kw = wtxt.lower() in keywords or any(c in txt for c in "!?")
        if style == "storm":
            scale = 1.0 + 0.5 * (1 - _ease_out_back(min(1.0, (t - shown[i][1]) / 0.22)))
            fill = YELLOW if is_kw else WHITE
            _draw_word(draw, x + widths[i] / 2, cy, txt, _font(font_key, int(size)),
                       fill, scale=scale)
        else:
            fill = ACCENT2 if (is_kw and style == "clean") else WHITE
            _draw_word(draw, x + widths[i] / 2, cy, txt, font, fill,
                       alpha=int(120 + 135 * p_in))
        x += widths[i] + gap
    return len(txts)


# ---------------- full-frame overlay compositors -----------------------------

def composite_frame(frame_rgb: np.ndarray, overlays: Dict[str, Any]) -> np.ndarray:
    """Overlay captions/cards/graphics onto a frame (direct RGB drawing for speed).

    overlay dict may contain: {'caption_words':..., 'caption_style':..., 'keywords':...,
    'card': {'kind':'intro'|'outro'|'fact', ...}, 'progress': 0..1,
    'watermark': True, 'disclaimer': True, 'waveform': [bars 0..1], 'waveform_y': 0..1}
    """
    H, W = frame_rgb.shape[:2]
    img = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(img)
    words = overlays.get("caption_words") or []
    style = overlays.get("caption_style", "center")
    t = overlays.get("t", 0.0)
    if words:
        render_word_block(draw, W, H, words, t, style,
                          overlays.get("keywords", set()),
                          base_size=int(H * 0.052))
    card = overlays.get("card")
    if card:
        _draw_card(draw, W, H, t, card, overlays.get("dur", 1.0))
    if overlays.get("progress") is not None:
        _draw_progress(draw, W, H, overlays["progress"])
    if overlays.get("watermark"):
        _draw_watermark(draw, W, H)
    if overlays.get("disclaimer"):
        _draw_disclaimer(draw, W, H)
    wf = overlays.get("waveform")
    if wf:
        _draw_waveform(draw, W, H, wf, overlays.get("waveform_y", 0.86))
    return np.asarray(img)


def _draw_card(draw: ImageDraw.ImageDraw, W: int, H: int, t: float,
               card: Dict[str, str], dur: float) -> None:
    kind = card.get("kind")
    if kind == "fact":
        # top context card (Template 4)
        text = card.get("text", "")
        if not text:
            return
        p_in = _ease_out_cubic(min(1.0, t / 0.5))
        p_out = min(1.0, max(0.0, (t - 4.2) / 0.6))
        alpha = int(235 * p_in * (1 - p_out))
        if alpha <= 0:
            return
        font = _font(F_SEMI, int(H * 0.030))
        prefix = "DID YOU KNOW?  "
        pfont = _font(F_BOLD, int(H * 0.026))
        line = prefix + text
        words_l = line.split()
        lines, cur = [], ""
        for wd in words_l:
            trial = (cur + " " + wd).strip()
            bb = _bbox(draw, trial, font)
            if bb[2] - bb[0] > W * 0.82 and cur:
                lines.append(cur)
                cur = wd
            else:
                cur = trial
        if cur:
            lines.append(cur)
        lines = lines[:2]
        y0 = H * 0.055 - (1 - p_in) * H * 0.02
        lh = int(H * 0.045)
        pad = int(H * 0.018)
        max_w = max(_bbox(draw, l, font)[2] for l in lines)
        box = [(W - max_w) / 2 - pad, y0 - pad, (W + max_w) / 2 + pad,
               y0 + lh * len(lines) + pad]
        draw.rounded_rectangle(box, radius=int(pad * 1.4), fill=(8, 8, 16))
        y = y0
        for i, l in enumerate(lines):
            if i == 0:
                bb = _bbox(draw, l, font)
                tw = bb[2] - bb[0]
                x = (W - tw) / 2
                pbb = _bbox(draw, prefix, pfont)
                draw.text((x, y), prefix, font=pfont, fill=_dim(ACCENT, alpha))
                draw.text((x + (pbb[2] - pbb[0]) + 6, y + 2),
                          l[len(prefix):], font=font, fill=_dim(WHITE, alpha))
            else:
                bb = _bbox(draw, l, font)
                draw.text(((W - (bb[2] - bb[0])) / 2, y), l, font=font,
                          fill=_dim(WHITE, alpha))
            y += lh
        return

    # intro / outro cards (Template 6)
    if kind == "intro":
        p = _ease_out_back(min(1.0, t / 0.35))
    else:
        p = _ease_out_cubic(min(1.0, t / 0.4))
    lines = card.get("lines", [])
    y = H * 0.42
    for i, (text, fkey, fsize, fill) in enumerate(lines):
        font = _font(fkey, int(fsize * H))
        bb = _bbox(draw, text, font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        scale = 0.8 + 0.2 * p
        if scale != 1.0:
            font = _font(fkey, int(fsize * H * scale))
            bb = _bbox(draw, text, font)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x = W / 2 - tw / 2 - bb[0]
        yy = y - th / 2 - bb[1] + (1 - p) * (H * 0.02) * (1 if kind == "intro" else -1)
        draw.text((x + max(2, tw // 40), yy + max(2, th // 40)), text,
                  font=font, fill=(0, 0, 0))
        draw.text((x, yy), text, font=font, fill=fill)
        y += th * 1.55
    if kind == "outro" and card.get("handle"):
        hfont = _font(F_MED, int(H * 0.026))
        bb = _bbox(draw, card["handle"], hfont)
        tw = bb[2] - bb[0]
        pill_w, pill_h = tw + H * 0.05, H * 0.052
        px, py = W / 2 - pill_w / 2, y + H * 0.01
        draw.rounded_rectangle([px, py, px + pill_w, py + pill_h],
                               radius=pill_h / 2, fill=ACCENT)
        draw.text((W / 2 - tw / 2 - bb[0], py + (pill_h - (bb[3] - bb[1])) / 2 - bb[1]),
                  card["handle"], font=hfont, fill=(10, 10, 18))


def _draw_progress(draw: ImageDraw.ImageDraw, W: int, H: int, p: float) -> None:
    y = H - H * 0.028
    h = H * 0.006
    draw.rounded_rectangle([W * 0.05, y, W * 0.95, y + h], radius=h / 2,
                           fill=(38, 38, 46))
    w = int((W * 0.9) * max(0.0, min(1.0, p)))
    if w > h:
        draw.rounded_rectangle([W * 0.05, y, W * 0.05 + w, y + h], radius=h / 2,
                               fill=ACCENT)


def _draw_watermark(draw: ImageDraw.ImageDraw, W: int, H: int) -> None:
    font = _font(F_SEMI, int(H * 0.024))
    txt = "FairClip"
    bb = _bbox(draw, txt, font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x = W - tw - W * 0.03 - bb[0]
    y = H - th - H * 0.02 - bb[1]
    draw.ellipse([x - tw * 0.35, y + th * 0.15, x - tw * 0.05, y + th * 1.1],
                 fill=(110, 72, 196))
    draw.text((x + 1, y + 1), txt, font=font, fill=(0, 0, 0))
    draw.text((x, y), txt, font=font, fill=(216, 216, 224))


def _draw_disclaimer(draw: ImageDraw.ImageDraw, W: int, H: int) -> None:
    font = _font(F_ROBO_M, int(H * 0.015))
    bb = _bbox(draw, DISCLAIMER_TEXT, font)
    tw = bb[2] - bb[0]
    if tw > W * 0.94:
        font = _font(F_ROBO_M, int(H * 0.012))
        bb = _bbox(draw, DISCLAIMER_TEXT, font)
        tw = bb[2] - bb[0]
    draw.text(((W - tw) / 2 - bb[0] + 1, H * 0.965 - bb[1] + 1), DISCLAIMER_TEXT,
              font=font, fill=(0, 0, 0))
    draw.text(((W - tw) / 2 - bb[0], H * 0.965 - bb[1]), DISCLAIMER_TEXT,
              font=font, fill=(150, 150, 160))


def _draw_waveform(draw: ImageDraw.ImageDraw, W: int, H: int, bars: List[float],
                   y_frac: float) -> None:
    n = len(bars)
    if n == 0:
        return
    cy = H * y_frac
    max_h = H * 0.075
    bw = (W * 0.7) / n
    for i, b in enumerate(bars):
        h = max(3, int(max_h * max(0.03, min(1.0, b))))
        x = W * 0.15 + i * bw
        c = ACCENT2 if b > 0.55 else ACCENT
        draw.rounded_rectangle([x + 1, cy - h / 2, x + bw - 2, cy + h / 2],
                               radius=2, fill=c)
