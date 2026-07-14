# Running FieldMind locally with Docker

## One-time setup

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

The root `.env` controls host port mappings (read automatically by
`docker compose`, separate from the app-config `.env` files above).
**Frontend defaults to port 3001, not 3000**, since another app is already
running on 3000 on this machine. Adjust `FRONTEND_PORT` / `BACKEND_PORT` /
`MONGO_PORT` in the root `.env` if any of those collide with something
else too.

Edit `backend/.env`:
- Set a real `JWT_SECRET` — generate one with `openssl rand -hex 32`.
- Leave `MONGO_URL` as-is for dev (docker-compose points it at the `mongo`
  container automatically); only change it if you're using an external Mongo.
- Leave `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` blank if you don't need AI
  extraction / receipt OCR / voice transcription yet — everything else
  still works.

`frontend/.env` can usually stay as `REACT_APP_BACKEND_URL=http://localhost:8001`
— but if you also change `BACKEND_PORT` in the root `.env`, update this to
match (it's a separate file; changing one doesn't auto-update the other).

## 1. Local dev (hot-reload, edit with Claude Code, preview on localhost)

```bash
docker compose up --build
```

- Frontend: http://localhost:3001
- Backend: http://localhost:8001/api
- Mongo: localhost:27017 (exposed if you want to inspect it with Compass/mongosh)

Both `backend/` and `frontend/` are bind-mounted into their containers, so
edits you make on your machine (with Claude Code, your editor, whatever) are
picked up live — backend via `uvicorn --reload`, frontend via the CRA dev
server. No rebuild needed for code changes; only rebuild
(`docker compose up --build`) if you change `requirements.txt` or
`package.json`.

To seed demo data (admin/manager/TM accounts) once containers are up:
```bash
# set ENABLE_DEMO_SEED=true in backend/.env first, then:
curl -X POST http://localhost:8001/api/seed/init
```
Turn `ENABLE_DEMO_SEED` back off if this ever runs anywhere internet-facing.

Stop everything:
```bash
docker compose down          # keep the mongo volume (data persists)
docker compose down -v       # also wipe the mongo volume
```

## 2. Production / self-hosted deploy

This assumes deploying all three containers together on one Docker host
(a VPS — DigitalOcean, Hetzner, an EC2 box, etc.). Copy the repo to that
host (or `git clone` it there), set real values in `backend/.env`, then:

```bash
REACT_APP_BACKEND_URL=https://api.your-domain.example \
CORS_ORIGINS=https://your-domain.example \
docker compose -f docker-compose.prod.yml up -d --build
```

- Frontend served on port 80 (put nginx/Caddy/Cloudflare in front for TLS).
- Backend on port 8001.
- `REACT_APP_BACKEND_URL` must be the public URL the browser will reach the
  backend at — it's baked into the JS bundle at build time, so if it
  changes later you need to rebuild the frontend image, not just restart it.

**Alternative:** split hosting — frontend on Vercel, backend on
Render/Railway/Fly, Mongo on Atlas. In that case only `backend/Dockerfile`
and `backend/.env.example` are relevant; skip `docker-compose.prod.yml`
entirely and follow whichever host's own deploy flow. Set
`REACT_APP_BACKEND_URL` in Vercel's project env vars to your backend's
public URL before each deploy.

## Known gaps to be aware of

- **No `yarn.lock` is committed** in this repo, so `yarn install` isn't
  reproducible build-to-build. Worth running `yarn install` once locally
  and committing the resulting `yarn.lock`.
- **Demo credentials are hardcoded** in `backend/seed.py`
  (`admin@field.io` / `admin123`, etc.) — gated behind `ENABLE_DEMO_SEED`,
  but rotate/remove before anything here is internet-facing for real.
