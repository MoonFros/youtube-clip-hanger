# youtube-clip-hanger

Clip YouTube videos by timestamp. Full-stack app with Next.js frontend + FastAPI backend.

## The Fix for `ECONNREFUSED 127.0.0.1:8000`

Your error:

```
Failed to proxy http://127.0.0.1:8000/api/health Error: connect ECONNREFUSED 127.0.0.1:8000
Failed to proxy http://127.0.0.1:8000/api/jobs Error: connect ECONNREFUSED 127.0.0.1:8000
```

**Root cause:** Frontend (Next.js on port 3000) is running, but backend (FastAPI on port 8000) is NOT running. Next.js `rewrites()` in `next.config.mjs` tries to proxy `/api/*` to `127.0.0.1:8000`, fails.

### Solution

1. **Backend must bind to `0.0.0.0:8000`** (not `127.0.0.1`), so it’s reachable inside container:
   ```bash
   python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Frontend must bind to `0.0.0.0:3000`** for Arena preview:
   ```bash
   npm run dev -- -H 0.0.0.0 -p 3000
   # or
   npm run dev:frontend
   ```

3. **Run BOTH together** (recommended):
   ```bash
   npm install
   pip install -r backend/requirements.txt
   npm run dev:all
   ```
   This uses `concurrently` to start backend + frontend in one terminal.

   Or run in two terminals:
   - Terminal 1: `npm run dev:backend`
   - Terminal 2: `npm run dev:frontend`

4. **Arena preview fix**: Added `allowedDevOrigins: ['*.e2b.app']` in `next.config.mjs` and CORS `allow_origins=["*"]` in FastAPI. Frontend uses relative URLs `/api/...` so browser never calls `localhost` directly — Next.js server proxies it.

### Verify backend is REALLY running (Windows & Mac)

**What success looks like:** When backend starts, you MUST see this in terminal:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started server process [....]
INFO:     Application startup complete.
```
If you don't see that, backend is NOT running.

**Windows PowerShell (your case):**

Your command `cd backend>> ./run.sh` is wrong:
- `>>` means "redirect output to file" in PowerShell/Bash, not "run"
- `./run.sh` is a Bash script, won't work in PowerShell by default
- And there was no `run.sh` before - now I added it

Correct Windows steps (from repo ROOT `C:\...\youtube-clip-hanger`):

```powershell
# 1. From root, NOT inside backend folder
cd C:\Users\HP\Desktop\cobeunh\youtube-clip-hanger

# 2. Install deps
pip install -r backend\requirements.txt

# 3. Run backend (this is the real command)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# You should see "Uvicorn running on http://0.0.0.0:8000"
# Leave this terminal running!

# 4. Open SECOND terminal for frontend
cd C:\Users\HP\Desktop\cobeunh\youtube-clip-hanger
npm install
npm run dev:frontend
```

Or just double-click `run.bat` in root - I added it for Windows.

Or use one-terminal mode:
```powershell
npm run dev:all
```

**How to check:**
- Browser: http://localhost:8000/api/health  should show `{"status":"ok",...}`
- Browser: http://localhost:8000/docs  should show Swagger UI
- Frontend: http://localhost:3000 should show green dot "API OK"
- PowerShell: `curl http://127.0.0.1:8000/api/health` or `Invoke-RestMethod http://localhost:8000/api/health`

If you see `ECONNREFUSED` again, backend terminal is not running or crashed.

## Dev

```bash
npm install
pip install -r backend/requirements.txt
# optional: ffmpeg + yt-dlp for real clipping
# sudo apt-get install ffmpeg
# pip already installs yt-dlp

npm run dev:all
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000/api/health
- In Arena: preview URL will be `https://3000-<id>.e2b.app`

## API

- `GET /api/health` -> {status: ok}
- `GET /api/jobs` -> list
- `POST /api/jobs` {url, start_time, end_time} -> create job
- `GET /api/jobs/{id}` -> job status
- Clips served at `/clips/{id}.mp4` if ffmpeg available, otherwise mocked as completed.

## Structure

- `app/page.tsx` - Main UI
- `next.config.mjs` - Proxy rewrites + allowedDevOrigins
- `backend/main.py` - FastAPI
- `clips/` - Output folder (gitignored)
