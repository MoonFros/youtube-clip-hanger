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
  video work; Whisper/ElevenLabs/LLM hooks are optional upgrades with offline fallbacks

---

## 1) Run locally (dev mode — 2 terminals, ~3 min)

Prereqs: **Python 3.11** and **Node 20** on your machine.

```bash
git clone https://github.com/MoonFros/youtube-clip-hanger.git
cd youtube-clip-hanger
```

**Terminal 1 — backend** (port 8000; creates its own venv automatically):
```bash
cd backend
./run.sh
```

**Terminal 2 — frontend** (port 3000; proxies /api and /media to the backend):
```bash
cd frontend
npm install
npm run dev
```

→ Open **http://localhost:3000**. Click **🎬 Demo video → Clip the demo**
(first time generates the 100s demo clip, ~3–5 min) or use **⬆️ Upload** to bring
your own .mp4 / .mkv / .webm.

Optional (better results, all still work without them):
```bash
export OPENAI_API_KEY=sk-...        # Whisper transcription + LLM hook writing
export ELEVENLABS_API_KEY=el-...    # higher-quality TTS voices
```
Without keys: paste the transcript in the Audio tab, and the built-in offline
voice (meSpeak) narrates the bookend.

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
    engine.py       PyAV decode/encode, muxing (no ffmpeg)
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
docker-compose.yml  single-machine production setup
deploy/Caddyfile    TLS reverse proxy
```

## Tests

```bash
cd backend
.venv/bin/python tests/mk_testvideo.py      # 12s synthetic source
.venv/bin/python tests/pipeline_test.py     # full job → render → preflight
.venv/bin/python tests/tpl_test.py          # all 6 templates end-to-end
```

## Fair Use — read this

FairClip is a creative tool, **not legal advice**. Fair use is a case-by-case
doctrine (17 U.S.C. § 107 in the U.S.) that depends on many facts. The
automated transformations (reframe, captions, micro-cuts, ducking, bookend)
help make clips transformative, but they do not guarantee fair use. Get
permission from copyright holders when possible, and consult an attorney
before publishing. You are solely responsible for what you publish.
