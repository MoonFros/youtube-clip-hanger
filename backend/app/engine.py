"""PyAV-based video engine: probe, decode, encode, mux.

All FairClip rendering is done with the PyAV wheel (which bundles a full
FFmpeg build with libx264), so the backend needs no system ffmpeg binary.

A system `ffmpeg`/`ffprobe` is used **when present** for the bulk one-shot work
(probing, preview transcodes, audio extraction): it is multithreaded C instead of
a python frame loop, which is 5-20x faster on the same box. Every fast path has a
PyAV fallback, so a missing ffmpeg only costs time, never functionality.
"""
from __future__ import annotations

import json
import io
import os
import shutil
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import av
import numpy as np

def _error_classes(*names: str) -> tuple:
    """Collect the error types that mean "the decoder ran dry" by name.

    PyAV renames/removes some of these between major versions, so a missing one
    must never break the import (a module-level tuple of av.error.* attributes
    is exactly how the backend used to refuse to start on a new av).
    """
    out = []
    for n in names:
        cls = getattr(av.error, n, None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            out.append(cls)
    if not out:                       # last resort, always present
        out.append(av.error.FFmpegError)
    return tuple(out)


PULL_ERRS = _error_classes(
    "EOFError", "BlockingIOError", "BugError", "ExitError", "BrokenPipeError",
    "ProcessLookupError", "TimeoutError",
)


def av_version() -> str:
    return getattr(av, "__version__", "?")


def layout_name(channels: int) -> str:
    """PyAV layout string for a channel count."""
    if channels == 1:
        return "mono"
    if channels == 2:
        return "stereo"
    return f"{channels}c"


def audio_frame_to_float(frame) -> np.ndarray:
    """Decoded AudioFrame -> (channels, samples) float32, on any PyAV version.

    av <= 14 let you ask for a format explicitly (`to_ndarray(format="fltp")`);
    from av 15 on the array follows the frame's own sample format, so packed and
    planar formats have to be normalised by hand here.
    """
    fmt = getattr(getattr(frame, "format", None), "name", "") or "fltp"
    try:
        arr = frame.to_ndarray(format="fltp")        # av <= 14
    except TypeError:
        arr = frame.to_ndarray()                     # av >= 15
    arr = np.asarray(arr)
    planar = fmt.endswith("p") or "planar" in fmt
    base = fmt.rstrip("p").lower()
    if arr.dtype == np.float32:
        out = arr
    elif arr.dtype == np.float64:
        out = arr.astype(np.float32)
    elif base == "s16":
        out = arr.astype(np.float32) / 32768.0
    elif base == "s32":
        out = arr.astype(np.float32) / 2147483648.0
    elif base == "u8":
        out = (arr.astype(np.float32) - 128.0) / 128.0
    else:
        out = arr.astype(np.float32)
    if out.ndim == 1:
        out = out.reshape(1, -1)
    elif out.shape[0] == 1 and not planar:
        # packed: one row holding all channels interleaved
        n = getattr(frame, "layout", None)
        try:
            ch = len(n.channels)
        except Exception:
            ch = 0
        if ch > 1 and out.shape[1] % ch == 0:
            out = out.reshape(-1, ch).T
        else:
            out = out.reshape(1, -1)
    return np.ascontiguousarray(out, dtype=np.float32)


def set_audio_layout(stream, channels: int) -> None:
    """Tell an audio encoder how many channels we feed it.

    av 12 wants `stream.channels = n`; from av 13 on that attribute is
    read-only and the layout is set as a string (or an av.AudioLayout).
    """
    if 1 <= channels <= 8:
        try:
            stream.layout = layout_name(channels)     # av >= 13
            return
        except Exception:
            pass
    stream.channels = int(channels)                   # av <= 12

class OperationCancelled(RuntimeError):
    """Raised when the caller's `cancelled()` callback says to stop."""


_FFMPEG: Optional[str] = None
_FFPROBE: Optional[str] = None
_FF_LOOKED = False


def _look_for_ffmpeg() -> Tuple[Optional[str], Optional[str]]:
    """Locate the system ffmpeg/ffprobe once (optional speed-up, never required)."""
    global _FFMPEG, _FFPROBE, _FF_LOOKED
    if _FF_LOOKED:
        return _FFMPEG, _FFPROBE
    _FF_LOOKED = True
    from .config import FFMPEG
    if FFMPEG:
        p = Path(FFMPEG)
        if p.is_file():
            _FFMPEG = str(p)
            cand = p.with_name("ffprobe" + p.suffix)
            _FFPROBE = str(cand) if cand.is_file() else shutil.which("ffprobe")
        return _FFMPEG, _FFPROBE
    _FFMPEG = shutil.which("ffmpeg")
    _FFPROBE = shutil.which("ffprobe")
    return _FFMPEG, _FFPROBE


def ffmpeg_available() -> bool:
    return bool(_look_for_ffmpeg()[0])


def ffmpeg_version() -> str:
    """Short version string, e.g. "7.0.2-static" ("" when ffmpeg is absent)."""
    ff, _ = _look_for_ffmpeg()
    if not ff:
        return ""
    try:
        out = subprocess.run([ff, "-version"], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        return ""
    first = (out or "").splitlines()[0] if out else ""
    parts = first.split()
    if len(parts) >= 3 and parts[0] == "ffmpeg" and parts[1] == "version":
        return parts[2]
    return first[:60]


def _run(cmd: List[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def probe(path: str) -> Dict[str, Any]:
    """Container/stream info. Uses ffprobe when installed (≈10x faster)."""
    _, ffprobe = _look_for_ffmpeg()
    if ffprobe:
        try:
            out = _run([ffprobe, "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)], timeout=60).stdout
            data = json.loads((out or b"{}").decode("utf-8", "replace"))
            info = _probe_from_ffprobe(data)
            if info["duration"] > 0:
                return info
        except Exception:
            pass
    return _probe_pyav(path)


def _probe_from_ffprobe(data: Dict[str, Any]) -> Dict[str, Any]:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = 0.0
    for src in (fmt.get("duration"), (v or {}).get("duration")):
        try:
            dur = float(src)
            if dur > 0:
                break
        except (TypeError, ValueError):
            continue
    fps = 30.0
    if v:
        for key in ("avg_frame_rate", "r_frame_rate"):
            raw = v.get(key) or ""
            try:
                num, _, den = raw.partition("/")
                if float(den or 1):
                    fps = float(num) / float(den or 1)
                    break
            except ValueError:
                continue
        if not fps:
            fps = 30.0
    # respect rotation (portrait phone videos)
    width = int((v or {}).get("width") or 0)
    height = int((v or {}).get("height") or 0)
    rot = 0
    try:
        for sd in (v or {}).get("side_data_list") or []:
            rot = int(sd.get("rotation") or rot)
    except Exception:
        rot = 0
    if rot % 180 == 90:
        width, height = height, width
    return {
        "duration": dur, "width": width, "height": height, "fps": fps or 30.0,
        "has_audio": a is not None,
        "vcodec": (v or {}).get("codec_name") or "",
        "acodec": (a or {}).get("codec_name") or "",
        "container": (fmt.get("format_name") or ""),
    }


def _probe_pyav(path: str) -> Dict[str, Any]:
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
            "container": (c.format.name or "").split(",")[0],
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
    """Decode full audio track -> float32 array (channels, samples).

    Uses ffmpeg + a temp file when available (roughly an order of magnitude
    faster than decoding frame by frame in python, and it resamples in C).
    """
    ff, _ = _look_for_ffmpeg()
    if ff:
        try:
            return _decode_audio_ffmpeg(ff, path, sr, mono)
        except Exception:
            pass
    return _decode_audio_pyav(path, sr, mono)


def _decode_audio_ffmpeg(ff: str, path: str, sr: int, mono: bool) -> Tuple[np.ndarray, int]:
    import tempfile
    ac = 1 if mono else 2
    fd, tmp = tempfile.mkstemp(suffix=".f32")
    os.close(fd)
    try:
        cmd = [ff, "-y", "-nostdin", "-v", "error", "-i", str(path), "-vn",
               "-map", "0:a:0?", "-f", "f32le", "-acodec", "pcm_f32le",
               "-ac", str(ac), "-ar", str(sr), tmp]
        p = subprocess.run(cmd, capture_output=True, timeout=3600)
        if p.returncode != 0 or not os.path.exists(tmp):
            raise RuntimeError((p.stderr or b"").decode("utf-8", "replace")[:200])
        if os.path.getsize(tmp) == 0:
            raise RuntimeError("no audio stream decoded")   # -> PyAV fallback
        x = np.fromfile(tmp, dtype="<f4")
        if ac == 1:
            x = x.reshape(1, -1)
        else:
            x = x.reshape(-1, ac).T
        return np.ascontiguousarray(x, dtype=np.float32), sr
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _decode_audio_pyav(path: str, sr: int = 48000,
                       mono: bool = True) -> Tuple[np.ndarray, int]:
    """Decode full audio track -> float32 array (channels, samples)."""
    c = av.open(path)
    chunks: List[np.ndarray] = []
    src_sr = sr
    try:
        for frame in c.decode(audio=0):
            src_sr = frame.sample_rate
            chunks.append(audio_frame_to_float(frame))
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


def transcode_preview(
    src: str,
    dst: str,
    preview_max_height: int = 720,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    total_frames_t0: float = 0.0,
    cancelled: Optional[Callable[[], bool]] = None,
) -> None:
    """Make a browser-playable H.264/AAC mp4 no taller than `preview_max_height`.

    ffmpeg path decodes/encodes in C with threads (5-20x faster than the PyAV
    frame-by-frame fallback) and reports real progress through `-progress`.
    """
    ff, _ = _look_for_ffmpeg()
    if ff:
        try:
            _transcode_preview_ffmpeg(ff, src, dst, preview_max_height,
                                      progress_cb, total_frames_t0, cancelled)
            return
        except OperationCancelled:
            raise
        except Exception:
            pass
    _transcode_preview_pyav(src, dst, preview_max_height, progress_cb, cancelled)


def _transcode_preview_ffmpeg(ff: str, src: str, dst: str, max_h: int,
                              progress_cb, dur: float, cancelled) -> None:
    vf = f"scale=-2:'min({max_h},ih)',format=yuv420p"
    cmd = [ff, "-y", "-nostdin", "-v", "error", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
           "-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
           str(dst)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, bufsize=1)
    last = 0
    try:
        assert p.stdout is not None
        for line in p.stdout:
            if cancelled and cancelled():
                p.kill()
                raise OperationCancelled("cancelled")
            key, _, val = line.strip().partition("=")
            if key in ("out_time_ms", "out_time_us") and dur > 0:
                try:
                    t = float(val) / 1_000_000
                except ValueError:
                    continue
                if progress_cb:
                    frac = max(0.0, min(1.0, t / dur))
                    total = max(1, int(dur * 30))
                    if int(frac * total) > last:
                        last = int(frac * total)
                        progress_cb(last, total)
    finally:
        p.wait()
    if p.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 1024:
        err = (p.stderr.read() if p.stderr else "")[:300]
        raise RuntimeError(f"ffmpeg preview transcode failed: {err}")
    if progress_cb:
        progress_cb(1, 1)


def _transcode_preview_pyav(src: str, dst: str, max_h: int, progress_cb,
                            cancelled=None) -> None:
    """Fallback: decode + resize + re-encode entirely through PyAV/numpy/PIL."""
    info = probe(src)
    w, h = info["width"], info["height"]
    if h > max_h:
        scale = max_h / h
        ow, oh = int(w * scale // 2 * 2), int(max_h // 2 * 2)
    else:
        ow, oh = w // 2 * 2, h // 2 * 2
    fps = 30 if info["fps"] < 45 else 60

    def gen():
        from PIL import Image
        for _t, img in iter_frames(src):
            if cancelled and cancelled():
                raise OperationCancelled("cancelled")
            yield np.asarray(Image.fromarray(img).resize((ow, oh), Image.BILINEAR))

    audio, sr = (decode_audio(src, sr=48000, mono=False)
                 if info["has_audio"] else (None, 48000))
    mux_output(dst, ow, oh, fps, gen(), audio=audio, audio_sr=sr, crf=23,
               preset="veryfast", progress_cb=progress_cb,
               total_frames=int(info["duration"] * fps))


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
        set_audio_layout(ast, int(audio.shape[0]))
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
                af = av.AudioFrame.from_ndarray(
                    np.ascontiguousarray(chunk, dtype=np.float32), format="fltp",
                    layout=layout_name(chunk.shape[0]))
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
            af = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(left, dtype=np.float32), format="fltp",
                layout=layout_name(left.shape[0]))
            af.sample_rate = audio_sr
            af.pts = n * spf
            for p in ast.encode(af):
                c.mux(p)
        for p in ast.encode(None):
            c.mux(p)
    c.close()
    return n, n / fps if fps else 0.0
