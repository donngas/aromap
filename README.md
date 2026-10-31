# Aromap

Interactive indoor scent diffusion simulator for the **Sensation** hackathon theme.
Planned stack: React frontend and FastAPI backend, with approximate relative concentration simulations.

- `frontend/` — frontend project root (npm).
- `backend/` — backend project root (Python, managed with uv).
- `compose.yaml` — local development with source reload.
- `compose.staging.yaml` — production-style build/commands for staging tests.

The backend provides image uploads and recognition job infrastructure. See
[backend/README.md](backend/README.md) for setup, API contracts, and current scope.

Requires Docker Compose 2.24.4+ (staging uses `!override` / `!reset`).
Optionally copy `.env.example` to `.env` at the root to override defaults. No
credentials are required. Both **host** ports are configurable via `FRONTEND_PORT`
and `BACKEND_PORT`; `HOST_BIND` defaults to `127.0.0.1` (local-only).

Local development:

```sh
docker compose up --build
```

Frontend: http://localhost:5173 · Backend: http://localhost:8000

Swagger: http://localhost:8000/docs · Readiness: http://localhost:8000/health

Only frontend `src/` and `public/` and backend `app/` are hot-mounted. Rebuild for
dependency/configuration changes. Container dependencies are not hidden by source
mounts. Backend tests are also mounted in local development:

```sh
docker compose run --rm --no-deps backend uv run --locked pytest -q
```

Staging uses built frontend assets served on container port 80 and a single backend
process without reload or dev dependencies. No source directories are mounted:

```sh
docker compose -p aromap-staging -f compose.yaml -f compose.staging.yaml up --build
```

Both host ports remain configurable and the backend remains directly accessible.
Use different ports to run local and staging simultaneously, for example:

```sh
FRONTEND_PORT=5174 BACKEND_PORT=8001 docker compose -p aromap-staging \
  -f compose.yaml -f compose.staging.yaml up --build
```

The explicit staging project name isolates its data volume from local development.
Use the same `-p` and `-f` arguments for staging `down`, `logs`, etc. Without `-v`,
`down` retains SQLite/images/results; adding `-v` deletes that stack's volume.
To run just the backend, append `backend` to the appropriate `up` command.

Frontend Docker targets are minimal templates for the FE lead. They require npm
manifests, a `dev` script accepting `--host`/`--port`, and a `build` script producing
`dist/`. If frontend application files are absent, run the backend alone until
the FE lead's work is integrated. The staging template serves `/`
and static assets only: SPA fallback and API proxy/configuration remain with the
FE lead. No frontend application/configuration files are changed by this setup.

The agreed routing contract is browser calls to relative `/api/...` paths. The
FE lead must proxy those paths in Vite for development and Nginx for staging,
preserving the `/api` prefix. Compose now supplies `API_PROXY_TARGET` (default
`http://backend:8000`) to the frontend development service. This variable alone
does not enable a proxy and is not a browser URL; Nginx needs separate configuration.
Until the FE proxy work is implemented, browser clients must explicitly use the
backend's published URL. No frontend-owned files are changed here.

For Vite running outside Docker, set its proxy target to the published backend
address (for example `http://localhost:8000`). The FE lead owns loading that setting
in Vite; the root `.env` is read by Compose, not automatically by host-run Vite.

Changing `BACKEND_PORT` changes host access only; Docker proxies continue using
`backend:8000`. Both serving modes must permit upload requests of at least
`AROMAP_MAX_UPLOAD_BYTES + 1 MiB` including multipart overhead (12 MiB is sufficient
for the default limit). Nginx also needs SPA fallback for frontend routes.

Compose automatically allows localhost/127.0.0.1 frontend origins at `FRONTEND_PORT`
unless `AROMAP_CORS_ORIGINS` is explicitly set. This is for direct cross-origin API
calls; same-origin proxying does not require CORS. For LAN access, set
`HOST_BIND=0.0.0.0` and configure actual browser origins. Swagger remains directly
accessible on the published backend port independently of frontend routing.

An actual production Compose file and cloudflared wiring are intentionally deferred.
