# paax-stream

Audio **stream URL resolution** backend for Paax, powered by [Invidious](https://invidious.io).

> **This service does NOT handle music metadata, search, or catalog.**
> Metadata lives in **[paax-api](https://github.com/uzielcezate/paax-api)** (ytmusicapi).

---

## Architecture

```
Flutter (paax-frontend)
    │
    ├── search / metadata / discovery
    │       └── paax-api  →  ytmusicapi → YouTube Music
    │
    └── audio stream URL
            └── paax-stream (this repo)
                    └── Invidious (?local=true) → CDN stream URL
```

| Service | Repo | Responsibility |
|---|---|---|
| **paax-stream** | uzielcezate/paax-stream | Stream URL resolution (this repo) |
| **paax-api** | uzielcezate/paax-api | Music metadata, search, catalog |
| **paax-frontend** | uzielcezate/Paax | Flutter mobile + web app |

---

## Endpoints

### `GET /health`
Health check for Railway and uptime monitors.

```json
{ "status": "ok", "service": "paax-stream", "provider": "invidious-nerdvpn" }
```

### `GET /resolve/stream/{videoId}`
Resolves the single best playable audio URL for a YouTube videoId.

**Audio selection:**
1. **Tier 1** — `audio/mp4` / M4A (AAC) — widest player compatibility, sorted by highest bitrate
2. **Tier 2** — `audio/webm` / Opus — fallback, sorted by highest bitrate

**Caching:** successful results are cached in memory for `CACHE_TTL_SECONDS`.

```bash
curl https://your-paax-stream.railway.app/resolve/stream/WdSGEvDGZAo
```

```json
{
  "success": true,
  "videoId": "WdSGEvDGZAo",
  "provider": "invidious-nerdvpn",
  "streamUrl": "https://invidious.nerdvpn.de/videoplayback?...",
  "mimeType": "audio/mp4",
  "container": "mp4",
  "bitrate": 131550,
  "cache": { "hit": false, "layer": "provider" }
}
```

### `GET /resolve/formats/{videoId}`
Returns all detected audio formats for debugging. Not called by the Flutter client in production.

```json
{
  "success": true,
  "videoId": "WdSGEvDGZAo",
  "provider": "invidious-nerdvpn",
  "formats": [
    { "mimeType": "audio/mp4", "container": "mp4", "bitrate": 131550, "url": "..." },
    { "mimeType": "audio/webm", "container": "webm", "bitrate": 150932, "url": "..." }
  ]
}
```

---

## About `local=true`

All Invidious requests use `?local=true`:

```
GET https://invidious.nerdvpn.de/api/v1/videos/{videoId}?local=true
```

This makes Invidious rewrite stream URLs to point at itself rather than `googlevideo.com`, so:
- The Flutter client never talks directly to Google's CDN
- The stream URL is routed through the Invidious instance
- This reduces bot-detection risk on the client side

---

## Error Responses

All errors return JSON with `"success": false`:

| Error Code | HTTP | Meaning |
|---|---|---|
| `INVALID_VIDEO_ID` | 400 | videoId is malformed or empty |
| `NO_AUDIO_FORMATS` | 422 | Video exists but has no playable audio |
| `PROVIDER_TIMEOUT` | 504 | Invidious request timed out |
| `PROVIDER_ERROR` | 502 | Invidious returned a non-200 response |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `INVIDIOUS_BASE_URL` | `https://invidious.nerdvpn.de` | Invidious instance base URL |
| `REQUEST_TIMEOUT_MS` | `8000` | HTTP timeout for Invidious requests (ms) |
| `CACHE_TTL_SECONDS` | `600` | In-memory cache TTL (seconds) |
| `FRONTEND_ORIGINS` | `*` | CORS origins (comma-separated or `*`) |
| `LOG_LEVEL` | `info` | Logging verbosity (`debug`/`info`/`warning`) |
| `PORT` | `8080` | Server port (Railway sets this automatically) |

---

## Running Locally

```bash
# 1. Clone
git clone https://github.com/uzielcezate/paax-stream.git
cd paax-stream

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env             # edit if needed

# 5. Start
uvicorn app.main:app --reload --port 8080
```

Open `http://localhost:8080/docs` for the interactive API explorer.

**Test resolution:**
```bash
curl http://localhost:8080/resolve/stream/WdSGEvDGZAo
```

**Override port:**
```bash
PORT=9000 uvicorn app.main:app --host 0.0.0.0 --port 9000
```

---

## Deploying to Railway

1. Connect this repo to a new Railway service.
2. Railway auto-detects `Procfile` and starts with:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
   ```
3. Set environment variables in Railway dashboard (all optional — defaults work for Phase 1):

| Variable | Recommended |
|---|---|
| `INVIDIOUS_BASE_URL` | `https://invidious.nerdvpn.de` |
| `FRONTEND_ORIGINS` | Your Flutter app / production URL |
| `CACHE_TTL_SECONDS` | `600` |
| `LOG_LEVEL` | `info` |

4. Health check is at `/health` — Railway uses this automatically via `railway.json`.

---

## File Structure

```
paax-stream/
├── app/
│   ├── main.py                    # FastAPI entry point
│   ├── config.py                  # Environment-based config
│   ├── models.py                  # Pydantic response models
│   ├── routes/
│   │   ├── health.py              # GET /health
│   │   └── resolve.py             # GET /resolve/stream|formats/{videoId}
│   ├── services/
│   │   ├── invidious_service.py   # Invidious HTTP client
│   │   ├── stream_selector.py     # Audio format ranking
│   │   └── cache_service.py       # In-memory TTL cache
│   └── utils/
│       ├── logging.py             # Structured logger
│       └── errors.py              # Custom exceptions + helpers
├── requirements.txt
├── .env.example
├── Procfile
├── railway.json
└── README.md
```

---

## Phase 1 Scope

- ✅ Single Invidious provider (`invidious.nerdvpn.de`)
- ✅ In-memory caching (no Redis yet)
- ✅ `audio/mp4` → `audio/webm` fallback selection
- ⏳ Multiple Invidious providers with failover → Phase 2
- ⏳ Redis cache → Phase 2
- ⏳ Prefetch endpoint → Phase 2
