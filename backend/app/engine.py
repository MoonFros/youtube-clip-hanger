"""PyAV-based video engine: probe, decode, encode, mux.

All FairClip rendering is done with the PyAV wheel (which bundles a full
FFmpeg build with libx264), so the backend needs no system ffmpeg binary.
"""
from __future__ import annotations

import io
import time
from fractions import Fraction
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import av
import numpy as np

PULL_ERRS = (
    av.error.EOFError,
    av.error.BlockingIOError,
    av.error.BugError,
    av.error.ExitError,
    av.error.BrokenPipeError,
    av.error.ProcessLookupError,
    av.error.TimeoutError,
)


def probe(path: str) -> Dict[str, Any]:
    c = av.open(path)
    try:
        vs = c.streams.video[0]
        fps = float(vs.average_rate) if vs.average_rate else 30.0
        w, h = vs.width, vs.height
        if c.duration:
            dur = float(c.duration) / 1_000_000
        elif vs.duration:
            dur = float(vs.duration * vs.time_base)
        else:
            dur = 0.0
        if dur <= 0:
            # fallback: count frames
            n = 0
            for _ in c.decode(video=0):
                n += 1
            dur = n / fps if fps else 0.0
        return {
            "duration": dur, "width": w, "height": h, "fps": fps,
            "has_audio": len(c.streams.audio) > 0,
            "vcodec": vs.codec_context.name,
            "acodec": c.streams.audio[0].codec_context.name if c.streams.audio else "",
            "container": c.format.name or "",
        }
    finally:
        c.close()


def iter_frames(
    path: str,
    start: Optional[float] = None,
    end: Optional[float] = None,
    max_dim: Optional[int] = None,
) -> Generator[Tuple[float, np.ndarray], None, None]:
    """Yield (time_seconds, rgb_ndarray) frames from a video file."""
    c = av.open(path)
    try:
        for frame in c.decode(video=0):
            t = float(frame.time)
            if start is not None and t < start - 0.25:
                continue
            if end is not None and t >= end:
                break
            img = frame.to_ndarray(format="rgb24")
            if max_dim:
                h, w = img.shape[:2]
                m = max(h, w)
                if m > max_dim:
                    scale = max_dim / m
                    from PIL import Image
                    img = np.asarray(Image.fromarray(img).resize(
                        (max(2, int(w * scale)), max(2, int(h * scale))),
                        Image.BILINEAR))
            yield t, img
    finally:
        c.close()


def decode_audio(path: str, sr: int = 48000, mono: bool = True) -> Tuple[np.ndarray, int]:
    """Decode full audio track -> float32 array (channels, samples)."""
    c = av.open(path)
    chunks: List[np.ndarray] = []
    src_sr = sr
    has = False
    try:
        for frame in c.decode(audio=0):
            has = True
            src_sr = frame.sample_rate
            arr = frame.to_ndarray(format="fltp")  # (ch, n) float32
            chunks.append(arr)
    finally:
        c.close()
    if not chunks:
        return np.zeros((1, 0), dtype=np.float32), sr
    x = np.concatenate(chunks, axis=1)
    if src_sr != sr:
        n_out = int(x.shape[1] * sr / src_sr)
        xi = np.arange(n_out) * (src_sr / sr)
        idx = np.floor(xi).astype(np.int64)
        frac = (xi - idx).astype(np.float32)
        idx = np.clip(idx, 0, x.shape[1] - 2)
        x = x[:, idx] * (1 - frac) + x[:, idx + 1] * frac
    if mono and x.shape[0] > 1:
        x = x.mean(axis=0, keepdims=True)
    return x.astype(np.float32), sr


def decode_wav(path: str) -> Tuple[np.ndarray, int]:
    """Load a 16-bit PCM wav -> (ch, n) float32."""
    import wave
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    x = x.reshape(-1, ch).T
    return x, sr


def frame_to_av(rgb: np.ndarray, out_w: int, out_h: int) -> "av.VideoFrame":
    vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
    if vf.width != out_w or vf.height != out_h:
        vf = vf.reformat(out_w, out_h)
    return vf.reformat(format="yuv420p")


def mux_output(
    out_path: str,
    out_w: int,
    out_h: int,
    fps: int,
    video_frames: Generator[np.ndarray, None, None],
    audio: Optional[np.ndarray] = None,          # (ch, n) float32 @48k
    audio_sr: int = 48000,
    crf: int = 20,
    preset: str = "veryfast",
    mov: bool = False,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    total_frames: int = 0,
) -> Tuple[int, float]:
    """Encode video generator (+ optional audio) to mp4/mov. Returns (n_frames, duration)."""
    fmt = "mov" if mov else "mp4"
    c = av.open(out_path, mode="w", format=fmt,
                options={"movflags": "+faststart"})
    vst = c.add_stream("libx264", rate=fps)
    vst.width, vst.height, vst.pix_fmt = out_w, out_h, "yuv420p"
    vst.options = {"preset": preset, "crf": str(crf), "profile": "high"}
    vst.thread_type = "AUTO"

    ast = None
    if audio is not None and audio.size:
        ast = c.add_stream("aac", rate=audio_sr)
        ast.channels = int(audio.shape[0])
        ast.bit_rate = 192_000

    spf = audio_sr // fps if ast is not None else 0
    n = 0
    for rgb in video_frames:
        vf = frame_to_av(rgb, out_w, out_h)
        for p in vst.encode(vf):
            c.mux(p)
        if ast is not None and n * spf < audio.shape[1]:
            chunk = audio[:, n * spf:(n + 1) * spf]
            if chunk.size:
                af = av.AudioFrame.from_ndarray(chunk, format="fltp")
                af.sample_rate = audio_sr
                af.pts = n * spf
                for p in ast.encode(af):
                    c.mux(p)
        n += 1
        if progress_cb and total_frames and (n % 15 == 0 or n == total_frames):
            progress_cb(n, total_frames)
    for p in vst.encode(None):
        c.mux(p)
    if ast is not None:
        # flush remaining audio
        left = audio[:, n * spf:] if audio is not None else None
        if left is not None and left.size:
            af = av.AudioFrame.from_ndarray(left, format="fltp")
            af.sample_rate = audio_sr
            af.pts = n * spf
            for p in ast.encode(af):
                c.mux(p)
        for p in ast.encode(None):
            c.mux(p)
    c.close()
    return n, n / fps if fps else 0.0
