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

Frontend development runs Vite on container port 5173; staging builds `dist/`
and serves it through Nginx on container port 80. Both forward relative `/api/...`
requests to `API_PROXY_TARGET` (default `http://backend:8000`), preserving the full
path and query string. Use an origin without a path or trailing slash. The browser
needs no backend URL or build-time API configuration. Staging reads proxy settings
at container startup; recreate the frontend container after changing them.

Nginx uses Docker DNS to resolve the backend again after container recreation.
It provides SPA fallback, caches hashed `/assets/` files, and serves `index.html`
with revalidation. API requests and missing build assets never use SPA fallback.

For Vite running outside Docker, set `API_PROXY_TARGET` to the published backend
address (for example `API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev` inside
`frontend/`). Vite also reads `frontend/.env`; the root `.env` is read by Compose.
Changing `BACKEND_PORT` changes host access only; Docker proxies continue using
`backend:8000`.

Staging Nginx limits complete request bodies to `FRONTEND_MAX_BODY_SIZE` (default
`12m`), allowing multipart overhead above the default 10 MiB backend image limit.
If increasing `AROMAP_MAX_UPLOAD_BYTES`, increase the Nginx limit to at least that
value plus 1 MiB. Vite has no corresponding body-size cap; the backend enforces its
image limit in both modes.

Compose automatically allows localhost/127.0.0.1 frontend origins at `FRONTEND_PORT`
unless `AROMAP_CORS_ORIGINS` is explicitly set. This is for direct cross-origin API
calls; same-origin proxying does not require CORS. For LAN access, set
`HOST_BIND=0.0.0.0` and configure actual browser origins. Swagger remains directly
accessible on the published backend port independently of frontend routing.

For deployment, build the production targets in CI, push versioned images to GHCR,
and pull them from the server's own Compose configuration. Docker can reuse the
dependency layer when the lockfiles are unchanged. The backend also uses a BuildKit
cache mount for uv downloads without including that cache in the image. Configure
persistent builder caching where available for ephemeral CI runners; cache-mount
persistence depends on the CI builder. Subsequent server pulls reuse unchanged layers.
Staging exercises the image commands, proxy and volume assumptions; server routing
and cloudflared configuration belong to the server deployment.

Start sizing with approximately 2 GiB of memory for the host/container workload,
leaving room for the OS; this is a test target, not a guaranteed minimum. Run the
backend's documented benchmarks and representative recognition and simulation jobs
on the actual host, observe peak memory and runtime, and set the container memory
limit accordingly. The application estimates memory but does not enforce an RSS cap.
Use a persistent writable `/data` volume, check free space before the event, and
monitor it during a load test. The default cleanup retains results for 24 hours.
