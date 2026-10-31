# Aromap

Indoor scent diffusion simulator for the **Sensation** hackathon. The React frontend
owns editable projects; the FastAPI backend prepares and recognizes floor plans and
runs approximate relative-concentration simulations. See [backend/README.md](backend/README.md)
for API contracts, supported recognition inputs, simulation assumptions, and limits.

## Local development

Requires Docker Compose 2.24.4 or newer. Defaults work without credentials or a
`.env` file; copy [.env.example](.env.example) to `.env` to override them.

```sh
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000; API docs: http://localhost:8000/docs
- Backend readiness: http://localhost:8000/health

The development stack mounts frontend source and backend `app/`, `tests/` and `scripts/` for
reload and testing. Rebuild after changing dependencies or configuration:

```sh
docker compose run --rm --no-deps backend uv run --locked pytest -q
```

## Staging

Staging builds the production targets: Nginx serves the frontend and one backend
process runs without reload or development dependencies. It uses a separate volume
when launched with the project name below:

```sh
docker compose -p aromap-staging -f compose.yaml -f compose.staging.yaml up --build
```

Use the same project name and files for `logs` and `down`. `down` preserves stored
uploads and results; `down -v` deletes the staging volume. To run staging beside
development, set different host ports, for example `FRONTEND_PORT=5174 BACKEND_PORT=8001`.
The host ports default to 5173 and 8000; `HOST_BIND` defaults to `127.0.0.1`.

The frontend proxies relative `/api/...` requests to `API_PROXY_TARGET`, defaulting
to `http://backend:8000` inside Compose. Use an origin without a path or trailing
slash. When Vite runs outside Docker, set this to the published backend address.
Nginx resolves the backend through Docker DNS and reads proxy settings at container
startup; recreate the frontend after changing them. The browser needs no backend URL.

`FRONTEND_MAX_BODY_SIZE` defaults to `12m`, allowing overhead above the backend's
10 MiB image limit. If increasing `AROMAP_MAX_UPLOAD_BYTES`, increase the Nginx
limit by at least 1 MiB as well. Same-origin proxy requests need no CORS setup;
configure `AROMAP_CORS_ORIGINS` for direct browser requests from other origins.
For LAN access, set `HOST_BIND=0.0.0.0` and configure those origins as needed.

## Manual CI and image publishing

In GitHub Actions, **Test staging stack** builds and starts the staging stack, runs
the backend suite in a separate development container, and checks the frontend,
backend health, upload and recognition through the frontend proxy. It collects logs
on failure and removes its temporary stacks and volumes. The same smoke test can run
against a local staging stack with `python3 scripts/smoke_staging.py`.

**Build and publish images** builds `frontend`, `backend`, or `both` for
`linux/amd64` and pushes production images to:

- `ghcr.io/<owner>/aromap-frontend:<commit-sha>`
- `ghcr.io/<owner>/aromap-backend:<commit-sha>`

The full commit SHA identifies the selected revision. Builds from `main` also update
`latest`; use SHA tags on the server and retain the previous tags for rollback. A
single-service run publishes only that service; a `both` run builds both from the
same revision. Manual workflows must exist on the default branch before GitHub can
dispatch them. Publishing uses `GITHUB_TOKEN` with package write permission.
SHA tags identify the source revision but can be overwritten by a rebuild; use an
image digest when an exact, immutable artifact is required.

BuildKit caches frontend and backend layers separately in GitHub Actions. The backend
uses a uv cache mount to avoid embedding downloads in the image; cache mounts do not
persist in the GitHub Actions layer cache by default. Later server pulls can reuse
unchanged image layers.

## Server deployment contract

The server maintains its own Compose configuration and pulls the GHCR images; server
routing and cloudflared configuration are outside this repository. The frontend
listens on container port 80 and defaults to `API_PROXY_TARGET=http://backend:8000`.
The backend listens on port 8000 and needs `AROMAP_DATA_DIR=/data` on a persistent,
writable volume. Run **one backend process and replica**: its bounded in-memory
queue and SQLite registry are designed for a single instance. Jobs are interrupted
on restart, and uploads and results expire after 24 hours by default.

After pulling the chosen tags and starting the server stack, check `/health` and
perform an upload and recognition through the public frontend. The CI smoke test
cannot verify the server's routing or volume permissions. Check free disk before
the event and monitor it during a load test.

Start sizing with roughly 2 GiB of memory for the host/container workload, leaving
room for the OS. This is a test target, not a guaranteed minimum: run representative
recognition and simulation jobs and the [backend benchmarks](backend/README.md) on
the actual host, then set the container limit from observed peak memory. The backend
has resource estimates and deadlines, but does not enforce a hard RSS cap.
