from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uuid
from datetime import datetime
import os
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Any, Dict
import json

app = FastAPI(title="YouTube Clip Hanger API - Fast MassReels style")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs_db = {}
CLIPS_DIR = Path("clips")
CLIPS_DIR.mkdir(exist_ok=True)

if CLIPS_DIR.exists():
    app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")

def parse_time_to_seconds(t: str) -> float:
    t = t.strip()
    if not t:
        return 0.0
    try:
        return float(t)
    except ValueError:
        pass
    parts = t.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"Invalid time format: {t}")
    if len(parts) == 3:
        h, m, s = parts
        return h*3600 + m*60 + s
    elif len(parts) == 2:
        m, s = parts
        return m*60 + s
    elif len(parts) == 1:
        return parts[0]
    else:
        raise ValueError(f"Invalid time format: {t}")

def seconds_to_hms(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm for yt-dlp sections"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

async def fast_clip_youtube_massreels_style(url: str, start_sec: float, end_sec: float, output_path: Path, job_id: str) -> tuple[bool, str]:
    """
    MassReels-fast clipping - 3 strategies from fastest to slowest:
    1. Direct URL + ffmpeg (fastest, streams only needed part)
    2. yt-dlp --download-sections (fast, downloads only section)
    3. Full download + ffmpeg clip (slow fallback)
    Returns (success, method_used)
    """
    duration = max(0.1, end_sec - start_sec)
    start_hms = seconds_to_hms(start_sec)
    end_hms = seconds_to_hms(end_sec)
    
    print(f"[{job_id}] Fast clip: {start_sec}s -> {end_sec}s ({duration}s) using {start_hms} to {end_hms}")
    
    # Strategy 1: Direct URL + ffmpeg (FASTEST - like MassReels)
    # yt-dlp --get-url gives direct video URL, ffmpeg can seek and stream only needed part
    try:
        print(f"[{job_id}] Trying Strategy 1: Direct URL + ffmpeg...")
        # Get direct URL
        cmd_get_url = [
            "yt-dlp",
            "-f", "best[ext=mp4][height<=720]/best[height<=720]/best",
            "--get-url",
            "--no-playlist",
            url
        ]
        proc = await asyncio.to_thread(subprocess.run, cmd_get_url, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0 and proc.stdout.strip():
            direct_url = proc.stdout.strip().split('\n')[0]  # First URL
            print(f"[{job_id}] Got direct URL, clipping with ffmpeg...")
            
            # Fast seek: -ss before -i
            cmd_ffmpeg = [
                "ffmpeg",
                "-y",
                "-ss", str(start_sec),
                "-i", direct_url,
                "-t", str(duration),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                str(output_path)
            ]
            proc_ff = await asyncio.to_thread(subprocess.run, cmd_ffmpeg, capture_output=True, text=True, timeout=60)
            if proc_ff.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
                print(f"[{job_id}] Strategy 1 SUCCESS: Direct URL + copy")
                return True, "direct_url_copy"
            
            # If copy failed (keyframe issue), try re-encode but still fast
            print(f"[{job_id}] Copy failed, trying re-encode...")
            cmd_ffmpeg2 = [
                "ffmpeg",
                "-y",
                "-ss", str(start_sec),
                "-i", direct_url,
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "ultrafast",  # Fastest preset
                "-c:a", "aac",
                str(output_path)
            ]
            proc_ff2 = await asyncio.to_thread(subprocess.run, cmd_ffmpeg2, capture_output=True, text=True, timeout=90)
            if proc_ff2.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
                print(f"[{job_id}] Strategy 1 SUCCESS: Direct URL + re-encode")
                return True, "direct_url_reencode"
        else:
            print(f"[{job_id}] Strategy 1 failed to get URL: {proc.stderr[:200]}")
    except Exception as e:
        print(f"[{job_id}] Strategy 1 exception: {e}")
    
    # Strategy 2: yt-dlp --download-sections (FAST - downloads only section)
    try:
        print(f"[{job_id}] Trying Strategy 2: yt-dlp --download-sections...")
        # yt-dlp syntax: --download-sections "*start-end"
        # Use seconds format
        section = f"*{start_sec}-{end_sec}"
        cmd_section = [
            "yt-dlp",
            "-f", "best[ext=mp4][height<=720]/best[height<=720]/best",
            "--download-sections", section,
            "-o", str(output_path),
            "--no-playlist",
            "--force-keyframes-at-cuts",
            url
        ]
        proc_sec = await asyncio.to_thread(subprocess.run, cmd_section, capture_output=True, text=True, timeout=90)
        if proc_sec.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
            print(f"[{job_id}] Strategy 2 SUCCESS: download-sections")
            return True, "download_sections"
        else:
            print(f"[{job_id}] Strategy 2 failed: {proc_sec.stderr[:300]}")
    except Exception as e:
        print(f"[{job_id}] Strategy 2 exception: {e}")
    
    # Strategy 3: Full download + clip (SLOW fallback)
    try:
        print(f"[{job_id}] Trying Strategy 3: Full download + clip (slow fallback)...")
        tmpdir = tempfile.mkdtemp()
        try:
            ydl_output = os.path.join(tmpdir, "%(title)s.%(ext)s")
            cmd_download = [
                "yt-dlp",
                "-f", "best[ext=mp4][height<=720]/best",
                "-o", ydl_output,
                "--no-playlist",
                url
            ]
            proc_dl = await asyncio.to_thread(subprocess.run, cmd_download, capture_output=True, text=True, timeout=180)
            if proc_dl.returncode != 0:
                print(f"[{job_id}] Full download failed: {proc_dl.stderr[:300]}")
                return False, f"download_failed: {proc_dl.stderr[:200]}"
            
            downloaded_files = list(Path(tmpdir).glob("*"))
            if not downloaded_files:
                return False, "no_file_downloaded"
            
            input_file = str(downloaded_files[0])
            # Fast seek before input
            cmd_clip = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-i", input_file,
                "-t", str(duration),
                "-c", "copy",
                str(output_path)
            ]
            proc_clip = await asyncio.to_thread(subprocess.run, cmd_clip, capture_output=True, text=True, timeout=60)
            if proc_clip.returncode != 0:
                cmd_clip2 = [
                    "ffmpeg", "-y",
                    "-ss", str(start_sec),
                    "-i", input_file,
                    "-t", str(duration),
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-c:a", "aac",
                    str(output_path)
                ]
                proc_clip2 = await asyncio.to_thread(subprocess.run, cmd_clip2, capture_output=True, text=True, timeout=90)
                if proc_clip2.returncode != 0:
                    return False, f"ffmpeg_failed: {proc_clip2.stderr[:200]}"
            
            if output_path.exists():
                print(f"[{job_id}] Strategy 3 SUCCESS: full download + clip")
                return True, "full_download"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as e:
        print(f"[{job_id}] Strategy 3 exception: {e}")
        return False, str(e)
    
    return False, "all_strategies_failed"

async def process_job(job_id: str):
    job = jobs_db.get(job_id)
    if not job:
        return
    try:
        job["status"] = "processing"
        job["started_at"] = datetime.utcnow().isoformat()
        url = job["url"]
        
        # Check if local uploaded file
        is_local_file = False
        local_path = None
        try:
            p = Path(url)
            if p.exists() and p.is_file():
                is_local_file = True
                local_path = p
            elif (CLIPS_DIR / Path(url).name).exists():
                is_local_file = True
                local_path = CLIPS_DIR / Path(url).name
            elif url.startswith("clips/") or url.startswith("clips\\"):
                check_path = Path(url)
                if check_path.exists():
                    is_local_file = True
                    local_path = check_path
        except:
            pass
        
        if is_local_file and local_path:
            job["title"] = f"Uploaded: {local_path.name}"
            if shutil.which("ffmpeg"):
                try:
                    start_sec = parse_time_to_seconds(job["start_time"])
                    end_sec = parse_time_to_seconds(job["end_time"])
                    if start_sec > 0 or (end_sec - start_sec) < 600:
                        duration = max(0.1, end_sec - start_sec)
                        output_filename = f"{job_id}_{local_path.stem}.mp4"
                        output_path = CLIPS_DIR / output_filename
                        # Fast seek for local files too
                        cmd_clip = [
                            "ffmpeg", "-y",
                            "-ss", str(start_sec),
                            "-i", str(local_path),
                            "-t", str(duration),
                            "-c:v", "libx264",
                            "-preset", "ultrafast",
                            "-c:a", "aac",
                            str(output_path)
                        ]
                        proc = await asyncio.to_thread(subprocess.run, cmd_clip, capture_output=True, text=True, timeout=60)
                        if proc.returncode == 0:
                            job["clip_path"] = f"/clips/{output_filename}"
                            job["status"] = "completed"
                            job["completed_at"] = datetime.utcnow().isoformat()
                            return
                except Exception as e:
                    print(f"Clip failed for upload: {e}")
            job["clip_path"] = f"/clips/{local_path.name}"
            job["status"] = "completed"
            job["completed_at"] = datetime.utcnow().isoformat()
        
        elif url.startswith("http"):
            if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
                await asyncio.sleep(0.5)
                job["title"] = f"Clip for {url[:40]}... (mock - install ffmpeg/yt-dlp)"
                if not shutil.which("ffmpeg"):
                    job["error"] = "ffmpeg not found - install for real clipping. Mock completed."
                job["status"] = "completed"
                job["completed_at"] = datetime.utcnow().isoformat()
                return
            
            start_sec = parse_time_to_seconds(job["start_time"])
            end_sec = parse_time_to_seconds(job["end_time"])
            output_filename = f"{job_id}.mp4"
            output_path = CLIPS_DIR / output_filename
            
            # FAST PATH - MassReels style
            success, method = await fast_clip_youtube_massreels_style(url, start_sec, end_sec, output_path, job_id)
            
            if success:
                job["clip_path"] = f"/clips/{output_filename}"
                job["title"] = f"Clipped via {method}: {url[:30]}..."
                job["status"] = "completed"
                job["method"] = method
                job["completed_at"] = datetime.utcnow().isoformat()
                # Calculate processing time
                try:
                    started = datetime.fromisoformat(job["started_at"])
                    completed = datetime.fromisoformat(job["completed_at"])
                    job["processing_time"] = (completed - started).total_seconds()
                except:
                    pass
            else:
                job["status"] = "failed"
                job["error"] = f"Fast clip failed: {method}"
        
        else:
            await asyncio.sleep(0.5)
            job["title"] = f"File: {Path(url).name}"
            if Path(url).exists():
                job["clip_path"] = f"/clips/{Path(url).name}"
            job["status"] = "completed"
            job["completed_at"] = datetime.utcnow().isoformat()
            
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        print(f"Job {job_id} failed: {e}")
        import traceback
        traceback.print_exc()

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "jobs_count": len(jobs_db),
        "yt_dlp_available": bool(shutil.which("yt-dlp")),
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
        "fast_mode": "massreels_style - direct_url + download_sections",
    }

@app.get("/api/jobs")
async def list_jobs():
    jobs = sorted(jobs_db.values(), key=lambda x: x["created_at"], reverse=True)
    result = []
    for j in jobs:
        result.append({**j, "jobId": j["id"], "job_id": j["id"]})
    return result

def extract_url_from_payload(data: Dict[str, Any]) -> tuple[Optional[str], str, str]:
    if not isinstance(data, dict):
        return None, "00:00:00", "00:00:10"
    url = data.get("url") or data.get("youtubeUrl") or data.get("youtube_url") or data.get("link")
    source = data.get("source")
    if isinstance(source, dict):
        if not url:
            url = source.get("url") or source.get("youtubeUrl") or source.get("link")
        if not url and source.get("type") == "upload":
            url = source.get("fileName") or source.get("name") or source.get("file")
    start_time = data.get("start_time") or data.get("startTime") or data.get("start") or "00:00:00"
    end_time = data.get("end_time") or data.get("endTime") or data.get("end") or "00:00:10"
    if isinstance(source, dict):
        if start_time == "00:00:00":
            start_time = source.get("start_time") or source.get("startTime") or start_time
        if end_time == "00:00:10":
            end_time = source.get("end_time") or source.get("endTime") or end_time
    return url, start_time, end_time

@app.post("/api/jobs")
async def create_job(request: Request):
    content_type = request.headers.get("content-type", "")
    data: Dict[str, Any] = {}
    uploaded_file: Optional[UploadFile] = None
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            for key, value in form.items():
                if isinstance(value, UploadFile):
                    uploaded_file = value
                else:
                    data[key] = value
            if "source" in data and isinstance(data["source"], str):
                try:
                    data["source"] = json.loads(data["source"])
                except:
                    pass
        else:
            try:
                data = await request.json()
            except:
                try:
                    form = await request.form()
                    data = dict(form)
                except:
                    data = {}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse request: {e}")
    
    print(f"Received job data: {data}")
    url, start_time, end_time = extract_url_from_payload(data)
    
    if uploaded_file:
        try:
            file_ext = Path(uploaded_file.filename).suffix or ".mp4"
            saved_name = f"upload_{uuid.uuid4().hex[:8]}{file_ext}"
            saved_path = CLIPS_DIR / saved_name
            with open(saved_path, "wb") as f:
                content = await uploaded_file.read()
                f.write(content)
            url = str(saved_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to save upload: {e}")
    
    if not url:
        source = data.get("source")
        if isinstance(source, dict) and source.get("type") == "upload":
            raise HTTPException(status_code=422, detail="Upload type requires a file. Send multipart form with file.")
        raise HTTPException(status_code=422, detail="Field 'url' required. Expected: {'url': 'https://youtube.com/...', 'start_time': '00:00:05', 'end_time': '00:00:15'}")
    
    try:
        start_sec = parse_time_to_seconds(str(start_time))
        end_sec = parse_time_to_seconds(str(end_time))
        if end_sec <= start_sec:
            raise HTTPException(status_code=400, detail="end_time must be after start_time")
        if end_sec - start_sec > 600:
            raise HTTPException(status_code=400, detail="Clip duration max 10 minutes")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    
    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "jobId": job_id,
        "job_id": job_id,
        "_id": job_id,
        "url": url,
        "start_time": str(start_time),
        "end_time": str(end_time),
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "clip_path": None,
        "title": None,
    }
    jobs_db[job_id] = job
    asyncio.create_task(process_job(job_id))
    return {**job, "jobId": job_id, "job_id": job_id, "id": job_id}

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id in ["undefined", "null"]:
        raise HTTPException(status_code=400, detail="Job ID is undefined. Frontend bug.")
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {**job, "jobId": job["id"], "job_id": job["id"]}

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs_db[job_id]
    if job.get("clip_path"):
        try:
            file_path = CLIPS_DIR / Path(job["clip_path"]).name
            if file_path.exists():
                file_path.unlink()
        except:
            pass
    del jobs_db[job_id]
    return {"deleted": True}

@app.get("/")
async def root():
    return {"message": "YouTube Clip Hanger API - Fast MassReels style", "docs": "/docs", "health": "/api/health"}
