from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uuid
from datetime import datetime
import os
import asyncio
import shutil
from pathlib import Path
from typing import Optional, Any, Dict
import json

app = FastAPI(title="YouTube Clip Hanger API")

# --- CORS: allow frontend dev server + Arena preview ---
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

class CreateJobRequest(BaseModel):
    url: str
    start_time: str = "00:00:00"
    end_time: str = "00:00:10"

class Job(BaseModel):
    id: str
    url: str
    start_time: str
    end_time: str
    status: str
    created_at: str
    clip_path: str | None = None
    title: str | None = None
    error: str | None = None

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

async def process_job(job_id: str):
    job = jobs_db.get(job_id)
    if not job:
        return
    try:
        job["status"] = "processing"
        url = job["url"]
        
        # Check if it's a local uploaded file
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
                # Handle relative clips path
                check_path = Path(url)
                if check_path.exists():
                    is_local_file = True
                    local_path = check_path
        except:
            pass
        
        if is_local_file and local_path:
            # Handle uploaded file - clip it if ffmpeg available, else just serve it
            await asyncio.sleep(0.5)
            job["title"] = f"Uploaded: {local_path.name}"
            # If ffmpeg available and times are not default, try to clip
            if shutil.which("ffmpeg"):
                try:
                    import subprocess
                    start_sec = parse_time_to_seconds(job["start_time"])
                    end_sec = parse_time_to_seconds(job["end_time"])
                    # Only clip if duration is specified and not full file
                    if start_sec > 0 or (end_sec - start_sec) < 600:
                        duration = max(0.1, end_sec - start_sec)
                        output_filename = f"{job_id}_{local_path.stem}.mp4"
                        output_path = CLIPS_DIR / output_filename
                        cmd_clip = [
                            "ffmpeg", "-y",
                            "-ss", str(start_sec),
                            "-i", str(local_path),
                            "-t", str(duration),
                            "-c:v", "libx264",
                            "-c:a", "aac",
                            str(output_path)
                        ]
                        proc = await asyncio.to_thread(subprocess.run, cmd_clip, capture_output=True, text=True, timeout=60)
                        if proc.returncode == 0:
                            job["clip_path"] = f"/clips/{output_filename}"
                            job["status"] = "completed"
                            return
                except Exception as e:
                    print(f"Clip failed for upload, serving original: {e}")
            # Fallback: serve original uploaded file
            job["clip_path"] = f"/clips/{local_path.name}"
            job["status"] = "completed"
        elif shutil.which("yt-dlp") and shutil.which("ffmpeg") and url.startswith("http"):
            import subprocess
            import tempfile
            tmpdir = tempfile.mkdtemp()
            try:
                ydl_output = os.path.join(tmpdir, "%(title)s.%(ext)s")
                cmd_download = [
                    "yt-dlp",
                    "-f", "best[ext=mp4]/best",
                    "-o", ydl_output,
                    "--no-playlist",
                    url
                ]
                proc = await asyncio.to_thread(subprocess.run, cmd_download, capture_output=True, text=True, timeout=120)
                if proc.returncode != 0:
                    raise Exception(f"yt-dlp failed: {proc.stderr[:500]}")
                downloaded_files = list(Path(tmpdir).glob("*"))
                if not downloaded_files:
                    raise Exception("No file downloaded")
                input_file = str(downloaded_files[0])
                start_sec = parse_time_to_seconds(job["start_time"])
                end_sec = parse_time_to_seconds(job["end_time"])
                duration = max(0.1, end_sec - start_sec)
                output_filename = f"{job_id}.mp4"
                output_path = CLIPS_DIR / output_filename
                cmd_clip = [
                    "ffmpeg", "-y",
                    "-ss", str(start_sec),
                    "-i", input_file,
                    "-t", str(duration),
                    "-c", "copy",
                    str(output_path)
                ]
                proc_clip = await asyncio.to_thread(subprocess.run, cmd_clip, capture_output=True, text=True, timeout=120)
                if proc_clip.returncode != 0:
                    cmd_clip2 = [
                        "ffmpeg", "-y",
                        "-ss", str(start_sec),
                        "-i", input_file,
                        "-t", str(duration),
                        "-c:v", "libx264",
                        "-c:a", "aac",
                        str(output_path)
                    ]
                    proc_clip2 = await asyncio.to_thread(subprocess.run, cmd_clip2, capture_output=True, text=True, timeout=120)
                    if proc_clip2.returncode != 0:
                        raise Exception(f"ffmpeg failed: {proc_clip2.stderr[:500]}")
                job["clip_path"] = f"/clips/{output_filename}"
                job["title"] = downloaded_files[0].stem
                job["status"] = "completed"
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        else:
            await asyncio.sleep(1)
            # Mock processing when ffmpeg/yt-dlp missing
            if url.startswith("http"):
                job["title"] = f"Clip for {url[:40]}... (mock - install ffmpeg for real clipping)"
                # Check why mock
                if not shutil.which("ffmpeg"):
                    job["error"] = "ffmpeg not found - install ffmpeg for real YouTube clipping. Mock completed."
                elif not shutil.which("yt-dlp"):
                    job["error"] = "yt-dlp not found - pip install yt-dlp"
            else:
                job["title"] = f"Uploaded file: {Path(url).name}"
                # If local file exists, serve it
                if Path(url).exists():
                    job["clip_path"] = f"/clips/{Path(url).name}"
                else:
                    # Try clips dir
                    possible = CLIPS_DIR / Path(url).name
                    if possible.exists():
                        job["clip_path"] = f"/clips/{possible.name}"
            job["status"] = "completed"
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        print(f"Job {job_id} failed: {e}")

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "jobs_count": len(jobs_db),
        "yt_dlp_available": bool(shutil.which("yt-dlp")),
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
    }

@app.get("/api/jobs")
async def list_jobs():
    jobs = sorted(jobs_db.values(), key=lambda x: x["created_at"], reverse=True)
    # Add compatibility fields
    result = []
    for j in jobs:
        result.append({
            **j,
            "jobId": j["id"],
            "job_id": j["id"],
        })
    return result

def extract_url_from_payload(data: Dict[str, Any]) -> tuple[Optional[str], str, str]:
    """
    Try to extract url/start/end from various frontend formats.
    Supports:
    - {"url": "...", "start_time": "...", "end_time": "..."}
    - {"youtubeUrl": "..."} / {"youtube_url": "..."}
    - {"source": {"type": "youtube", "url": "..."}} 
    - {"source": {"type": "upload", "file": "..."}} -> will be handled as upload
    - {"url": "...", "source": {...}}
    Returns (url, start_time, end_time)
    """
    if not isinstance(data, dict):
        return None, "00:00:00", "00:00:10"
    
    # Direct url
    url = data.get("url") or data.get("youtubeUrl") or data.get("youtube_url") or data.get("link")
    
    # Source nested
    source = data.get("source")
    if isinstance(source, dict):
        # source may contain url
        if not url:
            url = source.get("url") or source.get("youtubeUrl") or source.get("link")
        # If upload type and no url, check if file path provided
        if not url and source.get("type") == "upload":
            # Could be file upload handled separately, but try to get file name
            url = source.get("fileName") or source.get("name") or source.get("file")
    
    start_time = data.get("start_time") or data.get("startTime") or data.get("start") or "00:00:00"
    end_time = data.get("end_time") or data.get("endTime") or data.get("end") or "00:00:10"
    
    # Also check source for times
    if isinstance(source, dict):
        if start_time == "00:00:00":
            start_time = source.get("start_time") or source.get("startTime") or start_time
        if end_time == "00:00:10":
            end_time = source.get("end_time") or source.get("endTime") or end_time
    
    return url, start_time, end_time

@app.post("/api/jobs")
async def create_job(request: Request):
    """
    Flexible endpoint that accepts:
    - JSON: {"url": "...", "start_time": "...", "end_time": "..."}
    - JSON: {"source": {"type": "youtube", "url": "..."}}
    - JSON: {"source": {"type": "upload"}} + file upload (multipart)
    - Form: url, start_time, end_time, file
    """
    content_type = request.headers.get("content-type", "")
    data: Dict[str, Any] = {}
    uploaded_file: Optional[UploadFile] = None
    
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            # Convert form to dict
            for key, value in form.items():
                if isinstance(value, UploadFile):
                    uploaded_file = value
                else:
                    data[key] = value
            # Also try to parse source if it's JSON string
            if "source" in data and isinstance(data["source"], str):
                try:
                    data["source"] = json.loads(data["source"])
                except:
                    pass
        else:
            # Try JSON
            try:
                data = await request.json()
            except:
                # Try form urlencoded
                try:
                    form = await request.form()
                    data = dict(form)
                except:
                    data = {}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse request: {e}")
    
    print(f"Received job data: {data}")
    
    url, start_time, end_time = extract_url_from_payload(data)
    
    # Handle file upload
    if uploaded_file:
        # Save uploaded file
        try:
            file_ext = Path(uploaded_file.filename).suffix or ".mp4"
            saved_name = f"upload_{uuid.uuid4().hex[:8]}{file_ext}"
            saved_path = CLIPS_DIR / saved_name
            with open(saved_path, "wb") as f:
                content = await uploaded_file.read()
                f.write(content)
            # Use saved path as url for processing
            if not url:
                url = str(saved_path)
            else:
                # If url also provided, prefer uploaded file
                url = str(saved_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to save upload: {e}")
    
    # If still no url, check if it's an upload type without file (frontend bug)
    if not url:
        source = data.get("source")
        if isinstance(source, dict) and source.get("type") == "upload":
            raise HTTPException(
                status_code=422, 
                detail="Upload type requires a file. Frontend sent source.type=upload but no file or url. Please send either: 1) {'url': 'https://youtube.com/...'} or 2) multipart form with file. See /docs for examples."
            )
        raise HTTPException(
            status_code=422, 
            detail="Field 'url' required. Expected format: {'url': 'https://www.youtube.com/watch?v=...', 'start_time': '00:00:05', 'end_time': '00:00:15'} or form-data with url field."
        )
    
    # Validate times
    try:
        start_sec = parse_time_to_seconds(str(start_time))
        end_sec = parse_time_to_seconds(str(end_time))
        if end_sec <= start_sec:
            raise HTTPException(status_code=400, detail="end_time must be after start_time")
        if end_sec - start_sec > 600:
            raise HTTPException(status_code=400, detail="Clip duration max 10 minutes")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    
    # Basic url validation - allow http urls or local file paths (for uploads)
    if isinstance(url, str) and url.startswith("http"):
        if "youtube.com" not in url and "youtu.be" not in url:
            # Allow any http for testing, but log
            print(f"Warning: non-youtube url: {url}")
    elif not Path(url).exists() and not url.startswith("http"):
        # If it's not http and not existing file, still allow but warn
        print(f"Warning: url is not http and file doesn't exist: {url}")
    
    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "jobId": job_id,  # compatibility for frontends expecting jobId
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
    # Return with compatibility fields
    return {
        **job,
        "jobId": job_id,
        "job_id": job_id,
        "id": job_id,
    }

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    # Handle undefined string from buggy frontend
    if job_id == "undefined" or job_id == "null":
        raise HTTPException(status_code=400, detail="Job ID is undefined. Frontend bug: expected id but got undefined. Make sure backend returns id field and frontend uses data.id or data.jobId")
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {
        **job,
        "jobId": job["id"],
        "job_id": job["id"],
    }

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
        except Exception:
            pass
    del jobs_db[job_id]
    return {"deleted": True}

@app.get("/")
async def root():
    return {"message": "YouTube Clip Hanger API running. Frontend should proxy /api/* here.", "docs": "/docs"}
