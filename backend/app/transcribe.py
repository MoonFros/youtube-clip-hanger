"""Transcription: Whisper (local faster-whisper when a model is present,
OpenAI Whisper API when a key is set) with graceful degradation.

If no transcription backend is reachable (e.g. an offline sandbox), the job
still works — captions can be supplied by pasting a transcript in the UI, or
the demo video ships with a built-in ground-truth transcript.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import OPENAI_API_KEY, OPENAI_BASE_URL, WHISPER_MODEL
from .engine import OperationCancelled, decode_wav, decode_audio

_MODEL_CACHE: Dict[str, Any] = {}


def transcribe_job(job, progress_cb=None) -> Dict[str, Any]:
    """Run the best available transcription for a job. Result shape:
    {status: ready|unavailable, engine, text, words:[{w,t0,t1}], sentence_spans:[{s,t0,t1}]}

    `progress_cb(fraction, message)` is called so the UI can show real progress
    instead of an indefinite spinner. Returns quickly (status=unavailable) when
    no engine is installed — that is a normal, non-fatal state.
    """
    path = job.preview_path or job.source_path
    if not path or not job.has_audio:
        return {"status": "unavailable", "reason": "no audio track"}

    def report(f, msg=""):
        if progress_cb:
            progress_cb(f, msg)

    report(0.05, "loading speech model")
    # 1) local faster-whisper (offline). Downloads the model on first use unless
    #    FAIRCLIP_WHISPER_DOWNLOAD=0.
    local = _try_local_whisper(path, report)
    if local:
        return local

    # 2) OpenAI Whisper API (word timestamps)
    if OPENAI_API_KEY:
        report(0.3, "uploading audio to Whisper API")
        r = _openai_whisper(path)
        if r:
            return r

    return {"status": "unavailable",
            "reason": "No transcription engine installed. Captions can still be "
                      "added by pasting a transcript in the Audio panel. For "
                      "offline word-level captions run "
                      "`pip install -r backend/requirements-ai.txt`, or set "
                      "OPENAI_API_KEY to use the Whisper API."}


def _try_local_whisper(path: str, report=None) -> Optional[Dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel  # noqa
    except Exception:
        return None
    model_key = WHISPER_MODEL
    if model_key not in _MODEL_CACHE:
        import os
        local_dir = None
        hf_dir = os.environ.get("HF_HOME", "")
        if hf_dir:
            candidate = Path(hf_dir) / "hub"
            if candidate.exists():
                for d in candidate.iterdir():
                    if WHISPER_MODEL in d.name:
                        local_dir = str(d)
                        break
        if local_dir is None:
            if (os.environ.get("FAIRCLIP_WHISPER_DOWNLOAD", "1") or "1").strip() in ("0", "false", "no"):
                return None
            try:                       # first run: download the model (~150 MB)
                if report:
                    report(0.08, f"downloading whisper '{WHISPER_MODEL}' model (~150 MB)")
                _MODEL_CACHE[model_key] = WhisperModel(WHISPER_MODEL, device="cpu",
                                                       compute_type="int8")
            except Exception:
                return None
            return _whisper_run(_MODEL_CACHE[model_key], path, report)
        try:
            _MODEL_CACHE[model_key] = WhisperModel(local_dir, device="cpu",
                                                    compute_type="int8")
        except Exception:
            return None
    try:
        return _whisper_run(_MODEL_CACHE[model_key], path, report)
    except Exception:
        return None


def _whisper_run(model, path: str, report=None) -> Optional[Dict[str, Any]]:
    try:
        segments, info = model.transcribe(path, word_timestamps=True, beam_size=1)
        total = float(getattr(info, "duration", 0) or 0)
        words: List[Dict[str, float]] = []
        text_parts: List[str] = []
        sentence_spans = []
        for seg in segments:
            if report and total:
                report(min(0.95, 0.1 + 0.85 * (seg.end / total)),
                       f"transcribing {seg.end / total * 100:.0f}%")
            text_parts.append(seg.text.strip())
            sentence_spans.append({"s": seg.text.strip(), "t0": seg.start, "t1": seg.end})
            for w in (seg.words or []):
                words.append({"w": w.word.strip(), "t0": round(w.start, 3),
                              "t1": round(w.end, 3)})
        if not words:
            return None
        return {"status": "ready", "engine": f"whisper:{WHISPER_MODEL}",
                "text": " ".join(text_parts), "words": words,
                "sentence_spans": sentence_spans}
    except OperationCancelled:
        raise                      # user cancelled — do not mask it as "no engine"
    except Exception:
        return None


def _openai_whisper(path: str) -> Optional[Dict[str, Any]]:
    import httpx
    wav = "/tmp/fairclip_whisper_in.wav"
    try:
        x, sr = decode_audio(path, sr=16000, mono=True)
        import wave
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np_clip(x[0]) * 32767).astype("<i2").tobytes())
        with open(wav, "rb") as f:
            r = httpx.post(
                f"{OPENAI_BASE_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": ("audio.wav", f, "audio/wav")},
                data={"model": "whisper-1", "response_format": "verbose_json",
                      "timestamp_granularities[]": "word"},
                timeout=600,
            )
        if r.status_code != 200:
            return None
        data = r.json()
        words = [{"w": w["word"].strip(), "t0": round(w["start"], 3),
                  "t1": round(w["end"], 3)} for w in data.get("words", [])]
        if not words:
            return None
        return {"status": "ready", "engine": "openai-whisper",
                "text": data.get("text", ""), "words": words,
                "sentence_spans": _sentences(words)}
    except Exception:
        return None


def _sentences(words: List[Dict[str, float]]) -> List[Dict[str, Any]]:
    out = []
    cur: List[Dict[str, float]] = []
    for w in words:
        cur.append(w)
        if any(p in w["w"] for p in ".!?") or len(cur) > 14:
            txt = " ".join(x["w"] for x in cur).strip()
            if txt:
                out.append({"s": txt, "t0": cur[0]["t0"], "t1": cur[-1]["t1"]})
            cur = []
    if cur:
        txt = " ".join(x["w"] for x in cur).strip()
        if txt:
            out.append({"s": txt, "t0": cur[0]["t0"], "t1": cur[-1]["t1"]})
    return out


def words_from_pasted_text(text: str, duration: float) -> Dict[str, Any]:
    """Evenly-distributed word timings for a user-pasted transcript."""
    words = re.findall(r"[\w'’\-]+", text)
    if not words or duration <= 0:
        return {"status": "unavailable"}
    per = duration / len(words)
    ws = [{"w": w, "t0": round(i * per, 3), "t1": round((i + 1) * per - 0.02, 3)}
          for i, w in enumerate(words)]
    return {"status": "ready", "engine": "pasted", "text": text,
            "words": ws, "sentence_spans": _sentences(ws)}


import numpy as np  # noqa: E402


def np_clip(x):
    return np.clip(x, -1, 1)
