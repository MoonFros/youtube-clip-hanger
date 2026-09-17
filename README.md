# ✂️ FairClip

**Turn long videos into Shorts / Reels / TikToks with automatic Fair Use transformations.**

Upload a video (or a YouTube URL / direct link) → FairClip finds the best 15–60s
moments, reframes them to 9:16, separates **dialogue / music / SFX**, adds dynamic
word captions, and applies the Fair Use stack automatically: 9:16 reframe with
letterbox removal, micro-cuts every ≤7s, music ducked to 15–20% (or micro-silence
gaps / CC0 ambient), plus an AI-voiced **hook intro + CTA outro** (Breakdown
Bookend). A built-in **pre-flight check** scores every render 0–100 against
content-ID similarity and lists one-click fixes.

- **6 templates**: Cinematic Zoom · Split Screen · Caption Storm · Reaction Frame · Minimal Clean · Breakdown Bookend
- **Audio intelligence**: per-layer waveform in the timeline, solo previews, mode + gain per layer (keep / duck / mute / silence-gaps / replace)
- **Bookend**: 3 hook styles (Trivia / Emotional / Curiosity) + auto, 5 AI voices, **or record your own mic** (3s)
- **Export**: 720p/1080p, 30/60 fps, MP4/MOV, watermark toggle
- **Tiers**: Free (5 clips/day, 60s max, 720p, watermark) · Pro $9 (1080p, no watermark)
- **No ffmpeg, no database, no external services required** — PyAV + numpy/PIL do all
  video work. A system `ffmpeg` is used automatically when it is on `PATH`: it only
  makes the heavy stages (preview transcode, audio extraction, scene detection)
  5–20× faster. Whisper/ElevenLabs/LLM hooks are optional upgrades with offline fallbacks

---

## 1) Run locally (one command)

Prereqs: **Python 3.11+** and **Node 20+**.

```bash
git clone https://github.com/MoonFros/youtube-clip-hanger.git
cd youtube-clip-hanger
./run.sh          # macOS/Linux      (Windows: double-click run.bat)
```

That creates `backend/.venv`, installs both dependency sets, then starts:

| Service | URL | Notes |
|---|---|---|
| Web UI | http://localhost:3000 | Next.js, proxies `/api` + `/media` to the backend |
| API | http://localhost:8000/api/health | FastAPI (docs at `/docs`) |

→ Open **http://localhost:3000**, click **🎬 Demo video → Clip the demo**
(the synthetic demo is rendered on first use — a few minutes, with live progress)
or **⬆️ Upload** your own `.mp4 / .mkv / .webm / .mov`.

Useful variants: `./run.sh backend` / `./run.sh web` (one service), and
`cd backend && ./run.sh` if you only want the API. While editing backend code,
`FAIRCLIP_RELOAD=1 ./run.sh` (or `set FAIRCLIP_RELOAD=1` on Windows) restarts
the API on every change — the UI rides through those restarts.

Optional extras (both are strictly optional):

```bash
# 1. offline word-level captions (downloads a ~150 MB model on first use)
backend/.venv/bin/pip install -r backend/requirements-ai.txt

# 2. a system ffmpeg — the single biggest speed-up for long videos
#    Windows: winget install Gyan.FFmpeg     macOS: brew install ffmpeg
#    Linux:   sudo apt install ffmpeg

export OPENAI_API_KEY=sk-...        # cloud transcription + LLM hook writing
export ELEVENLABS_API_KEY=el-...    # premium TTS voices
```

## 2) Run locally (Docker — one command)

```bash
cp .env.example .env                # optional keys
docker compose up -d --build
```
→ **http://localhost:3000** (api on localhost:8000). Data lives in the
`fairclip_data` volume (auto-cleaned after 24 h).

---

## 3) Deploy online — Vercel (frontend) + Render (backend)  · free tiers

> The browser talks **directly** to the Render API (CORS is open), so uploads and
> video streaming bypass Vercel's request-size limits entirely.

### Step 1 — Backend on Render
1. Render dashboard → **New → Web Service** → pick your repo.
2. **Root Directory**: `backend` (Render auto-detects the Dockerfile).
3. **Instance**: Free (see caveats below).
4. **Health Check Path**: `/api/health`
5. Environment (all optional): `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`.
6. Deploy. Note the URL, e.g. `https://fairclip-api-xxxx.onrender.com`.

### Step 2 — Frontend on Vercel
1. Vercel → **Add New → Project** → import the same repo.
2. **Root Directory**: `frontend`. Framework preset: Next.js (auto).
3. Environment Variables (add to *Production* and *Preview*):
   ```
   NEXT_PUBLIC_API_BASE=https://fairclip-api-xxxx.onrender.com
   ```
4. Deploy. Done — your Vercel URL is the app.

### Free-tier caveats (be aware before you demo)
| Service | Free plan reality |
|---|---|
| **Render** | Spins down after ~15 min idle → first request after idle takes ~30–60 s (the job progress screen hides this fine). 512 MB RAM, 750 h/month. |
| **Render disk** | **Ephemeral**: `/app/data` is wiped on every redeploy/restart. The demo video regenerates itself automatically, but uploaded videos and finished renders are lost on restart. For real use, attach a **Persistent Disk** ($1–7/mo) at `/app/data`. |
| **Upload size** | Render free plan caps request bodies at ~10 MB — keep uploads small on the free plan (paid instances allow much larger files). |
| **Vercel** | Generous: static + rewrites are fine. Nothing needed beyond the env var. |

This combo is great for **showcasing and light personal use** (demo clip,
small files). For daily heavy use, use the single-VPS setup below or a $7/mo
Render instance with a persistent disk.

---

## 4) Deploy online — single VPS (recommended for real use, ~$5–10/mo)

Any Ubuntu 22.04/24.04 box with **4 GB+ RAM, 2–4 vCPU** (Hetzner, DigitalOcean,
Vultr…):

```bash
curl -fsSL https://get.docker.com | sh                    # 1. Docker
git clone https://github.com/MoonFros/youtube-clip-hanger.git && cd youtube-clip-hanger
cp .env.example .env                                       # 2. optional keys
docker compose up -d --build                               # 3. build & start
docker compose logs -f                                     #    watch until healthy

sudo apt install -y caddy                                  # 4. TLS proxy
sudo nano deploy/Caddyfile                                 #    put your domain in it
# point the DNS A record at the server IP, then:
sudo systemctl enable --now caddy
sudo caddy reload --config deploy/Caddyfile
```

→ **https://your-domain.com** — automatic Let's Encrypt, uploads up to 2 GB.
(No domain yet? Change the two `ports:` in `docker-compose.yml` to
`"8000:8000"` / `"3000:3000"` and use `http://your-ip:3000` — no TLS.)

**Rule of thumb**: one `api` instance per box (video rendering is CPU-bound,
~1.2–4× realtime at 720p). Scale by adding boxes behind a load balancer later.

---

## Environment variables

| Variable | Where | Default | Purpose |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE` | frontend build | `""` (same-origin proxy) | Direct API URL — set to your Render/VPS API URL when the frontend is hosted elsewhere (Vercel) |
| `FAIRCLIP_BACKEND` | frontend build (Docker) | `http://127.0.0.1:8000` | Same-origin proxy target for docker-compose/local builds |
| `OPENAI_API_KEY` | backend | — | Whisper transcription + LLM hook writing (optional) |
| `OPENAI_BASE_URL` | backend | OpenAI | Use any compatible endpoint (optional) |
| `ELEVENLABS_API_KEY` | backend | — | Premium TTS voices (optional) |
| `FAIRCLIP_WHISPER_MODEL` | backend | `base` | Whisper size: tiny/base/small/medium |
| `FAIRCLIP_DATA` | backend | `./data` | Where jobs/media are stored |
| `FAIRCLIP_FFMPEG` | backend | auto-detected | Explicit `ffmpeg` path (if it is not on `PATH`) |
| `FAIRCLIP_YTDLP_MAX_HEIGHT` | backend | `720` | Max source height downloaded from YouTube |
| `FAIRCLIP_YTDLP_FORMAT` | backend | sensible ladder | Override the yt-dlp format selector entirely |
| `FAIRCLIP_COOKIES_FROM_BROWSER` | backend | — | `chrome`/`edge`/`firefox`: use browser cookies (fixes bot checks) |
| `FAIRCLIP_COOKIES_FILE` | backend | — | Path to a Netscape cookies.txt instead |
| `FAIRCLIP_MAX_SOURCE_MINUTES` | backend | `0` (all) | Only download the first N minutes of long videos |
| `FAIRCLIP_STEMS_LONG_AFTER_S` | backend | `900` | Videos longer than this use the fast 16 kHz stem analysis |
| `FAIRCLIP_STEMS_BLOCK_S` | backend | `20` | Stem analysis block size (memory/speed trade-off) |
| `FAIRCLIP_WHISPER_DOWNLOAD` | backend | `1` | Set `0` to never auto-download the local Whisper model |
| `FAIRCLIP_YTDLP_EXTRA_ARGS` | backend | — | `key=value,key=value` escape hatch for any yt-dlp option |

Everything runs with **zero keys** — you just paste transcripts instead of
auto-transcription, and the offline voice narrates the bookend.

## The flow (what the app does)

1. **Ingest** — upload / YouTube (yt-dlp) / direct link / synthetic demo
2. **Analyze** — scene-change detection, letterbox detection, 1200-bucket
   waveform, STFT + harmonic-percussive **stem separation** (dialogue/music/sfx)
3. **Transcribe** — Whisper (API key) or pasted text → word-level timestamps
4. **Suggest** — 5–10 scored 15–60s highlight windows (or full-video fallback)
5. **Edit** — drag timeline handles (scene snap), pick a template, tune audio
   layers, generate the AI bookend (or record your mic)
6. **Render** — 9:16 composite with micro-cuts ≤7s, captions, grade/grain,
   music ducked to 15–20%, TTS-injected bookend, watermark per tier
7. **Pre-flight** — dHash similarity timeline vs source, music-level check,
   0–100 Fair Use score, one-click fixes (re-cut / re-duck / re-grade)

## Project structure

```
backend/            FastAPI app
  app/
    engine.py       PyAV decode/encode/mux + optional ffmpeg fast paths
    analysis.py     scenes, letterbox, waveform, clip suggestion
    stems.py        STFT + HPSS dialogue/music/sfx separation
    render.py       6 template compositors, micro-cut engine, audio plan
    captions.py     word-level caption rendering (PIL)
    hooks.py        hook/outro script generation (rule-based, LLM if key)
    tts.py          ElevenLabs → OpenAI → offline meSpeak chain
    preflight.py    similarity timeline, 0-100 score, warnings + fixes
    ingest.py       job pipeline (upload/url/link/demo)
    demo.py         synthetic 100s demo video generator
    api.py / main.py
  tts/              vendored meSpeak (Node) — offline TTS
  tests/            E2E pipeline + all-templates render tests
frontend/           Next.js 14 (App Router) editor
  app/              landing, job progress, editor
  components/       PhonePreview, Timeline (canvas), panel tabs
DEPLOYMENT.md       deeper deployment notes (Railway, Fly.io, ops, scaling)
legacy/             the abandoned first-iteration clipper — do not run on :8000
docker-compose.yml  single-machine production setup
deploy/Caddyfile    TLS reverse proxy
```

## Tests

```bash
cd backend
.venv/bin/python tests/mk_testvideo.py      # 12s synthetic source
.venv/bin/python tests/ingest_smoke.py      # ingest stages + timings + cancel
.venv/bin/python tests/pipeline_test.py     # full job → render → preflight
.venv/bin/python tests/tpl_test.py          # all 6 templates end-to-end
```

## Troubleshooting

### “Uploads fail with 422 / settings 404 / the progress bar never finishes”
You are almost certainly talking to the **legacy single-file backend** from the
first iteration of this project (`uvicorn backend.main:app`, the old `run.bat`) —
it also binds port 8000 but speaks a completely different API, so the UI gets
404/422 responses and jobs that never reach the `ready` state the UI waits for.

It now lives in [`legacy/`](legacy/README.md) and must not run on 8000. Stop it,
then start the app with `./run.sh` / `run.bat`. The web UI detects the wrong
backend and shows a red banner if it happens again.

### Frontend log: `Failed to proxy http://127.0.0.1:8000/api/… Error: socket hang up (ECONNRESET)`
That message comes from the **Next.js dev server**, not from FairClip: its proxy
lost the connection to the API on port 8000 while forwarding a browser request.
It is almost always one of these:

1. **A stale backend from before the cleanup is still running.** If you ever
   started the old app (`uvicorn backend.main:app --reload`, or `run.bat` from an
   older checkout), that process is gone from the repo now — `--reload` crashes
   as soon as it tries to reload, the port accepts and immediately drops
   connections, and every `/api` call fails exactly like this. Close every old
   terminal (`Ctrl+C`), check for leftovers with
   `netstat -ano | findstr :8000`, then start fresh with `run.bat` / `./run.sh`.
2. **The backend was restarted or is still booting.** Requests during a restart
   fail; the UI reconnects by itself (it re-checks `/api/health` every 10s and
   shows a red banner with a **Retry now** button meanwhile).
3. **A keep-alive race in dev** — uvicorn's default 5s idle timeout can close a
   connection exactly when Next reuses it. The bundled scripts start uvicorn with
   `--timeout-keep-alive 75` to avoid it.

Quick check:
```bash
curl http://localhost:8000/api/health
# {"ok":true,...}                      -> backend fine, ignore the proxy noise
# {"detail":"Not Found"} / connection refused / empty -> it is not running
```
The UI also tells you which side is broken: an **old backend** is detected (it
answers `/api/health` with a different shape) and reported in a red banner.

### “A YouTube download takes forever”
Order of stages for a URL job: **download → probe → preview transcode → scenes →
audio profile → stems → transcript**. Every stage now reports a percentage and a
detail line (`12/48 MB · 3.1 MB/s · ETA 1:20`), so you can always see what it is
doing — and `Cancel job` actually stops it.

What makes it fast:
- downloads cap at **720p** (`FAIRCLIP_YTDLP_MAX_HEIGHT`) — 1080p+ doubles the
  download *and* every analysis stage for no visible gain in a 9:16 clip;
- 4 parallel DASH fragments + retries instead of one fragile connection;
- a system **ffmpeg** for the transcode/audio/scene work (5–20× faster than the
  python fallback). If you don't have it the UI says `(no ffmpeg: slow path)`;
- the heavy analysis runs in blocks, so an hour-long video no longer needs
  several GB of RAM (that used to thrash and look like a hang).

On a slow CPU you can also help it along:
```bash
FAIRCLIP_MAX_SOURCE_MINUTES=20      # only fetch the first 20 min of a long video
FAIRCLIP_STEMS_LONG_AFTER_S=300     # switch to the fast 16 kHz stem analysis sooner
```

### “YouTube says: Sign in to confirm you're not a bot”
YouTube throttles anonymous downloads on some networks. Let yt-dlp reuse your
browser session:
```bash
FAIRCLIP_COOKIES_FROM_BROWSER=chrome   # or edge / firefox / brave
```
(close the browser first on Windows). Alternatively export cookies to a file and
set `FAIRCLIP_COOKIES_FILE=/path/cookies.txt`.

### “pip install fails on Windows”
`av` (PyAV) and `numpy` ship wheels for Python 3.11/3.12 — but the old
`requirements.txt` also pulled `piper-tts`, whose native dependency has **no
Windows wheels**, which is what used to break the install and drop you onto the
legacy backend. Those packages are gone (the bookend voice is the vendored
meSpeak engine, no install needed). If pip still complains:
```bat
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r backend\requirements-windows.txt
```

### “Where is my data / how do I clear it”
`backend/data/<job id>/` holds the source, preview, stems and renders;
`backend/data/settings.json` holds the plan. Everything is deleted automatically
after 24 h (`JOB_RETENTION_HOURS`). To wipe everything: stop the backend and
delete `backend/data/`.

### “The demo is slow to generate the first time”
It is a real 100-second 720p video with synthesised dialogue, music and SFX,
rendered frame-by-frame on first use (and cached in `backend/data/demo/`
afterwards). Watch the progress bar on the job screen.

## Fair Use — read this

FairClip is a creative tool, **not legal advice**. Fair use is a case-by-case
doctrine (17 U.S.C. § 107 in the U.S.) that depends on many facts. The
automated transformations (reframe, captions, micro-cuts, ducking, bookend)
help make clips transformative, but they do not guarantee fair use. Get
permission from copyright holders when possible, and consult an attorney
before publishing. You are solely responsible for what you publish.
