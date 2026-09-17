# legacy/ — the old "MassReels-style" single-file clipper

This folder holds the **first, abandoned iteration** of this project. It is kept
for reference only and is **not part of FairClip**.

| File | What it was |
|------|-------------|
| `massreels_backend.py` | 470-line single-file FastAPI app: `POST /api/jobs {url, start_time, end_time}` → tries `yt-dlp --get-url` + `ffmpeg -c copy`, then `yt-dlp --download-sections`, then a full download. |
| `massreels_web/` | The old Next.js page (port 3000) and its own `package.json` that talked to that backend. |

## Why it is dangerous to run

It is a **second FastAPI app that also binds `:8000`** and it registers a
completely different API:

| Route | legacy backend | FairClip backend |
|-------|----------------|------------------|
| `POST /api/jobs` | `{url, start_time, end_time}` | `{source: {type: demo\|upload\|url\|link, url}}` |
| `PUT /api/settings` | ❌ 404 | ✅ |
| `GET /api/jobs/{id}` | status `queued\|processing\|completed\|failed` | status `queued\|processing\|ready\|error` |
| `POST /api/jobs/{id}/upload` | ❌ 404 | ✅ |

If both are running, the FairClip UI silently talks to this one and every
action fails: `PUT /api/settings` → **404**, `POST /api/jobs` with
`{"source":{"type":"upload"}}` → **422 Unprocessable Content**, and jobs never
reach the `ready` status the UI waits for (it only knows `ready` / `error`), so
the progress screen spins forever.

That exact combination is what produced the bug reports this cleanup fixes.
**Do not run it on port 8000.**

## If you still want to use it

```bash
# terminal 1 — backend on 8001
cd legacy
python -m uvicorn massreels_backend:app --host 127.0.0.1 --port 8001

# terminal 2 — old UI on 3001
cd legacy/massreels_web
npm install
npx next dev -p 3001
```

It needs a system `ffmpeg` on `PATH` and works best for short clips of short
videos. Everything it can do, FairClip does better (see the root `README.md`).
