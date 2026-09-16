"""REST API for FairClip."""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from .config import (
    DATA_DIR,
    HOOK_STYLES,
    LEGAL_DISCLAIMER,
    PRO_PRICE,
    TIERS,
    TTS_VOICES,
)
from .engine import probe
from .preflight import check_render, frame_similarity_timeline
from .render import build_plan, run_render
from .store import STORE
from .templates import DEFAULT_TEMPLATE, TEMPLATES, template_list_public

router = APIRouter(prefix="/api")

demo_state = {"generating": False, "done": False, "error": ""}

# strong references to background tasks (avoids GC of pending asyncio tasks)
_background_tasks: set = set()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)


# ---------------- helpers ------------------------------------------------------

def _range_response(path: str, request: Request, media_type: str) -> Response:
    size = os.path.getsize(path)
    rng = request.headers.get("range")
    if rng:
        try:
            rngval = rng.replace("bytes=", "")
            start_s, _, end_s = rngval.partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
            end = min(end, size - 1)
            length = end - start + 1
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(length)
            return Response(content=data, status_code=206, media_type=media_type,
                            headers={
                                "Content-Range": f"bytes {start}-{end}/{size}",
                                "Accept-Ranges": "bytes",
                                "Content-Length": str(length),
                            })
        except Exception:
            pass
    return FileResponse(path, media_type=media_type)


def _get_job_or_404(job_id: str):
    job = STORE.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def _get_clip_or_404(clip_id: str):
    clip = STORE.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "clip not found")
    return clip


# ---------------- settings / meta ---------------------------------------------

@router.get("/health")
def health():
    demo_file = DATA_DIR / "demo" / "demo.mp4"
    return {
        "ok": True,
        "plan": STORE.settings.get("plan", "free"),
        "demo_ready": demo_file.exists(),
        "demo_generating": demo_state["generating"],
        "demo_error": demo_state["error"],
        "tts_voices": {k: {"label": v[2], "desc": v[3]} for k, v in TTS_VOICES.items()},
        "hook_styles": HOOK_STYLES,
        "tiers": {k: v for k, v in TIERS.items()},
        "pro_price": PRO_PRICE,
        "legal_disclaimer": LEGAL_DISCLAIMER,
    }


@router.get("/settings")
def get_settings():
    return {"plan": STORE.settings.get("plan", "free"),
            "has_upload_token": bool(STORE.settings.get("upload_token"))}


@router.put("/settings")
def put_settings(body: Dict[str, Any]):
    if "plan" in body and body["plan"] in TIERS:
        STORE.settings["plan"] = body["plan"]
    if "upload_token" in body:
        STORE.settings["upload_token"] = str(body["upload_token"])
    STORE.save_settings()
    return get_settings()


@router.get("/templates")
def templates():
    return template_list_public()


# ---------------- jobs ----------------------------------------------------------

@router.post("/jobs")
async def create_job(body: Dict[str, Any]):
    from . import ingest
    src = body.get("source") or body
    src_type = str(src.get("type", "upload"))
    src_url = str(src.get("url", ""))
    if src_type == "demo":
        from .demo import ensure_demo
        demo_file = DATA_DIR / "demo" / "demo.mp4"
        if demo_file.exists():
            job = STORE.create_job("demo", source="demo-scene", name="Demo scene: 'The Reactor' (synthetic)", demo=True)
            meta = ensure_demo(str(demo_file))[1]
            job.transcript = meta["transcript"]
            job.source_path = str(demo_file)
            _spawn(ingest.run_job(job.id))
            return {"job_id": job.id}
        if not demo_state["generating"]:
            job = STORE.create_job("demo", source="demo-scene", name="Demo scene: 'The Reactor' (synthetic)", demo=True)
            demo_state["generating"] = True

            async def _gen():
                try:
                    path, meta = await asyncio.to_thread(ensure_demo, str(demo_file))
                    job.source_path = path
                    job.transcript = meta["transcript"]
                    await ingest.run_job(job.id)
                    demo_state["done"] = True
                except Exception as e:  # noqa: BLE001
                    demo_state["error"] = str(e)
                finally:
                    demo_state["generating"] = False
            _spawn(_gen())
            return {"job_id": job.id}
        raise HTTPException(409, "Demo is already being generated")

    job = STORE.create_job(src_type, source=src_url,
                           name=(src_url or "upload").rsplit("/", 1)[-1][:60] or "Untitled")
    if src_type == "url":
        from .ingest import ingest_youtube
        _spawn(_ingest_then_run(job, lambda: ingest_youtube(job, src_url)))
    elif src_type == "link":
        from .ingest import ingest_link
        _spawn(_ingest_then_run(job, lambda: ingest_link(job, src_url)))
    return {"job_id": job.id}


async def _ingest_then_run(job, ingest_fn):
    from . import ingest
    try:
        await ingest_fn()
        await ingest.run_job(job.id)
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)[:400]


@router.post("/jobs/{job_id}/upload")
async def upload(job_id: str, file: UploadFile = File(...)):
    from . import ingest
    job = _get_job_or_404(job_id)
    if job.status not in ("queued", "processing") and job.source_path:
        raise HTTPException(409, "job already has a source")
    if not job.source_type == "upload" and not job.source_path:
        job.source_type = "upload"
    await asyncio.to_thread(ingest.ingest_upload, job, file.file)
    await asyncio.to_thread(ingest.finalize_job_source, job)
    _spawn(ingest.run_job(job.id))
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    return _get_job_or_404(job_id).public()


@router.get("/jobs/{job_id}/analysis")
def job_analysis(job_id: str):
    job = _get_job_or_404(job_id)
    return {
        "job": job.public(),
        "waveform": job.waveform,
        "stems": job.stems,
        "transcript": job.transcript,
        "templates": template_list_public(),
        "tiers": {k: {kk: vv for kk, vv in v.items() if kk != "export_presets"}
                  for k, v in TIERS.items()},
    }


@router.post("/jobs/{job_id}/transcript")
def paste_transcript(job_id: str, body: Dict[str, Any]):
    from .transcribe import words_from_pasted_text
    job = _get_job_or_404(job_id)
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    res = words_from_pasted_text(text, job.duration)
    if res.get("status") != "ready":
        raise HTTPException(400, "could not parse transcript")
    job.transcript = res
    from .ingest import _suggest
    _suggest(job)
    return {"status": "ready", "word_count": len(res["words"]),
            "suggested_clips": job.suggested_clips}


# ---------------- clips ----------------------------------------------------------

@router.post("/jobs/{job_id}/clips")
def create_clip(job_id: str, body: Dict[str, Any]):
    from .config import TIERS
    job = _get_job_or_404(job_id)
    start = float(body.get("start", 0))
    end = float(body.get("end", 0))
    name = str(body.get("name", "Clip"))[:60]
    tier = TIERS[STORE.settings.get("plan", "free")]
    if end <= start:
        raise HTTPException(400, "end must be after start")
    if end - start > tier["max_clip_seconds"]:
        raise HTTPException(400,
                            f"Clip too long for {tier['label']} tier "
                            f"(max {tier['max_clip_seconds']:.0f}s)")
    if start < 0 or end > job.duration + 0.25:
        raise HTTPException(400, "clip outside video bounds")
    clip = STORE.create_clip(job_id, start, end, name)
    return clip.public()


@router.get("/jobs/{job_id}/clips")
def list_clips(job_id: str):
    return [c.public() for c in STORE.job_clips(job_id)]


@router.patch("/clips/{clip_id}")
def update_clip(clip_id: str, body: Dict[str, Any]):
    clip = _get_clip_or_404(clip_id)
    if "start" in body:
        clip.start = max(0.0, float(body["start"]))
    if "end" in body:
        clip.end = float(body["end"])
    if clip.end <= clip.start:
        raise HTTPException(400, "end must be after start")
    if "name" in body:
        clip.name = str(body["name"])[:60]
    if "template" in body and body["template"] in TEMPLATES:
        clip.template = body["template"]
    if "audio" in body and isinstance(body["audio"], dict):
        for layer in ("dialogue", "music", "sfx"):
            if layer in body["audio"]:
                spec = body["audio"][layer]
                if "mode" in spec:
                    clip.audio[layer]["mode"] = spec["mode"]
                if "gain" in spec:
                    clip.audio[layer]["gain"] = max(0.0, min(1.5, float(spec["gain"])))
    if "bookend" in body and isinstance(body["bookend"], dict):
        for k in ("enabled", "style", "voice", "intro_text", "outro_text", "fact"):
            if k in body["bookend"]:
                clip.bookend[k] = body["bookend"][k]
    return clip.public()


@router.delete("/clips/{clip_id}")
def delete_clip(clip_id: str):
    return {"deleted": STORE.delete_clip(clip_id)}


# ---------------- bookend ---------------------------------------------------------

@router.post("/clips/{clip_id}/bookend")
async def bookend(clip_id: str, body: Dict[str, Any]):
    from . import hooks
    from .ingest import job_dir
    from .tts import synthesize
    clip = _get_clip_or_404(clip_id)
    job = _get_job_or_404(clip.job_id)
    style = body.get("style", "auto")
    voice = body.get("voice", clip.bookend.get("voice", "deep"))
    return _generate_bookend(clip, job, style, voice, hooks, job_dir, synthesize)


@router.post("/clips/{clip_id}/bookend/mic")
async def bookend_mic(clip_id: str, mic: UploadFile = File(...),
                      style: str = Form("auto"), voice: str = Form("mic")):
    from . import hooks
    from .ingest import job_dir
    from .tts import synthesize
    clip = _get_clip_or_404(clip_id)
    job = _get_job_or_404(clip.job_id)
    mic_path = None
    d = job_dir(job)
    intro_wav = d / f"mic_{clip.id}_intro.wav"
    with open(intro_wav, "wb") as f:
        shutil.copyfileobj(mic.file, f)
    mic_path = str(intro_wav)
    return _generate_bookend(clip, job, style, "mic", hooks, job_dir, synthesize,
                             mic_path=mic_path)


def _generate_bookend(clip, job, style, voice, hooks, job_dir, synthesize,
                      mic_path: Optional[str] = None) -> Dict[str, Any]:

    words = job.transcript.get("words") or []
    sentences = job.transcript.get("sentence_spans") or []
    result = hooks.generate_bookend_script(words, sentences, clip.start, clip.end,
                                           style=style)

    d = job_dir(job)
    tts_audio = {}
    if voice in TTS_VOICES:
        for key, text_field in (("intro", "intro"), ("outro", "outro")):
            text = result.get(text_field, "")
            if not text:
                continue
            out = d / f"tts_{clip.id}_{key}.wav"
            if not out.exists():
                r = synthesize(text, voice_id=voice, out_path=str(out), max_seconds=3.0)
                if not r.get("path"):
                    result["tts_error"] = r.get("error", "tts failed")
                    break
            else:
                from .engine import decode_wav
                x, sr = decode_wav(str(out))
                r = {"duration": round(x.shape[1] / sr, 2)}
            tts_audio[key] = {
                "url": f"/media/jobs/{job.id}/tts/{out.name}",
                "duration": r.get("duration"),
            }
    elif voice == "mic" and mic_path is not None:
        tts_audio["intro"] = {"url": f"/media/jobs/{job.id}/tts/{Path(mic_path).name}",
                              "duration": None}
        # keep one mic note for the intro, outro stays visual-only
    clip.bookend.update({
        "style": result.get("style", style if style in HOOK_STYLES else "B"),
        "intro_text": result.get("intro", ""),
        "outro_text": result.get("outro", ""),
        "fact": result.get("fact", ""),
        "voice": voice,
        "tts_status": "ready" if tts_audio else ("off" if voice == "off" else "missing"),
        "script_engine": result.get("engine", ""),
    })
    if voice == "off":
        clip.bookend["tts_status"] = "off"
    return {"clip": clip.public(), "script": result, "tts_audio": tts_audio}


# ---------------- renders -----------------------------------------------------------

@router.post("/clips/{clip_id}/renders")
async def create_render(clip_id: str, body: Dict[str, Any]):
    from .config import TIERS
    clip = _get_clip_or_404(clip_id)
    job = _get_job_or_404(clip.job_id)
    plan_name = STORE.settings.get("plan", "free")
    tier = TIERS[plan_name]
    template = body.get("template", clip.template)
    if template not in TEMPLATES:
        raise HTTPException(400, "unknown template")
    if clip.duration > tier["max_clip_seconds"]:
        raise HTTPException(400, f"Clip exceeds {plan_name} tier limit "
                                 f"({tier['max_clip_seconds']:.0f}s)")
    daily = STORE.render_count_today(plan_name)
    if daily >= tier["daily_clip_limit"]:
        raise HTTPException(403, f"Daily limit reached ({tier['daily_clip_limit']} "
                                 f"clips/day on {tier['label']}). Upgrade to Pro for "
                                 f"unlimited.")
    options = body.get("options", {}) or {}
    width = int(options.get("width", 720))
    if width > tier["max_render_width"]:
        width = tier["max_render_width"]
    options["width"] = width
    options["height"] = int(width * 16 / 9)
    options["fps"] = int(options.get("fps", 30))
    options["format"] = options.get("format", "mp4")
    options["crf"] = int(options.get("crf", 20))
    options["preset"] = options.get("preset", "veryfast")
    options["watermark"] = bool(options.get("watermark", True))
    if tier["watermark_forced"]:
        options["watermark"] = True
    options["disclaimer"] = bool(options.get("disclaimer", False))
    options["grade"] = options.get("grade", "auto")
    options["music_replace"] = bool(options.get("music_replace", False))
    # audio overrides for one-click fixes
    fix = body.get("fix_options") or {}
    if fix.get("audio"):
        for layer, spec in fix["audio"].items():
            clip.audio[layer].update(spec)
    clip.template = template

    render = STORE.create_render(clip, template, options)
    STORE.bump_render_count(plan_name)
    if tier["watermark_forced"]:
        pass
    _spawn(_run_render_task(render))
    return render.public()


async def _run_render_task(render) -> None:
    from .ingest import job_dir
    clip = STORE.get_clip(render.clip_id)
    job = STORE.get_job(render.job_id)
    if clip is None or job is None:
        render.status = "error"
        render.error = "clip or job missing"
        return
    try:
        render.status = "compositing"
        render.stage = "building plan"
        plan = await asyncio.to_thread(build_plan, job, clip, render.template,
                                       render.options, STORE)

        def prog(p, stage):
            render.progress = p
            render.stage = stage

        d = job_dir(job)
        ext = "mov" if render.options.get("format") == "mov" else "mp4"
        out = d / f"render_{render.id}.{ext}"
        await asyncio.to_thread(run_render, plan, str(out), prog)
        render.output_path = str(out)
        render.status = "preflight"
        render.stage = "content id pre-flight"
        render.progress = 0.97
        render.audio_plan = plan.get("audio_plan", {})
        info = probe(render.output_path)
        render.duration = info["duration"]
        render.size = os.path.getsize(render.output_path)
        sims = await asyncio.to_thread(
            frame_similarity_timeline, render.output_path,
            job.preview_path or job.source_path, plan["t0"], plan["t1"])
        render.preflight = check_render(render, sims)
        render.status = "done"
        render.progress = 1.0
        render.stage = "done"
    except Exception as e:  # noqa: BLE001
        render.status = "error"
        render.error = f"{type(e).__name__}: {e}"
        import traceback
        traceback.print_exc()


@router.get("/clips/{clip_id}/renders")
def list_renders(clip_id: str):
    return [r.public() for r in STORE.clip_renders(clip_id)]


@router.get("/clips/{clip_id}/renders/{render_id}")
def get_render(clip_id: str, render_id: str):
    r = STORE.get_render(render_id)
    if r is None or r.clip_id != clip_id:
        raise HTTPException(404, "render not found")
    return r.public()


@router.post("/clips/{clip_id}/renders/{render_id}/fix")
async def fix_render(clip_id: str, render_id: str, body: Dict[str, Any]):
    """One-click fix: re-render with the suggested adjustment applied."""
    r = STORE.get_render(render_id)
    if r is None or r.clip_id != clip_id:
        raise HTTPException(404, "render not found")
    options = dict(r.options)
    fix_options: Dict[str, Any] = {}
    warnings = (r.preflight or {}).get("warnings", [])
    target = next((w for w in warnings if w.get("id") == body.get("warning_id", "")),
                  None)
    action = (target or {}).get("fix", {}).get("action", body.get("fix", "all"))
    if action == "microcut":
        options["force_microcut_every"] = 4.0
    elif action == "duck":
        fix_options["audio"] = {"music": {"mode": "duck", "gain": 0.5}}
    elif action == "grade":
        options["grade"] = "warm"
        options["extra_grain"] = 3.0
    else:  # "all"
        options["force_microcut_every"] = 4.0
        options["grade"] = "warm"
        options["extra_grain"] = 3.0
        fix_options["audio"] = {"music": {"mode": "duck", "gain": 0.5}}
    return await create_render(clip_id, {"template": r.template,
                                         "options": options,
                                         "fix_options": fix_options})


# ---------------- media (served at /media/... — no /api prefix) -------------------

media_router = APIRouter()


@media_router.get("/media/jobs/{job_id}/preview")
def media_preview(job_id: str, request: Request):
    job = _get_job_or_404(job_id)
    path = job.preview_path or job.source_path
    if not path or not os.path.exists(path):
        raise HTTPException(404, "media not ready")
    return _range_response(path, request, "video/mp4")


@media_router.get("/media/jobs/{job_id}/stems/{layer}")
def media_stem(job_id: str, layer: str, request: Request):
    job = _get_job_or_404(job_id)
    if layer not in ("dialogue", "music", "sfx"):
        raise HTTPException(400, "bad layer")
    d = DATA_DIR / job_id
    npz = d / "stems.npz"
    if not npz.exists():
        raise HTTPException(404, "stems not ready")
    wav = d / f"stem_{layer}.wav"
    if not wav.exists():
        import numpy as np
        import wave
        data = np.load(npz)[layer]
        frames = (np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()
        with wave.open(str(wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(frames)
    return _range_response(str(wav), request, "audio/wav")


@media_router.get("/media/jobs/{job_id}/tts/{name}")
def media_tts(job_id: str, name: str, request: Request):
    job = _get_job_or_404(job_id)
    safe = Path(name).name
    p = DATA_DIR / job_id / safe
    if not p.exists():
        raise HTTPException(404, "not found")
    return _range_response(str(p), request, "audio/wav")


@media_router.get("/media/clips/{clip_id}/renders/{render_id}/out")
def media_output(clip_id: str, render_id: str, request: Request):
    r = STORE.get_render(render_id)
    if r is None or r.clip_id != clip_id or not r.output_path or not os.path.exists(r.output_path):
        raise HTTPException(404, "render not ready")
    mt = "video/quicktime" if r.output_path.endswith(".mov") else "video/mp4"
    return _range_response(r.output_path, request, mt)
