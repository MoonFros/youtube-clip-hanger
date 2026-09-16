"""Text-to-speech for Bookend commentary.

Provider chain (first available wins):
  1. ElevenLabs API        (if ELEVENLABS_API_KEY is set) — natural premium voices
  2. OpenAI TTS            (if OPENAI_API_KEY is set)     — natural premium voices
  3. Vendored meSpeak      (always available, offline)    — robotic "demo" voice
Mic recordings uploaded from the browser are used verbatim (no provider).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from .config import ELEVENLABS_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, TTS_BRIDGE, TTS_VOICES

_NODE = shutil.which("node") or "node"


def synthesize(
    text: str,
    voice_id: str = "deep",
    out_path: str = "",
    max_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Synthesize text to a 22kHz mono wav. Returns {path, engine, duration}."""
    if not out_path:
        fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
    preset = TTS_VOICES.get(voice_id, TTS_VOICES["deep"])
    if ELEVENLABS_API_KEY:
        r = _elevenlabs(text, voice_id, out_path)
        if r:
            return r
    if OPENAI_API_KEY:
        r = _openai_tts(text, voice_id, out_path)
        if r:
            return r
    r = _mespeak(text, voice_id, out_path)
    if max_seconds and r.get("duration", 0) > max_seconds:
        r = _fit_to_duration(r["path"], max_seconds)
        r = {**r, "path": r["path"]}
    return {**r, "engine": r.get("engine", "mespeak"), "voice": voice_id, "preset": preset[2]}


def _mespeak(text: str, voice_id: str, out_path: str) -> Dict[str, Any]:
    voice, variant, label, _ = TTS_VOICES.get(voice_id, TTS_VOICES["deep"])
    cmd = [_NODE, str(TTS_BRIDGE), "--text", text, "--voice", voice,
           "--variant", variant, "--out", out_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or not os.path.exists(out_path):
            raise RuntimeError(proc.stderr.strip()[:300] or "mespeak failed")
        from .engine import decode_wav
        x, sr = decode_wav(out_path)
        return {"path": out_path, "engine": "mespeak", "voice": voice_id,
                "preset": label, "duration": round(x.shape[1] / sr, 2), "sr": sr}
    except Exception as e:  # noqa: BLE001
        return {"path": "", "engine": "error", "error": str(e)}


def _openai_tts(text: str, voice_id: str, out_path: str) -> Optional[Dict[str, Any]]:
    import httpx
    voice_map = {"deep": "onyx", "story": "alloy", "casual": "nova",
                 "energetic": "coral", "hype": "shimmer"}
    try:
        r = httpx.post(
            f"{OPENAI_BASE_URL}/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "gpt-4o-mini-tts", "voice": voice_map.get(voice_id, "alloy"),
                  "input": text[:400]},
            timeout=90,
        )
        if r.status_code != 200:
            return None
        Path(out_path).write_bytes(r.content)
        from .engine import decode_wav
        x, sr = decode_wav(out_path)
        # resample to 22k mono
        if sr != 22050 or x.shape[0] != 1:
            _resample_save(out_path, x, sr)
        return {"path": out_path, "engine": "openai", "voice": voice_id,
                "duration": round(x.shape[1] / sr, 2), "sr": 22050}
    except Exception:
        return None


def _elevenlabs(text: str, voice_id: str, out_path: str) -> Optional[Dict[str, Any]]:
    import httpx
    # preset voice ids for ElevenLabs (defaults may be replaced in settings)
    voice_map = {
        "deep": "pNInz6obpgDQGcFmaJgB",          # Adam
        "story": "EXAVITQu4vr4xnSDxMaL",          # Antoni
        "casual": "TxGEqnHWrfWFTfGW9XjX",         # Bill
        "energetic": "21m00Tcm4TlvDq8ikWAM",      # Callie
        "hype": "MF3mGyEYCl7XYWbV9V6O",           # Eve
    }
    try:
        r = httpx.post(
            "https://api.elevenlabs.io/v1/text-to-speech/" + voice_map.get(voice_id, voice_map["story"]),
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={"text": text[:400], "model_id": "eleven_multilingual_v2"},
            timeout=90,
        )
        if r.status_code != 200:
            return None
        Path(out_path).write_bytes(r.content)
        from .engine import decode_wav
        x, sr = decode_wav(out_path)
        _resample_save(out_path, x, sr)
        return {"path": out_path, "engine": "elevenlabs", "voice": voice_id,
                "duration": round(x.shape[1] / sr, 2), "sr": 22050}
    except Exception:
        return None


def _resample_save(out_path: str, x: np.ndarray, sr: int) -> None:  # noqa: F821
    import numpy as np
    from .engine import decode_audio
    if x.shape[0] > 1:
        x = x.mean(axis=0, keepdims=True)
    n_out = int(x.shape[1] * 22050 / sr)
    xi = np.arange(n_out) * (sr / 22050)
    idx = np.clip(np.floor(xi).astype(int), 0, x.shape[1] - 2)
    frac = (xi - idx).astype(np.float32)
    y = x[0, idx] * (1 - frac) + x[0, idx + 1] * frac
    import wave
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())


def _fit_to_duration(path: str, max_seconds: float) -> Dict[str, Any]:
    """Time-stretch a wav (rate resample) so it fits max_seconds."""
    import numpy as np
    from .engine import decode_wav
    x, sr = decode_wav(path)
    target = int(max_seconds * sr)
    if x.shape[1] <= target:
        return {"path": path}
    xi = np.arange(target) * (x.shape[1] / target)
    idx = np.clip(np.floor(xi).astype(int), 0, x.shape[1] - 2)
    frac = (xi - idx).astype(np.float32)
    y = x[:, idx] * (1 - frac) + x[:, idx + 1] * frac
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(int(x.shape[0]))
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    return {"path": path, "duration": max_seconds}
