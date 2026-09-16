# Deploying FairClip

FairClip is two long-running services:

| Service  | Stack                          | CPU profile                          |
|----------|--------------------------------|--------------------------------------|
| `api`    | Python 3.11 · FastAPI · PyAV   | **Heavy** — decodes/composites/encodes video on CPU (~1.2–4× realtime at 720p) |
| `web`    | Node 20 · Next.js 14           | Light — static + proxy rewrites      |

Everything runs with zero external dependencies: no database, no object
storage, no ffmpeg. State lives in the api container's memory + a data
volume (auto-cleaned after 24 h). **Run exactly one `api` instance** —
scale by adding workers later (see "Beyond a single box").

Optional env vars (all fall back to on-device/offline processing if unset):
- `OPENAI_API_KEY` — Whisper transcription + LLM hook writing (without it, users paste the transcript)
- `ELEVENLABS_API_KEY` — higher-quality TTS voices (without it, the vendored meSpeak voice is used)

---

## Option A — single VPS (recommended, ~$5–10/mo)

Any Ubuntu 22.04/24.04 VPS with **4 GB+ RAM** and 2–4 vCPU
(Hetzner CX22/32, DigitalOcean, Vultr…).

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sh

# 2. Code
git clone https://github.com/MoonFros/youtube-clip-hanger.git
cd youtube-clip-hanger
cp .env.example .env      # optional: add API keys

# 3. Build & start
docker compose up -d --build
docker compose logs -f    # watch until both are healthy

# 4. TLS + domain (Caddy, automatic Let's Encrypt)
sudo apt install -y caddy
sudo nano deploy/Caddyfile            # replace your-domain.com
sudo systemctl enable --now caddy
sudo caddy reload --config deploy/Caddyfile   # after DNS A record is live
```

That's it — `https://your-domain.com` serves the app, `/api` and `/media`
are proxied to the backend, uploads up to 2 GB work.

> No domain yet? Change the two `ports:` in `docker-compose.yml` to
> `"8000:8000"` / `"3000:3000"` and open both ports in the firewall —
> you'll reach the app on `http://your-ip:3000` (no TLS, no uploads over
> ~300 MB through some proxies).

## Option B — Railway

1. New project → deploy the repo.
2. **Service 1 (`api`)**: root `backend/` (Dockerfile auto-detected).
   - Attach a **volume** mounted at `/app/data` (settings → volumes).
   - Set vars: `FAIRCLIP_DATA=/app/data` plus any API keys.
   - Public networking off (only the web service needs to reach it).
3. **Service 2 (`web`)**: root `frontend/`.
   - Build var: `FAIRCLIP_BACKEND=http://api:8000` (Railway service name)
     or the api's internal URL (`$${SERVICES.api}`).
   - Generate a public domain.
4. Done — Railway handles TLS, restarts, and logs.

## Option C — Fly.io

```bash
# api (with a volume for media)
cd backend && fly launch --name fairclip-api --no-deploy && fly volumes create fairclip_data --size 10
fly deploy
# then add to fly.toml: [[mounts]] source="fairclip_data" path="/app/data"

# web (FAIRCLIP_BACKEND baked at build time = the api's internal app URL)
cd ../frontend && fly launch --name fairclip-web \
  --build-arg FAIRCLIP_BACKEND=http://fairclip-api:8000
fly deploy
# Proxy the public hostname so /api and /media route to fairclip-api
# (fly proxy / a small edge redirect / Fly's "custom domains" + rules).
```

## Verify

```bash
curl https://your-domain.com/api/health          # {"ok":true,...}
curl -o /dev/null -w "%{http_code}\n" https://your-domain.com/   # 200
```
Then in the browser: click **Demo video → Clip the demo**, render a clip,
check the pre-flight score.

---

## Honest production checklist (what's done vs. what you'd add)

**Works as-is on a real server:**
- ✅ YouTube URL + direct-link download (egress was blocked *only in the dev
  sandbox*; on a normal host yt-dlp works out of the box)
- ✅ Whisper transcription (with `OPENAI_API_KEY`) or pasted transcripts
- ✅ TTS bookend voices (ElevenLabs with a key, offline meSpeak without)
- ✅ All 6 templates, stem separation, pre-flight, tier limits, 24 h cleanup
- ✅ Uploads up to 2 GB, MP4/MOV 30/60 fps, 720p (Pro 1080p)

**Add before charging money / scaling to many users:**
1. **Payments** — the Free/Pro toggle is a local setting. Integrate Stripe
   (checkout + webhook flips `plan` in `STORE.settings`; per-user storage
   needed once accounts exist).
2. **Accounts/auth** — currently anonymous & stateless (no login).
   Supabase/Auth0/Clerk all fit behind the existing API.
3. **Persistence** — jobs/clips are in-memory; the volume keeps media.
   Add SQLite (easiest — one file on the volume) or Postgres, and S3/Cloudflare R2 for media once you go multi-instance or beyond ~100 GB.
4. **Concurrency** — one render per api process (CPU-bound). Keep one
   instance per box and add boxes behind the load balancer, or move
   `run_render` to a queue (Redis/BullMQ or Dramatiq) with worker replicas.
5. **Abuse control** — per-IP rate limiting on `/api/jobs` + uploads
   (Caddy `rate_limit` or a small middleware), and a content filter if
   you'll host public links.

## Operations

- **Data**: `docker compose exec api ls /app/data` — one dir per job
  (preview, stems, TTS wavs, renders). Safe to delete old dirs; the app
  auto-deletes after 24 h.
- **Updates**: `git pull && docker compose up -d --build` (~1 min; the
  in-memory job list resets).
- **Logs**: `docker compose logs -f api web`.
- **Rebuild demo video**: delete `/app/data/demo/demo.mp4`, restart api,
  and hit *Demo video* once (auto-regenerates, ~3–5 min).
