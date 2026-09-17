from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uuid
from datetime import datetime
import os
import asyncio
import shutil
from pathlib import Path

app = FastAPI(title="YouTube Clip Hanger API")

# --- CORS: allow frontend dev server + Arena preview ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In prod, restrict to your domains. For dev/Arena, allow all.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-memory job store (replace with DB in prod) ---
# Structure: {id: Job}
jobs_db = {}

CLIPS_DIR = Path("clips")
CLIPS_DIR.mkdir(exist_ok=True)

# Serve clips statically if needed
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
    """Parse HH:MM:SS, MM:SS, or seconds string to float seconds."""
    t = t.strip()
    if not t:
        return 0.0
    # If pure number
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
    """Background task to download and clip."""
    job = jobs_db.get(job_id)
    if not job:
        return
    try:
        job["status"] = "processing"
        # Try to use yt-dlp + ffmpeg if available, else mock processing
        # Check if yt-dlp is installed
        if shutil.which("yt-dlp") and shutil.which("ffmpeg"):
            # Real implementation
            import subprocess
            import tempfile
            tmpdir = tempfile.mkdtemp()
            try:
                # Download best mp4
                ydl_output = os.path.join(tmpdir, "%(title)s.%(ext)s")
                # Use yt-dlp to get info and download
                # For speed, we download only needed portion? yt-dlp doesn't clip easily, so we download then ffmpeg clip
                # Keep it simple: download and clip
                cmd_download = [
                    "yt-dlp",
                    "-f", "best[ext=mp4]/best",
                    "-o", ydl_output,
                    "--no-playlist",
                    job["url"]
                ]
                proc = await asyncio.to_thread(subprocess.run, cmd_download, capture_output=True, text=True, timeout=120)
                if proc.returncode != 0:
                    raise Exception(f"yt-dlp failed: {proc.stderr[:500]}")

                # Find downloaded file
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
                    "ffmpeg",
                    "-y",
                    "-ss", str(start_sec),
                    "-i", input_file,
                    "-t", str(duration),
                    "-c", "copy",
                    str(output_path)
                ]
                # If copy fails (keyframe issues), re-encode
                proc_clip = await asyncio.to_thread(subprocess.run, cmd_clip, capture_output=True, text=True, timeout=120)
                if proc_clip.returncode != 0:
                    # Try re-encode
                    cmd_clip2 = [
                        "ffmpeg",
                        "-y",
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
            # Mock processing for environments without yt-dlp/ffmpeg
            await asyncio.sleep(2)
            job["title"] = f"Mock clip for {job['url'][:30]}..."
            job["clip_path"] = None
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
    # Return newest first
    jobs = sorted(jobs_db.values(), key=lambda x: x["created_at"], reverse=True)
    return jobs

@app.post("/api/jobs")
async def create_job(req: CreateJobRequest):
    if not req.url or "youtube.com" not in req.url and "youtu.be" not in req.url:
        # Allow any URL for testing, but warn
        if not req.url.startswith("http"):
            raise HTTPException(status_code=400, detail="Invalid URL. Must be a YouTube link.")
    
    try:
        start_sec = parse_time_to_seconds(req.start_time)
        end_sec = parse_time_to_seconds(req.end_time)
        if end_sec <= start_sec:
            raise HTTPException(status_code=400, detail="end_time must be after start_time")
        if end_sec - start_sec > 600:
            raise HTTPException(status_code=400, detail="Clip duration max 10 minutes")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "url": req.url,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "clip_path": None,
        "title": None,
    }
    jobs_db[job_id] = job

    # Start background processing
    asyncio.create_task(process_job(job_id))

    return job

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = jobs_db.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")
    # Delete clip file if exists
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
    return {"message": "YouTube Clip Hanger API running. Frontend should proxy /api/* here."}
