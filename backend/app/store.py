"""In-memory store with JSON persistence for jobs, clips and renders."""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DATA_DIR


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass
class Job:
    id: str
    source_type: str                    # upload | url | link | demo
    source: str = ""                    # original url / filename
    status: str = "queued"              # queued|processing|ready|error|cancelled
    stage: str = ""
    progress: float = 0.0
    detail: str = ""                    # human readable sub-stage detail
    cancel_requested: bool = False
    progress_lo: float = 0.0            # window of the bar this job owns
    progress_hi: float = 1.0
    error: str = ""
    name: str = "Untitled video"
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 30.0
    has_audio: bool = True
    letterbox: Dict[str, int] = field(default_factory=dict)
    scenes: List[float] = field(default_factory=list)
    suggested_clips: List[Dict[str, Any]] = field(default_factory=list)
    waveform: Dict[str, Any] = field(default_factory=dict)
    transcript: Dict[str, Any] = field(default_factory=dict)
    stems: Dict[str, Any] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    source_path: str = ""
    preview_path: str = ""
    stems_ready: bool = False
    demo: bool = False

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id, "source_type": self.source_type, "source": self.source,
            "status": self.status, "stage": self.stage, "progress": round(self.progress, 3),
            "detail": self.detail,
            "error": self.error, "name": self.name, "duration": round(self.duration, 2),
            "width": self.width, "height": self.height, "fps": self.fps,
            "has_audio": self.has_audio, "letterbox": self.letterbox,
            "scenes": [round(s, 2) for s in self.scenes],
            "suggested_clips": self.suggested_clips,
            "created": self.created, "demo": self.demo,
        }


@dataclass
class Clip:
    id: str
    job_id: str
    start: float
    end: float
    name: str = "Clip"
    template: str = "cinematic_zoom"
    bookend: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True, "style": "auto", "intro_text": "", "outro_text": "",
        "fact": "", "voice": "deep", "tts_status": "pending",
    })
    audio: Dict[str, Any] = field(default_factory=lambda: {
        "dialogue": {"mode": "keep", "gain": 1.0},
        "music": {"mode": "auto", "gain": 0.5},
        "sfx": {"mode": "keep", "gain": 1.0},
    })
    renders: List[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id, "job_id": self.job_id, "start": round(self.start, 2),
            "end": round(self.end, 2), "duration": round(self.duration, 2),
            "name": self.name, "template": self.template, "bookend": self.bookend,
            "audio": self.audio, "renders": self.renders, "created": self.created,
        }


@dataclass
class Render:
    id: str
    clip_id: str
    job_id: str
    template: str
    options: Dict[str, Any] = field(default_factory=dict)
    status: str = "queued"              # queued|compositing|muxing|preflight|done|error
    stage: str = ""
    progress: float = 0.0
    error: str = ""
    output_path: str = ""
    duration: float = 0.0
    size: int = 0
    preflight: Dict[str, Any] = field(default_factory=dict)
    audio_plan: Dict[str, Any] = field(default_factory=dict)
    created: float = field(default_factory=time.time)

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id, "clip_id": self.clip_id, "job_id": self.job_id,
            "template": self.template, "options": self.options,
            "status": self.status, "stage": self.stage, "progress": round(self.progress, 3),
            "error": self.error, "duration": round(self.duration, 2), "size": self.size,
            "preflight": self.preflight, "created": self.created,
        }


class Store:
    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self.clips: Dict[str, Clip] = {}
        self.renders: Dict[str, Render] = {}
        self.settings: Dict[str, Any] = {
            "plan": "free",
            "upload_token": "",
            "daily": {},
        }
        self.lock = threading.RLock()
        self._load_settings()

    # -- persistence (best effort) -----------------------------------------
    def _settings_path(self) -> Path:
        return DATA_DIR / "settings.json"

    def _load_settings(self) -> None:
        try:
            p = self._settings_path()
            if p.exists():
                self.settings.update(json.loads(p.read_text()))
        except Exception:
            pass

    def save_settings(self) -> None:
        try:
            self._settings_path().write_text(json.dumps(self.settings, indent=1))
        except Exception:
            pass

    # -- daily render counter (free tier) -----------------------------------
    def render_count_today(self, plan: str) -> int:
        import datetime as _dt
        day = _dt.datetime.utcnow().strftime("%Y-%m-%d")
        return int(self.settings["daily"].get(f"{plan}:{day}", 0))

    def bump_render_count(self, plan: str) -> int:
        import datetime as _dt
        day = _dt.datetime.utcnow().strftime("%Y-%m-%d")
        key = f"{plan}:{day}"
        self.settings["daily"][key] = int(self.settings["daily"].get(key, 0)) + 1
        # keep the last 14 days only
        for k in [k for k in self.settings["daily"] if k.split(":")[1] < day[:4] + "-"]:
            pass
        self.save_settings()
        return int(self.settings["daily"][key])

    # -- jobs ---------------------------------------------------------------
    def create_job(self, source_type: str, source: str = "", name: str = "",
                   demo: bool = False) -> Job:
        with self.lock:
            job = Job(id=_uid("job"), source_type=source_type, source=source,
                      name=name or ("Demo scene" if demo else "Untitled video"),
                      demo=demo)
            self.jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self.lock:
            return self.jobs.get(job_id)

    # -- clips --------------------------------------------------------------
    def create_clip(self, job_id: str, start: float, end: float,
                    name: str = "Clip") -> Clip:
        with self.lock:
            clip = Clip(id=_uid("clip"), job_id=job_id, start=start, end=end, name=name)
            self.clips[clip.id] = clip
            job = self.jobs.get(job_id)
            if job:
                pass
        return clip

    def get_clip(self, clip_id: str) -> Optional[Clip]:
        with self.lock:
            return self.clips.get(clip_id)

    def job_clips(self, job_id: str) -> List[Clip]:
        with self.lock:
            return [c for c in self.clips.values() if c.job_id == job_id]

    def delete_clip(self, clip_id: str) -> bool:
        with self.lock:
            clip = self.clips.pop(clip_id, None)
            if clip is None:
                return False
            for rid in list(clip.renders):
                self.renders.pop(rid, None)
            return True

    # -- renders -------------------------------------------------------------
    def create_render(self, clip: Clip, template: str, options: Dict[str, Any]) -> Render:
        with self.lock:
            r = Render(id=_uid("r"), clip_id=clip.id, job_id=clip.job_id,
                       template=template, options=options)
            self.renders[r.id] = r
            clip.renders.append(r.id)
        return r

    def get_render(self, render_id: str) -> Optional[Render]:
        with self.lock:
            return self.renders.get(render_id)

    def clip_renders(self, clip_id: str) -> List[Render]:
        with self.lock:
            return [r for r in self.renders.values() if r.clip_id == clip_id]


STORE = Store()
